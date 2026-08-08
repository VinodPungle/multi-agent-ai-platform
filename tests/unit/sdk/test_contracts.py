"""SDK contract behaviour.

The SDK is the surface every future provider compiles against, so its
guarantees — immutability, structural typing, capability-based routing — are
worth pinning before any provider exists to depend on them.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError as PydanticValidationError

from agent_platform_sdk import (
    Capability,
    CompletionRequest,
    CompletionResponse,
    ExecutionContext,
    LLMProvider,
    Message,
    MessageRole,
    ModelDescriptor,
    Provider,
    ResponseFormat,
    TokenUsage,
)
from agent_platform_sdk.policies import BudgetPolicy, RetryPolicy
from agent_platform_sdk.schemas import tool_schema_from_model
from agent_platform_sdk.types.enums import ErrorCategory

pytestmark = pytest.mark.unit


class TestExecutionContextImmutability:
    """A context captured by a background task must not change underneath it."""

    def test_context_cannot_be_mutated(self) -> None:
        context = ExecutionContext()

        with pytest.raises(PydanticValidationError):
            context.agent_id = "chat-agent"

    def test_derive_returns_a_new_context(self) -> None:
        original = ExecutionContext(conversation_id="conv-1")

        derived = original.derive(agent_id="chat-agent")

        assert derived is not original
        assert derived.agent_id == "chat-agent"
        assert original.agent_id is None

    def test_derive_preserves_the_correlation_id(self) -> None:
        """The whole execution tree must stay joinable in telemetry."""
        original = ExecutionContext()

        derived = original.derive(agent_id="research-agent", execution_id="exec-1")

        assert derived.correlation_id == original.correlation_id

    def test_identifiers_are_generated_when_not_supplied(self) -> None:
        first = ExecutionContext()
        second = ExecutionContext()

        assert first.correlation_id != second.correlation_id
        assert first.request_id != first.correlation_id

    def test_log_fields_omit_unset_identifiers(self) -> None:
        """Records stay compact and queries need not filter nulls."""
        fields = ExecutionContext(agent_id="chat-agent").to_log_fields()

        assert fields["agent_id"] == "chat-agent"
        assert "conversation_id" not in fields
        assert "model_id" not in fields

    def test_unknown_field_is_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            ExecutionContext(agnet_id="typo")  # type: ignore[call-arg]  # deliberate typo


class TestStructuralTyping:
    """Providers satisfy contracts without importing a platform base class."""

    def test_a_class_satisfies_provider_without_inheriting(self) -> None:
        class StandaloneProvider:
            @property
            def provider_id(self) -> str:
                return "standalone"

            async def initialize(self) -> None: ...

            async def health_check(self) -> object: ...

            def supports(self, capability: Capability) -> bool:
                return False

            async def close(self) -> None: ...

        assert isinstance(StandaloneProvider(), Provider)

    def test_an_incomplete_class_does_not_satisfy_the_contract(self) -> None:
        class Incomplete:
            @property
            def provider_id(self) -> str:
                return "incomplete"

        assert not isinstance(Incomplete(), Provider)
        assert not isinstance(Incomplete(), LLMProvider)


class TestCapabilityRouting:
    """Routing checks capability, never provider identity."""

    def test_declared_capabilities_are_reported(self) -> None:
        model = ModelDescriptor(
            model_id="gemma-4",
            provider_id="azure-foundry",
            display_name="Gemma 4",
            capabilities=frozenset({Capability.STREAMING, Capability.TOOL_CALLING}),
            max_context_tokens=8192,
            max_output_tokens=4096,
        )

        assert model.supports(Capability.STREAMING) is True
        assert model.supports(Capability.VISION) is False

    def test_a_model_with_no_declared_capabilities_supports_nothing(self) -> None:
        """The safe default: an undeclared capability is treated as absent."""
        model = ModelDescriptor(
            model_id="minimal",
            provider_id="test",
            display_name="Minimal",
            max_context_tokens=1024,
            max_output_tokens=256,
        )

        assert all(not model.supports(capability) for capability in Capability)


class TestTokenAccounting:
    """Cost is derived from these numbers, so the arithmetic matters."""

    def test_total_is_the_sum_of_prompt_and_completion(self) -> None:
        usage = TokenUsage(prompt_tokens=100, completion_tokens=25)

        assert usage.total_tokens == 125

    def test_negative_token_counts_are_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            TokenUsage(prompt_tokens=-1)

    def test_pricing_uses_decimal_not_float(self) -> None:
        """Summing float costs over millions of calls accumulates error."""
        model = ModelDescriptor(
            model_id="priced",
            provider_id="test",
            display_name="Priced",
            max_context_tokens=1024,
            max_output_tokens=256,
        )

        assert isinstance(model.pricing.input_cost_per_million_tokens, Decimal)


class TestCompletionRequestValidation:
    """Invalid model parameters must fail before a provider is called."""

    @pytest.mark.parametrize("temperature", [-0.1, 2.1])
    def test_temperature_outside_range_is_rejected(self, temperature: float) -> None:
        with pytest.raises(PydanticValidationError):
            CompletionRequest(
                model_id="gemma-4",
                messages=(Message(role=MessageRole.USER, content="hello"),),
                temperature=temperature,
            )

    def test_non_positive_output_token_cap_is_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            CompletionRequest(
                model_id="gemma-4",
                messages=(),
                max_output_tokens=0,
            )

    def test_none_temperature_defers_to_the_model_default(self) -> None:
        request = CompletionRequest(model_id="gemma-4", messages=())

        assert request.temperature is None

    @pytest.mark.parametrize("top_p", [0.0, 1.1])
    def test_top_p_outside_range_is_rejected(self, top_p: float) -> None:
        with pytest.raises(PydanticValidationError):
            CompletionRequest(model_id="gemma-4", messages=(), top_p=top_p)

    def test_optional_parameters_default_to_provider_behaviour(self) -> None:
        """An unset parameter must not be sent as a value the caller never chose."""
        request = CompletionRequest(model_id="gemma-4", messages=())

        assert request.system_prompt is None
        assert request.top_p is None
        assert request.response_format is None
        assert request.metadata == {}


class TestCommonContractIsOpenAIShaped:
    """The contract is written in the dialect every OpenAI-compatible endpoint speaks.

    Not cosmetic: it is what makes an adapter for such an endpoint a rename
    rather than a translation layer (``architecture.md`` §30).
    """

    def test_the_request_carries_the_documented_common_fields(self) -> None:
        expected = {
            "model_id",
            "messages",
            "system_prompt",
            "temperature",
            "top_p",
            "max_output_tokens",
            "stop_sequences",
            "tool_ids",
            "response_format",
            "metadata",
        }

        assert set(CompletionRequest.model_fields) == expected

    def test_the_response_carries_the_documented_common_fields(self) -> None:
        expected = {
            "message",
            "model_id",
            "provider_id",
            "usage",
            "estimated_cost",
            "latency_ms",
            "finish_reason",
            "provider_metadata",
            "model_metadata",
        }

        assert set(CompletionResponse.model_fields) == expected

    def test_response_metadata_is_flat_strings(self) -> None:
        """Vendor objects must be flattened at the provider boundary, not carried."""
        response = CompletionResponse(
            message=Message(role=MessageRole.ASSISTANT, content="hi"),
            model_id="gemma-4",
            provider_id="azure-foundry",
            provider_metadata={"upstream_request_id": "abc-123"},
            model_metadata={"deployment": "gemma-4-managed"},
        )

        assert response.provider_metadata["upstream_request_id"] == "abc-123"
        assert response.model_metadata["deployment"] == "gemma-4-managed"

    def test_response_format_uses_the_openai_vocabulary(self) -> None:
        assert ResponseFormat.JSON_OBJECT.value == "json_object"
        assert ResponseFormat.TEXT.value == "text"


class TestRetryPolicy:
    """Retrying a deterministic failure wastes budget and delays the real error."""

    @pytest.mark.parametrize(
        "category",
        [ErrorCategory.NETWORK, ErrorCategory.PROVIDER, ErrorCategory.TIMEOUT],
    )
    def test_transient_categories_are_retryable(self, category: ErrorCategory) -> None:
        assert RetryPolicy().is_retryable(category) is True

    @pytest.mark.parametrize(
        "category",
        [
            ErrorCategory.VALIDATION,
            ErrorCategory.POLICY_VIOLATION,
            ErrorCategory.CONFIGURATION,
            ErrorCategory.NOT_FOUND,
        ],
    )
    def test_deterministic_categories_are_not_retryable(self, category: ErrorCategory) -> None:
        assert RetryPolicy().is_retryable(category) is False

    def test_a_single_attempt_disables_retrying(self) -> None:
        assert RetryPolicy(max_attempts=1).max_attempts == 1

    def test_zero_attempts_is_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            RetryPolicy(max_attempts=0)

    def test_jitter_is_on_by_default(self) -> None:
        """Without it, replicas that fail together retry together."""
        assert RetryPolicy().jitter is True


class TestBudgetPolicy:
    """Milestone 01 introduces no behaviour; later milestones opt in explicitly."""

    def test_all_limits_default_to_unlimited(self) -> None:
        policy = BudgetPolicy()

        assert policy.max_total_tokens is None
        assert policy.max_cost is None
        assert policy.max_tool_invocations is None
        assert policy.max_model_calls is None

    @pytest.mark.parametrize("limit", [0, -1])
    def test_non_positive_limits_are_rejected(self, limit: int) -> None:
        with pytest.raises(PydanticValidationError):
            BudgetPolicy(max_total_tokens=limit)


class TestToolSchemaDerivation:
    """One declaration feeds tool calling, OpenAPI and argument validation."""

    def test_a_flat_model_produces_a_json_schema(self) -> None:
        from pydantic import BaseModel, Field

        class SearchArgs(BaseModel):
            query: str = Field(description="What to search for.")
            max_results: int = 5

        schema = tool_schema_from_model(SearchArgs)

        assert schema["type"] == "object"
        assert "query" in schema["properties"]
        assert schema["required"] == ["query"]

    def test_nested_models_are_inlined(self) -> None:
        """Several providers reject or mishandle `$ref` in tool declarations."""
        from pydantic import BaseModel

        class Filter(BaseModel):
            field_name: str

        class QueryArgs(BaseModel):
            query: str
            filter: Filter

        schema = tool_schema_from_model(QueryArgs)

        assert "$defs" not in schema
        assert schema["properties"]["filter"]["type"] == "object"
        assert "field_name" in schema["properties"]["filter"]["properties"]
