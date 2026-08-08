"""Azure AI Foundry provider behaviour.

Driven through a fake `ChatCompletionsClient`, so the whole adapter — message
translation, tool calls, usage, cost, error mapping, streaming, cleanup — is
exercised with no network call, no credential and no Azure subscription.

That matters beyond convenience: this suite has to pass in CI, on a laptop with
no Azure access, and for a contributor who has never run `az login`. A test that
needed a live endpoint would be skipped everywhere and would therefore protect
nothing.

The one thing these cannot prove is that the real service accepts what we send.
That was verified separately against a live deployment — see the milestone
record, which also states exactly how many calls that took and why.
"""

from __future__ import annotations

import time
from decimal import Decimal
from types import TracebackType
from typing import Any

import pytest
from azure.ai.inference.models import CompletionsFinishReason
from azure.core.credentials import AccessToken
from azure.core.exceptions import (
    ClientAuthenticationError,
    HttpResponseError,
    ServiceRequestError,
)

from agent_platform.exceptions.base import ConfigurationError, ProviderError
from agent_platform.providers.azure_foundry.azure_foundry_provider import AzureFoundryProvider
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.dto.completion import CompletionRequest
from agent_platform_sdk.dto.message import Message
from agent_platform_sdk.dto.tool import ToolDescriptor  # noqa: F401 - documents the tool contract
from agent_platform_sdk.interfaces.llm_provider import LLMProvider
from agent_platform_sdk.types.enums import Capability, HealthStatus, MessageRole

pytestmark = pytest.mark.unit

CONTEXT = ExecutionContext()


class _Function:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class _ToolCall:
    def __init__(self, call_id: str, name: str, arguments: str) -> None:
        self.id = call_id
        self.function = _Function(name, arguments)


class _Message:
    def __init__(self, content: str, tool_calls: list[_ToolCall] | None = None) -> None:
        self.content = content
        self.tool_calls = tool_calls or []


class _Choice:
    def __init__(
        self,
        content: str,
        finish_reason: str = "stop",
        # Mirrors an SDK shape the provider must tolerate.
        **kwargs: Any,  # noqa: ANN401
    ) -> None:
        self.message = _Message(content, kwargs.get("tool_calls"))
        self.finish_reason = finish_reason
        self.delta = kwargs.get("delta")


class _Usage:
    def __init__(self, prompt: int, completion: int) -> None:
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.total_tokens = prompt + completion


class _Completion:
    def __init__(
        self,
        content: str = "Hello.",
        finish_reason: str = "stop",
        usage: _Usage | None = None,
        tool_calls: list[_ToolCall] | None = None,
    ) -> None:
        self.id = "upstream-123"
        self.model = "served-model"
        self.choices = [_Choice(content, finish_reason, tool_calls=tool_calls)]
        self.usage = usage or _Usage(10, 5)


class _Delta:
    def __init__(self, content: str | None) -> None:
        self.content = content


class _StreamChoice:
    def __init__(self, content: str | None, finish_reason: str | None = None) -> None:
        self.delta = _Delta(content)
        self.finish_reason = finish_reason


class _StreamUpdate:
    def __init__(
        self,
        content: str | None = None,
        finish_reason: str | None = None,
        usage: _Usage | None = None,
    ) -> None:
        self.choices = [_StreamChoice(content, finish_reason)]
        self.usage = usage


class _Stream:
    """An async iterator that records whether it was closed."""

    def __init__(self, updates: list[_StreamUpdate]) -> None:
        self._updates = updates
        self.closed = False

    def __aiter__(self) -> _Stream:
        return self

    async def __anext__(self) -> _StreamUpdate:
        if not self._updates:
            raise StopAsyncIteration
        return self._updates.pop(0)

    async def close(self) -> None:
        self.closed = True


class FakeClient:
    """Stands in for `ChatCompletionsClient`, recording what it was sent."""

    def __init__(
        self,
        completion: _Completion | None = None,
        stream: _Stream | None = None,
        failure: Exception | None = None,
    ) -> None:
        self._completion = completion or _Completion()
        self._stream = stream
        self._failure = failure
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    async def complete(self, **kwargs: Any) -> Any:  # noqa: ANN401 — SDK signature
        self.calls.append(kwargs)
        if self._failure is not None:
            raise self._failure
        if kwargs.get("stream"):
            return self._stream or _Stream([_StreamUpdate("hi", "stop", _Usage(1, 1))])
        return self._completion

    async def close(self) -> None:
        self.closed = True


class FakeCredential:
    """Stands in for `DefaultAzureCredential`.

    Implements the whole `AsyncTokenCredential` protocol, including `get_token`,
    which the provider never calls — the SDK client does. Satisfying it in full
    keeps the double honest: a fake narrower than the protocol would let the
    provider's declared dependency drift from what it actually needs.
    """

    def __init__(self) -> None:
        self.closed = False

    async def get_token(
        self,
        *scopes: str,
        claims: str | None = None,
        tenant_id: str | None = None,
        enable_cae: bool = False,
        **kwargs: Any,  # noqa: ANN401 — the protocol's own signature
    ) -> AccessToken:
        return AccessToken("fake-token", int(time.time()) + 3600)

    async def close(self) -> None:
        self.closed = True

    async def __aenter__(self) -> FakeCredential:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        await self.close()


def build_provider(
    client: FakeClient | None = None,
    # Overrides span heterogeneous constructor fields.
    **overrides: Any,  # noqa: ANN401
) -> AzureFoundryProvider:
    """Assemble a provider over a fake client."""
    fields: dict[str, Any] = {
        "endpoint": "https://example.services.ai.azure.com/models",
        "deployment": "gemma-4-deployment",
        "model_id": "gemma-4",
        "credential": FakeCredential(),
        "client": client or FakeClient(),
    }
    fields.update(overrides)
    return AzureFoundryProvider(**fields)


def a_request(**overrides: Any) -> CompletionRequest:  # noqa: ANN401 — mixed field types
    fields: dict[str, Any] = {
        "model_id": "gemma-4",
        "messages": (Message(role=MessageRole.USER, content="hello"),),
    }
    fields.update(overrides)
    return CompletionRequest(**fields)


class TestContractConformance:
    def test_it_satisfies_the_provider_contract(self) -> None:
        assert isinstance(build_provider(), LLMProvider)

    def test_streaming_and_cost_reporting_are_declared(self) -> None:
        provider = build_provider()

        assert provider.supports(Capability.STREAMING) is True
        assert provider.supports(Capability.COST_REPORTING) is True

    def test_tool_calling_follows_the_deployed_model(self) -> None:
        """It varies by model, not by provider."""
        assert build_provider(supports_tools=True).supports(Capability.TOOL_CALLING) is True
        assert build_provider(supports_tools=False).supports(Capability.TOOL_CALLING) is False

    def test_vision_is_not_claimed(self) -> None:
        assert build_provider().supports(Capability.VISION) is False


class TestConfiguration:
    async def test_a_malformed_endpoint_is_refused_at_startup(self) -> None:
        """A platform that starts with a bad endpoint fails on a user's request instead."""
        provider = build_provider(endpoint="not-a-url")

        with pytest.raises(ConfigurationError, match="https"):
            await provider.initialize()

    async def test_an_empty_endpoint_is_refused(self) -> None:
        with pytest.raises(ConfigurationError):
            await build_provider(endpoint="").initialize()

    async def test_initialisation_does_not_call_the_service(self) -> None:
        """Probing at startup would wake a scale-to-zero deployment on every restart."""
        client = FakeClient()
        provider = build_provider(client)

        await provider.initialize()

        assert client.calls == []


class TestGeneration:
    async def test_it_returns_the_answer(self) -> None:
        provider = build_provider(FakeClient(_Completion(content="The answer.")))
        await provider.initialize()

        response = await provider.generate(a_request(), CONTEXT)

        assert response.message.content == "The answer."
        assert response.message.role is MessageRole.ASSISTANT

    async def test_the_deployment_is_sent_as_the_model(self) -> None:
        """The deployment name is what selects the model — the model id is ours."""
        client = FakeClient()
        provider = build_provider(client)
        await provider.initialize()

        await provider.generate(a_request(), CONTEXT)

        assert client.calls[0]["model"] == "gemma-4-deployment"

    async def test_the_system_prompt_becomes_a_system_message(self) -> None:
        """Each provider places it where its own API expects."""
        client = FakeClient()
        provider = build_provider(client)
        await provider.initialize()

        await provider.generate(a_request(system_prompt="Be brief."), CONTEXT)

        first = client.calls[0]["messages"][0]
        assert type(first).__name__ == "SystemMessage"

    async def test_conversation_roles_are_translated(self) -> None:
        client = FakeClient()
        provider = build_provider(client)
        await provider.initialize()

        await provider.generate(
            a_request(
                messages=(
                    Message(role=MessageRole.USER, content="q"),
                    Message(role=MessageRole.ASSISTANT, content="a"),
                    Message(role=MessageRole.TOOL, content="{}", tool_call_id="call-1"),
                )
            ),
            CONTEXT,
        )

        names = [type(message).__name__ for message in client.calls[0]["messages"]]
        assert names == ["UserMessage", "AssistantMessage", "ToolMessage"]

    async def test_usage_is_reported(self) -> None:
        provider = build_provider(FakeClient(_Completion(usage=_Usage(100, 50))))
        await provider.initialize()

        response = await provider.generate(a_request(), CONTEXT)

        assert response.usage.prompt_tokens == 100
        assert response.usage.completion_tokens == 50

    async def test_the_upstream_request_id_is_kept(self) -> None:
        """It is what an Azure support case needs."""
        provider = build_provider()
        await provider.initialize()

        response = await provider.generate(a_request(), CONTEXT)

        assert response.provider_metadata["upstream_id"] == "upstream-123"

    async def test_the_served_model_is_recorded_separately(self) -> None:
        """A provider can upgrade a deployment underneath a stable model id."""
        provider = build_provider()
        await provider.initialize()

        response = await provider.generate(a_request(), CONTEXT)

        assert response.model_metadata["served_model"] == "served-model"
        assert response.model_metadata["deployment"] == "gemma-4-deployment"

    async def test_tool_calls_are_translated(self) -> None:
        client = FakeClient(
            _Completion(
                content="",
                finish_reason="tool_calls",
                tool_calls=[_ToolCall("call-1", "internet-search", '{"query":"x"}')],
            )
        )
        provider = build_provider(client)
        await provider.initialize()

        response = await provider.generate(a_request(), CONTEXT)

        assert len(response.message.tool_calls) == 1
        call = response.message.tool_calls[0]
        assert call.tool_id == "internet-search"
        assert call.call_id == "call-1"
        # Arguments stay a raw string: models emit malformed JSON often enough
        # that parsing must be a validation step the runtime controls.
        assert call.arguments == '{"query":"x"}'

    async def test_tools_are_declared_only_when_the_model_supports_them(self) -> None:
        client = FakeClient()
        provider = build_provider(client, supports_tools=False)
        await provider.initialize()

        await provider.generate(a_request(tool_ids=("internet-search",)), CONTEXT)

        assert client.calls[0]["tools"] is None

    async def test_no_choices_is_a_provider_error(self) -> None:
        completion = _Completion()
        completion.choices = []
        provider = build_provider(FakeClient(completion))
        await provider.initialize()

        with pytest.raises(ProviderError):
            await provider.generate(a_request(), CONTEXT)

    async def test_calling_before_initialisation_is_refused(self) -> None:
        provider = AzureFoundryProvider(
            endpoint="https://example.services.ai.azure.com/models",
            deployment="d",
            model_id="m",
            credential=FakeCredential(),
        )

        with pytest.raises(ProviderError, match="not initialised"):
            await provider.generate(a_request(), CONTEXT)


class TestErrorMapping:
    """Setup failures are the ones that actually happen, so they get real guidance."""

    async def test_authentication_failure_explains_both_environments(self) -> None:
        provider = build_provider(FakeClient(failure=ClientAuthenticationError("401")))
        await provider.initialize()

        with pytest.raises(ProviderError) as raised:
            await provider.generate(a_request(), CONTEXT)

        assert "az login" in raised.value.message
        assert "Managed Identity" in raised.value.message

    async def test_a_missing_deployment_names_the_usual_mistake(self) -> None:
        """The deployment name is frequently not the model name."""
        error = HttpResponseError("not found")
        error.status_code = 404
        provider = build_provider(FakeClient(failure=error))
        await provider.initialize()

        with pytest.raises(ProviderError) as raised:
            await provider.generate(a_request(), CONTEXT)

        assert "deployment name, not the model name" in raised.value.message

    async def test_rate_limiting_is_reported_as_such(self) -> None:
        error = HttpResponseError("too many")
        error.status_code = 429
        provider = build_provider(FakeClient(failure=error))
        await provider.initialize()

        with pytest.raises(ProviderError, match="rate limit"):
            await provider.generate(a_request(), CONTEXT)

    async def test_a_transport_failure_mentions_cold_starts(self) -> None:
        """A scale-to-zero deployment's first request legitimately takes tens of seconds."""
        provider = build_provider(FakeClient(failure=ServiceRequestError("unreachable")))
        await provider.initialize()

        with pytest.raises(ProviderError, match="scale-to-zero"):
            await provider.generate(a_request(), CONTEXT)

    async def test_the_original_message_never_escapes(self) -> None:
        """SDK exception text can carry the endpoint, headers and token fragments."""
        provider = build_provider(FakeClient(failure=RuntimeError("token=SECRET123")))
        await provider.initialize()

        with pytest.raises(ProviderError) as raised:
            await provider.generate(a_request(), CONTEXT)

        assert "SECRET123" not in raised.value.message


class TestStreaming:
    async def test_deltas_are_yielded(self) -> None:
        stream = _Stream(
            [_StreamUpdate("Hello"), _StreamUpdate(" world"), _StreamUpdate(None, "stop")]
        )
        provider = build_provider(FakeClient(stream=stream))
        await provider.initialize()

        chunks = [chunk async for chunk in provider.stream(a_request(), CONTEXT)]

        assert "".join(chunk.delta for chunk in chunks) == "Hello world"

    async def test_a_terminal_chunk_carries_usage_and_finish_reason(self) -> None:
        stream = _Stream([_StreamUpdate("hi"), _StreamUpdate(None, "stop", _Usage(7, 3))])
        provider = build_provider(FakeClient(stream=stream))
        await provider.initialize()

        chunks = [chunk async for chunk in provider.stream(a_request(), CONTEXT)]

        assert chunks[-1].delta == ""
        assert chunks[-1].finish_reason == "stop"
        assert chunks[-1].usage is not None
        assert chunks[-1].usage.completion_tokens == 3

    async def test_the_stream_is_closed_when_exhausted(self) -> None:
        """The SDK stream holds an open HTTP connection."""
        stream = _Stream([_StreamUpdate("hi", "stop")])
        provider = build_provider(FakeClient(stream=stream))
        await provider.initialize()

        _ = [chunk async for chunk in provider.stream(a_request(), CONTEXT)]

        assert stream.closed is True

    async def test_the_stream_is_closed_when_abandoned(self) -> None:
        """Stopping generation must release the connection, not just stop reading."""
        stream = _Stream([_StreamUpdate(f"chunk {index}") for index in range(10)])
        provider = build_provider(FakeClient(stream=stream))
        await provider.initialize()

        iterator = provider.stream(a_request(), CONTEXT)
        await anext(iterator)
        await iterator.aclose()

        assert stream.closed is True

    async def test_a_streaming_failure_becomes_a_provider_error(self) -> None:
        provider = build_provider(FakeClient(failure=ServiceRequestError("gone")))
        await provider.initialize()

        with pytest.raises(ProviderError):
            _ = [chunk async for chunk in provider.stream(a_request(), CONTEXT)]


class TestAccounting:
    def test_cost_is_computed_from_configured_rates(self) -> None:
        from agent_platform_sdk.dto.completion import TokenUsage

        provider = build_provider(
            input_cost_per_million_tokens=Decimal("2.00"),
            output_cost_per_million_tokens=Decimal("10.00"),
        )

        cost = provider.estimate_cost(
            "gemma-4", TokenUsage(prompt_tokens=1_000_000, completion_tokens=100_000)
        )

        assert cost == Decimal("3.00")

    def test_an_unpriced_deployment_reports_zero_not_a_guess(self) -> None:
        """A fabricated rate would reach cost dashboards looking real."""
        from agent_platform_sdk.dto.completion import TokenUsage

        provider = build_provider()

        assert provider.estimate_cost("gemma-4", TokenUsage(prompt_tokens=1_000_000)) == Decimal(0)

    async def test_token_counting_is_an_estimate(self) -> None:
        provider = build_provider()

        short = await provider.count_tokens(a_request())
        long = await provider.count_tokens(
            a_request(messages=(Message(role=MessageRole.USER, content="word " * 400),))
        )

        assert long.prompt_tokens > short.prompt_tokens


class TestLifecycleAndHealth:
    async def test_health_reports_configuration_without_calling_the_model(self) -> None:
        client = FakeClient()
        provider = build_provider(client)
        await provider.initialize()

        health = await provider.health_check()

        assert health.status is HealthStatus.HEALTHY
        assert client.calls == []

    async def test_health_is_unknown_before_initialisation(self) -> None:
        provider = AzureFoundryProvider(
            endpoint="https://example.services.ai.azure.com/models",
            deployment="d",
            model_id="m",
            credential=FakeCredential(),
        )

        assert (await provider.health_check()).status is HealthStatus.UNKNOWN

    async def test_the_model_descriptor_reflects_configuration(self) -> None:
        provider = build_provider(max_context_tokens=8192, max_output_tokens=2048)
        await provider.initialize()

        models = await provider.list_models()

        assert len(models) == 1
        assert models[0].model_id == "gemma-4"
        assert models[0].deployment_name == "gemma-4-deployment"
        assert models[0].max_context_tokens == 8192

    async def test_closing_releases_an_injected_client_to_its_owner(self) -> None:
        """A client the provider did not open is not the provider's to close."""
        client = FakeClient()
        provider = build_provider(client)
        await provider.initialize()

        await provider.close()

        assert client.closed is False


class TestOutputTokenParameter:
    """Reasoning models reject `max_tokens` outright rather than ignoring it.

    Found by a live call that returned HTTP 400 where every mock in this file
    had accepted `max_tokens` without complaint. The mock was not wrong — it was
    simply not the service.
    """

    async def test_the_default_sends_max_tokens(self) -> None:
        client = FakeClient()
        provider = build_provider(client)
        await provider.initialize()

        await provider.generate(a_request(max_output_tokens=64), CONTEXT)

        assert client.calls[0]["max_tokens"] == 64

    async def test_a_reasoning_model_gets_max_completion_tokens(self) -> None:
        client = FakeClient()
        provider = build_provider(
            client,
            output_token_parameter="max_completion_tokens",  # noqa: S106 — a parameter name
        )
        await provider.initialize()

        await provider.generate(a_request(max_output_tokens=64), CONTEXT)

        assert "max_tokens" not in client.calls[0]
        assert client.calls[0]["model_extras"] == {"max_completion_tokens": 64}

    async def test_nothing_is_sent_when_no_cap_was_requested(self) -> None:
        """An explicit None is not the same as absent to the service."""
        client = FakeClient()
        provider = build_provider(client)
        await provider.initialize()

        await provider.generate(a_request(), CONTEXT)

        assert "max_tokens" not in client.calls[0]
        assert "model_extras" not in client.calls[0]

    async def test_streaming_uses_the_same_parameter(self) -> None:
        client = FakeClient(stream=_Stream([_StreamUpdate("hi", "stop")]))
        provider = build_provider(
            client,
            output_token_parameter="max_completion_tokens",  # noqa: S106 — a parameter name
        )
        await provider.initialize()

        _ = [chunk async for chunk in provider.stream(a_request(max_output_tokens=32), CONTEXT)]

        assert client.calls[0]["model_extras"] == {"max_completion_tokens": 32}


class TestFinishReasonNeutrality:
    """The real SDK enum, not a friendly string.

    These use `CompletionsFinishReason` deliberately. The original tests passed
    a plain `"stop"`, which is what the mock returns and what every fake here
    had been handed — so the adapter looked correct while `str(enum)` was
    putting `CompletionsFinishReason.STOPPED` into the public API response.

    A double that is more convenient than the real type does not test the
    adapter; it tests the double.
    """

    @pytest.mark.parametrize(
        ("sdk_reason", "expected"),
        [
            (CompletionsFinishReason.STOPPED, "stop"),
            (CompletionsFinishReason.TOKEN_LIMIT_REACHED, "length"),
            (CompletionsFinishReason.CONTENT_FILTERED, "content_filter"),
            (CompletionsFinishReason.TOOL_CALLS, "tool_calls"),
        ],
    )
    async def test_sdk_enums_become_platform_vocabulary(
        self, sdk_reason: CompletionsFinishReason, expected: str
    ) -> None:
        client = FakeClient(_Completion(finish_reason=sdk_reason))
        provider = build_provider(client)
        await provider.initialize()

        response = await provider.generate(a_request(), CONTEXT)

        assert response.finish_reason == expected

    async def test_no_azure_type_name_reaches_the_response(self) -> None:
        client = FakeClient(_Completion(finish_reason=CompletionsFinishReason.STOPPED))
        provider = build_provider(client)
        await provider.initialize()

        response = await provider.generate(a_request(), CONTEXT)

        assert response.finish_reason is not None
        assert "CompletionsFinishReason" not in response.finish_reason
        assert "." not in response.finish_reason

    async def test_streaming_reports_the_same_vocabulary(self) -> None:
        stream = _Stream(
            [_StreamUpdate("hi"), _StreamUpdate(None, CompletionsFinishReason.TOKEN_LIMIT_REACHED)]
        )
        provider = build_provider(FakeClient(stream=stream))
        await provider.initialize()

        chunks = [chunk async for chunk in provider.stream(a_request(), CONTEXT)]

        assert chunks[-1].finish_reason == "length"

    async def test_an_unrecognised_reason_is_reported_not_swallowed(self) -> None:
        """A reason we have not seen is information, not a reason to claim success."""
        client = FakeClient(_Completion(finish_reason="some_new_reason"))
        provider = build_provider(client)
        await provider.initialize()

        response = await provider.generate(a_request(), CONTEXT)

        assert response.finish_reason == "some_new_reason"

    async def test_a_missing_reason_stays_absent(self) -> None:
        client = FakeClient(_Completion(finish_reason=""))
        provider = build_provider(client)
        await provider.initialize()

        response = await provider.generate(a_request(), CONTEXT)

        assert response.finish_reason is None
