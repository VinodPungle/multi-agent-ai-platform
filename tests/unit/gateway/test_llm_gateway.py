"""LLM Gateway behaviour.

The gateway is the seam that keeps provider concerns out of business logic, so
these tests pin the two things that seam promises: that a provider-neutral
request reaches the provider unaltered, and that every policy the runtime would
otherwise have to implement itself — retry, timeout, cost, latency — is applied
here, identically, for any provider.

No provider implementation exists yet. That is the point: a fake satisfies
`LLMProvider` structurally and the gateway cannot tell the difference, which is
the same guarantee that will let Azure AI Foundry be swapped for an
OpenAI-compatible endpoint.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from agent_platform.exceptions.base import (
    ConfigurationError,
    NotFoundError,
    PlatformTimeoutError,
    ProviderError,
    ValidationError,
)
from agent_platform.gateway.llm_gateway import DefaultLLMGateway
from agent_platform.gateway.registry_resolver import RegistryBackedProviderResolver
from agent_platform.registries import KeyedRegistry
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.contracts.health import ComponentHealth
from agent_platform_sdk.dto.completion import (
    CompletionChunk,
    CompletionRequest,
    CompletionResponse,
    TokenUsage,
)
from agent_platform_sdk.dto.message import Message
from agent_platform_sdk.dto.model import ModelDescriptor
from agent_platform_sdk.interfaces.llm_gateway import LLMGateway
from agent_platform_sdk.interfaces.llm_provider import LLMProvider
from agent_platform_sdk.interfaces.llm_provider_resolver import LLMProviderResolver
from agent_platform_sdk.policies.retry import RetryPolicy
from agent_platform_sdk.policies.timeout import TimeoutPolicy
from agent_platform_sdk.types.enums import Capability, HealthStatus, MessageRole

pytestmark = pytest.mark.unit

MODEL_ID = "gemma-4"


class ManualClock:
    """A clock that only moves when a test moves it.

    Declared here rather than imported from ``tests/conftest.py``: ``tests`` is
    not an importable package, so a shared helper is reachable as a fixture but
    not as a type. Latency assertions need the concrete type.
    """

    def __init__(self) -> None:
        self._monotonic = 0.0

    def now(self) -> datetime:
        return datetime(2026, 1, 1, tzinfo=UTC)

    def monotonic(self) -> float:
        return self._monotonic

    def advance(self, seconds: float) -> None:
        """Move the monotonic counter forward by ``seconds``."""
        self._monotonic += seconds


def a_request(**overrides: object) -> CompletionRequest:
    """Build a minimal valid completion request."""
    fields: dict[str, object] = {
        "model_id": MODEL_ID,
        "messages": (Message(role=MessageRole.USER, content="hello"),),
    }
    fields.update(overrides)
    return CompletionRequest(**fields)  # type: ignore[arg-type]  # keyword forwarding


class FakeLLMProvider:
    """A provider that records what it was asked and returns what it was told to.

    Satisfies :class:`LLMProvider` structurally — it inherits nothing, which is
    what ADR-0004 buys.
    """

    def __init__(
        self,
        provider_id: str = "fake-provider",
        *,
        response: CompletionResponse | None = None,
        failures: tuple[Exception, ...] = (),
        chunks: tuple[CompletionChunk, ...] = (),
        cost: Decimal = Decimal("0.42"),
    ) -> None:
        self._provider_id = provider_id
        self._response = response
        self._failures = list(failures)
        self._chunks = chunks
        self._cost = cost

        self.generate_calls: list[tuple[CompletionRequest, ExecutionContext]] = []
        self.stream_calls: list[tuple[CompletionRequest, ExecutionContext]] = []
        self.count_tokens_calls: list[CompletionRequest] = []
        self.estimate_cost_calls: list[tuple[str, TokenUsage]] = []
        self.stream_closed = False

    @property
    def provider_id(self) -> str:
        return self._provider_id

    async def initialize(self) -> None: ...

    async def health_check(self) -> ComponentHealth:
        return ComponentHealth(name=self._provider_id, status=HealthStatus.HEALTHY)

    def supports(self, capability: Capability) -> bool:
        return capability is Capability.STREAMING

    async def close(self) -> None: ...

    async def generate(
        self,
        request: CompletionRequest,
        context: ExecutionContext,
    ) -> CompletionResponse:
        self.generate_calls.append((request, context))
        if self._failures:
            raise self._failures.pop(0)
        return self._response or CompletionResponse(
            message=Message(role=MessageRole.ASSISTANT, content="hi"),
            model_id=request.model_id,
            provider_id=self._provider_id,
        )

    async def stream(
        self,
        request: CompletionRequest,
        context: ExecutionContext,
    ) -> AsyncIterator[CompletionChunk]:
        self.stream_calls.append((request, context))
        if self._failures:
            raise self._failures.pop(0)
        try:
            for chunk in self._chunks:
                yield chunk
        finally:
            self.stream_closed = True

    async def count_tokens(self, request: CompletionRequest) -> TokenUsage:
        self.count_tokens_calls.append(request)
        return TokenUsage(prompt_tokens=11)

    def estimate_cost(self, model_id: str, usage: TokenUsage) -> Decimal:
        self.estimate_cost_calls.append((model_id, usage))
        return self._cost

    async def list_models(self) -> tuple[ModelDescriptor, ...]:
        return ()


def build_gateway(
    *providers: LLMProvider,
    default_provider_id: str | None = None,
    retry: RetryPolicy | None = None,
    timeout: TimeoutPolicy | None = None,
    clock: ManualClock | None = None,
) -> DefaultLLMGateway:
    """Assemble a gateway over ``providers`` with fast, deterministic policies."""
    return DefaultLLMGateway(
        resolver=RegistryBackedProviderResolver(
            providers,
            KeyedRegistry("model"),
            default_provider_id=default_provider_id,
        ),
        clock=clock or ManualClock(),
        # Sub-millisecond backoff without jitter: retry *behaviour* is what is
        # under test, not how long the platform waits between attempts.
        retry_policy=retry or RetryPolicy(initial_backoff_seconds=0.001, jitter=False),
        timeout_policy=timeout or TimeoutPolicy(),
    )


class TestContractConformance:
    """Consumers depend on the protocol, so the implementation must satisfy it."""

    def test_gateway_satisfies_the_gateway_contract(self) -> None:
        assert isinstance(build_gateway(FakeLLMProvider()), LLMGateway)

    def test_resolver_satisfies_the_resolver_contract(self) -> None:
        assert isinstance(
            RegistryBackedProviderResolver((), KeyedRegistry("model")), LLMProviderResolver
        )

    def test_fake_provider_satisfies_the_provider_contract(self) -> None:
        """Structural typing: the fake inherits nothing from the platform."""
        assert isinstance(FakeLLMProvider(), LLMProvider)


class TestProviderNeutrality:
    """The provider must receive exactly what the caller wrote."""

    async def test_the_request_reaches_the_provider_unaltered(self) -> None:
        provider = FakeLLMProvider()
        gateway = build_gateway(provider)
        request = a_request(temperature=0.1, top_p=0.9, metadata={"experiment": "a"})

        await gateway.generate(request, ExecutionContext())

        assert provider.generate_calls[0][0] == request

    async def test_the_resolved_provider_and_model_are_stamped_on_the_context(self) -> None:
        """Telemetry must record what served the call, not what was asked for."""
        provider = FakeLLMProvider(provider_id="azure-foundry")
        gateway = build_gateway(provider)

        await gateway.generate(a_request(), ExecutionContext())

        _, context = provider.generate_calls[0]
        assert context.provider_id == "azure-foundry"
        assert context.model_id == MODEL_ID

    async def test_the_caller_context_is_not_mutated(self) -> None:
        provider = FakeLLMProvider()
        gateway = build_gateway(provider)
        context = ExecutionContext()

        await gateway.generate(a_request(), context)

        assert context.provider_id is None


class TestProviderResolution:
    """Selection is deterministic, and ambiguity is an error rather than a guess."""

    async def test_the_single_registered_provider_is_used(self) -> None:
        provider = FakeLLMProvider()
        gateway = build_gateway(provider)

        response = await gateway.generate(a_request(), ExecutionContext())

        assert response.provider_id == "fake-provider"

    async def test_no_registered_provider_is_a_not_found_error(self) -> None:
        gateway = build_gateway()

        with pytest.raises(NotFoundError, match="No LLM provider is registered"):
            await gateway.generate(a_request(), ExecutionContext())

    async def test_a_pinned_provider_id_wins(self) -> None:
        first = FakeLLMProvider(provider_id="first")
        second = FakeLLMProvider(provider_id="second")
        gateway = build_gateway(first, second, default_provider_id="first")

        await gateway.generate(a_request(), ExecutionContext(provider_id="second"))

        assert second.generate_calls
        assert not first.generate_calls

    async def test_an_unknown_provider_id_is_a_not_found_error(self) -> None:
        gateway = build_gateway(FakeLLMProvider())

        with pytest.raises(NotFoundError, match="No LLM provider registered under id"):
            await gateway.generate(a_request(), ExecutionContext(provider_id="nope"))

    async def test_several_providers_without_a_default_is_an_error(self) -> None:
        """Choosing for the operator would be routing, and routing is not implemented."""
        gateway = build_gateway(FakeLLMProvider("first"), FakeLLMProvider("second"))

        with pytest.raises(NotFoundError, match="no default is configured"):
            await gateway.generate(a_request(), ExecutionContext())

    def test_duplicate_provider_ids_are_rejected_at_construction(self) -> None:
        with pytest.raises(ConfigurationError, match="Duplicate LLM provider id"):
            RegistryBackedProviderResolver(
                (FakeLLMProvider("same"), FakeLLMProvider("same")), KeyedRegistry("model")
            )

    def test_a_default_naming_an_unregistered_provider_is_rejected(self) -> None:
        """A typo in configuration must fail at startup, not on a user's request."""
        with pytest.raises(ConfigurationError, match="is not registered"):
            RegistryBackedProviderResolver(
                (FakeLLMProvider("real"),), KeyedRegistry("model"), default_provider_id="typo"
            )


class TestRequestValidation:
    """A request that no provider could serve must not cost a call."""

    async def test_a_blank_model_id_is_rejected(self) -> None:
        provider = FakeLLMProvider()
        gateway = build_gateway(provider)

        with pytest.raises(ValidationError, match="must name a model"):
            await gateway.generate(a_request(model_id="  "), ExecutionContext())

        assert not provider.generate_calls

    async def test_an_empty_request_is_rejected(self) -> None:
        provider = FakeLLMProvider()
        gateway = build_gateway(provider)

        with pytest.raises(ValidationError, match="at least one message"):
            await gateway.generate(a_request(messages=()), ExecutionContext())

        assert not provider.generate_calls

    async def test_a_system_prompt_alone_is_a_valid_request(self) -> None:
        gateway = build_gateway(FakeLLMProvider())

        response = await gateway.generate(
            a_request(messages=(), system_prompt="Summarise the document."),
            ExecutionContext(),
        )

        assert response.message.content == "hi"


class TestResponseNormalisation:
    """Downstream code must not need to know which provider answered."""

    async def test_latency_is_filled_in_when_the_provider_omits_it(self) -> None:
        clock = ManualClock()

        class TickingProvider(FakeLLMProvider):
            """Advances the injected clock so the assertion is exact, not timing-dependent."""

            async def generate(
                self,
                request: CompletionRequest,
                context: ExecutionContext,
            ) -> CompletionResponse:
                clock.advance(1.5)
                return await super().generate(request, context)

        provider = TickingProvider()
        gateway = build_gateway(provider, clock=clock)

        response = await gateway.generate(a_request(), ExecutionContext())

        assert response.latency_ms == pytest.approx(1500.0)

    async def test_a_provider_reported_latency_is_preserved(self) -> None:
        provider = FakeLLMProvider(
            response=CompletionResponse(
                message=Message(role=MessageRole.ASSISTANT, content="hi"),
                model_id=MODEL_ID,
                provider_id="fake-provider",
                latency_ms=99.0,
            )
        )
        gateway = build_gateway(provider)

        response = await gateway.generate(a_request(), ExecutionContext())

        assert response.latency_ms == 99.0

    async def test_cost_is_estimated_when_the_provider_omits_it(self) -> None:
        provider = FakeLLMProvider(
            response=CompletionResponse(
                message=Message(role=MessageRole.ASSISTANT, content="hi"),
                model_id=MODEL_ID,
                provider_id="fake-provider",
                usage=TokenUsage(prompt_tokens=10, completion_tokens=5),
            ),
            cost=Decimal("0.25"),
        )
        gateway = build_gateway(provider)

        response = await gateway.generate(a_request(), ExecutionContext())

        assert response.estimated_cost == Decimal("0.25")
        assert provider.estimate_cost_calls == [
            (MODEL_ID, TokenUsage(prompt_tokens=10, completion_tokens=5))
        ]

    async def test_cost_is_not_estimated_when_no_tokens_were_used(self) -> None:
        """A zero-token response means the provider reported nothing to price."""
        provider = FakeLLMProvider()
        gateway = build_gateway(provider)

        response = await gateway.generate(a_request(), ExecutionContext())

        assert response.estimated_cost is None
        assert not provider.estimate_cost_calls


class TestRetryPolicy:
    """Retrying the wrong failure wastes budget and hides the real error."""

    async def test_a_transient_provider_failure_is_retried(self) -> None:
        provider = FakeLLMProvider(failures=(ProviderError("upstream 503"),))
        gateway = build_gateway(provider)

        response = await gateway.generate(a_request(), ExecutionContext())

        assert len(provider.generate_calls) == 2
        assert response.message.content == "hi"

    async def test_retries_stop_at_the_configured_limit(self) -> None:
        provider = FakeLLMProvider(failures=tuple(ProviderError("boom") for _ in range(5)))
        gateway = build_gateway(
            provider,
            retry=RetryPolicy(max_attempts=3, initial_backoff_seconds=0.001, jitter=False),
        )

        with pytest.raises(ProviderError, match="boom"):
            await gateway.generate(a_request(), ExecutionContext())

        assert len(provider.generate_calls) == 3

    async def test_a_deterministic_failure_is_not_retried(self) -> None:
        provider = FakeLLMProvider(failures=(ValidationError("prompt too long"),))
        gateway = build_gateway(provider)

        with pytest.raises(ValidationError):
            await gateway.generate(a_request(), ExecutionContext())

        assert len(provider.generate_calls) == 1

    async def test_max_attempts_of_one_disables_retrying(self) -> None:
        provider = FakeLLMProvider(failures=(ProviderError("boom"), ProviderError("boom")))
        gateway = build_gateway(provider, retry=RetryPolicy(max_attempts=1))

        with pytest.raises(ProviderError):
            await gateway.generate(a_request(), ExecutionContext())

        assert len(provider.generate_calls) == 1


class TestUnexpectedProviderFailures:
    """A provider that breaks its contract must not break the platform."""

    async def test_an_unhandled_exception_becomes_a_provider_error(self) -> None:
        provider = FakeLLMProvider(failures=(RuntimeError("connection string is bad"),))
        gateway = build_gateway(provider)

        with pytest.raises(ProviderError) as raised:
            await gateway.generate(a_request(), ExecutionContext())

        assert raised.value.provider_id == "fake-provider"
        assert "RuntimeError" in raised.value.message

    async def test_the_original_message_is_not_exposed(self) -> None:
        """Provider exception text can carry an endpoint or a credential fragment."""
        provider = FakeLLMProvider(failures=(RuntimeError("key=SECRET123"),))
        gateway = build_gateway(provider)

        with pytest.raises(ProviderError) as raised:
            await gateway.generate(a_request(), ExecutionContext())

        assert "SECRET123" not in raised.value.message

    async def test_an_unhandled_exception_is_not_retried(self) -> None:
        """The platform has no basis for calling a contract violation transient."""
        provider = FakeLLMProvider(failures=(RuntimeError("x"), RuntimeError("x")))
        gateway = build_gateway(provider)

        with pytest.raises(ProviderError):
            await gateway.generate(a_request(), ExecutionContext())

        assert len(provider.generate_calls) == 1

    async def test_the_cause_is_preserved_for_diagnosis(self) -> None:
        original = RuntimeError("original")
        gateway = build_gateway(FakeLLMProvider(failures=(original,)))

        with pytest.raises(ProviderError) as raised:
            await gateway.generate(a_request(), ExecutionContext())

        assert raised.value.__cause__ is original


class TestTimeoutPolicy:
    """A hung provider must not hold a request open indefinitely."""

    async def test_a_slow_call_raises_a_platform_timeout(self) -> None:
        class HangingProvider(FakeLLMProvider):
            async def generate(
                self,
                request: CompletionRequest,
                context: ExecutionContext,
            ) -> CompletionResponse:
                await asyncio.sleep(5)
                raise AssertionError("unreachable: the timeout must fire first")

        gateway = build_gateway(
            HangingProvider(),
            retry=RetryPolicy(max_attempts=1),
            timeout=TimeoutPolicy(model_call_seconds=0.01),
        )

        with pytest.raises(PlatformTimeoutError, match="exceeded"):
            await gateway.generate(a_request(), ExecutionContext())


class TestStreaming:
    """Streaming is coordinated, not retried."""

    async def test_chunks_are_yielded_in_order(self) -> None:
        chunks = (
            CompletionChunk(delta="Hel"),
            CompletionChunk(delta="lo"),
            CompletionChunk(finish_reason="stop"),
        )
        gateway = build_gateway(FakeLLMProvider(chunks=chunks))

        received = [chunk async for chunk in gateway.stream(a_request(), ExecutionContext())]

        assert received == list(chunks)

    async def test_the_provider_receives_the_resolved_context(self) -> None:
        provider = FakeLLMProvider(chunks=(CompletionChunk(delta="a"),))
        gateway = build_gateway(provider)

        _ = [chunk async for chunk in gateway.stream(a_request(), ExecutionContext())]

        assert provider.stream_calls[0][1].provider_id == "fake-provider"

    async def test_a_failing_stream_is_not_retried(self) -> None:
        """A partially delivered answer cannot be replayed."""
        provider = FakeLLMProvider(failures=(ProviderError("upstream 503"),))
        gateway = build_gateway(provider)

        with pytest.raises(ProviderError):
            _ = [chunk async for chunk in gateway.stream(a_request(), ExecutionContext())]

        assert len(provider.stream_calls) == 1

    async def test_an_empty_stream_yields_nothing(self) -> None:
        gateway = build_gateway(FakeLLMProvider(chunks=()))

        received = [chunk async for chunk in gateway.stream(a_request(), ExecutionContext())]

        assert received == []

    async def test_an_abandoned_stream_is_closed(self) -> None:
        """A client disconnecting mid-response is routine; leaking its connection is not."""
        provider = FakeLLMProvider(
            chunks=tuple(CompletionChunk(delta=str(index)) for index in range(10))
        )
        gateway = build_gateway(provider)

        stream = gateway.stream(a_request(), ExecutionContext())
        assert await anext(stream) == CompletionChunk(delta="0")
        await stream.aclose()

        assert provider.stream_closed is True

    async def test_validation_happens_before_the_provider_is_called(self) -> None:
        provider = FakeLLMProvider(chunks=(CompletionChunk(delta="a"),))
        gateway = build_gateway(provider)

        with pytest.raises(ValidationError):
            _ = [
                chunk async for chunk in gateway.stream(a_request(messages=()), ExecutionContext())
            ]

        assert not provider.stream_calls


class TestAccountingDelegation:
    """Token counting and pricing belong to the provider; the gateway routes them."""

    async def test_count_tokens_reaches_the_resolved_provider(self) -> None:
        provider = FakeLLMProvider()
        gateway = build_gateway(provider)

        usage = await gateway.count_tokens(a_request(), ExecutionContext())

        assert usage.prompt_tokens == 11
        assert provider.count_tokens_calls

    async def test_estimate_cost_reaches_the_resolved_provider(self) -> None:
        provider = FakeLLMProvider(cost=Decimal("1.75"))
        gateway = build_gateway(provider)

        cost = await gateway.estimate_cost(
            MODEL_ID,
            TokenUsage(prompt_tokens=1000),
            ExecutionContext(),
        )

        assert cost == Decimal("1.75")
