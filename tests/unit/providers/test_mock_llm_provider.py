"""Mock provider behaviour.

The mock is what every other Milestone 02 test runs against, so its own
guarantees have to hold first: it satisfies the provider contract, its streamed
deltas reassemble into exactly its non-streamed answer, and it is deterministic.

The reassembly test is the important one. If deltas do not concatenate to the
whole answer, every consumer that appends them — the service, the SSE layer, the
browser — renders something subtly wrong, and the bug looks like a UI problem.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from agent_platform.providers.mock.mock_llm_provider import MockLLMProvider
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.dto.completion import CompletionRequest
from agent_platform_sdk.dto.message import Message
from agent_platform_sdk.interfaces.llm_provider import LLMProvider
from agent_platform_sdk.types.enums import Capability, HealthStatus, MessageRole

pytestmark = pytest.mark.unit

CONTEXT = ExecutionContext()


def a_request(prompt: str = "What is this platform?") -> CompletionRequest:
    """Build a completion request carrying one user message."""
    return CompletionRequest(
        model_id="mock-echo",
        messages=(Message(role=MessageRole.USER, content=prompt),),
    )


@pytest.fixture
def provider() -> MockLLMProvider:
    # No delay: these tests assert on content, and sleeping between chunks would
    # add seconds to the suite for nothing.
    return MockLLMProvider(chunk_delay_seconds=0.0)


class TestContractConformance:
    def test_it_satisfies_the_provider_contract(self, provider: MockLLMProvider) -> None:
        assert isinstance(provider, LLMProvider)

    def test_it_declares_only_what_it_implements(self, provider: MockLLMProvider) -> None:
        """Claiming tool calling would make the runtime route work it cannot do."""
        assert provider.supports(Capability.STREAMING) is True
        assert provider.supports(Capability.TOOL_CALLING) is False
        assert provider.supports(Capability.VISION) is False

    async def test_it_is_always_healthy(self, provider: MockLLMProvider) -> None:
        health = await provider.health_check()

        assert health.status is HealthStatus.HEALTHY

    async def test_it_serves_exactly_one_model(self, provider: MockLLMProvider) -> None:
        models = await provider.list_models()

        assert len(models) == 1
        assert models[0].model_id == "mock-echo"
        assert models[0].supports(Capability.STREAMING)


class TestGeneration:
    async def test_it_answers(self, provider: MockLLMProvider) -> None:
        response = await provider.generate(a_request(), CONTEXT)

        assert response.message.role is MessageRole.ASSISTANT
        assert response.message.content

    async def test_it_is_deterministic(self, provider: MockLLMProvider) -> None:
        """A random mock would make every UI and streaming test flaky."""
        first = await provider.generate(a_request("same question"), CONTEXT)
        second = await provider.generate(a_request("same question"), CONTEXT)

        assert first.message.content == second.message.content

    async def test_the_answer_quotes_the_question(self, provider: MockLLMProvider) -> None:
        response = await provider.generate(a_request("Why is the sky blue?"), CONTEXT)

        assert "Why is the sky blue?" in response.message.content

    async def test_the_answer_exercises_the_markdown_renderer(
        self, provider: MockLLMProvider
    ) -> None:
        """Heading, list and fenced code block — the three things the UI must render."""
        content = (await provider.generate(a_request(), CONTEXT)).message.content

        assert "## " in content
        assert "- " in content
        assert "```python" in content

    async def test_a_greeting_gets_a_short_reply(self, provider: MockLLMProvider) -> None:
        response = await provider.generate(a_request("hello"), CONTEXT)

        assert "```" not in response.message.content

    async def test_an_empty_conversation_is_explained_not_crashed(
        self, provider: MockLLMProvider
    ) -> None:
        request = CompletionRequest(model_id="mock-echo", messages=())

        response = await provider.generate(request, CONTEXT)

        assert "mock provider" in response.message.content

    async def test_it_reports_the_resolved_identifiers(self, provider: MockLLMProvider) -> None:
        response = await provider.generate(a_request(), CONTEXT)

        assert response.provider_id == "mock"
        assert response.model_id == "mock-echo"
        assert response.finish_reason == "stop"


class TestStreaming:
    async def test_deltas_reassemble_into_the_complete_answer(
        self, provider: MockLLMProvider
    ) -> None:
        """Consumers append deltas. If this fails, everything downstream is wrong."""
        request = a_request()
        expected = (await provider.generate(request, CONTEXT)).message.content

        streamed = "".join([chunk.delta async for chunk in provider.stream(request, CONTEXT)])

        assert streamed == expected

    async def test_it_emits_more_than_one_chunk(self, provider: MockLLMProvider) -> None:
        """A single-chunk stream would leave the incremental path untested."""
        chunks = [chunk async for chunk in provider.stream(a_request(), CONTEXT)]

        assert len(chunks) > 10

    async def test_usage_and_finish_reason_arrive_on_a_terminal_chunk(
        self, provider: MockLLMProvider
    ) -> None:
        chunks = [chunk async for chunk in provider.stream(a_request(), CONTEXT)]
        final = chunks[-1]

        assert final.delta == ""
        assert final.finish_reason == "stop"
        assert final.usage is not None
        assert final.usage.completion_tokens > 0

    async def test_only_the_terminal_chunk_carries_a_finish_reason(
        self, provider: MockLLMProvider
    ) -> None:
        chunks = [chunk async for chunk in provider.stream(a_request(), CONTEXT)]

        assert all(chunk.finish_reason is None for chunk in chunks[:-1])

    async def test_an_abandoned_stream_can_be_closed(self, provider: MockLLMProvider) -> None:
        """Stopping generation closes the iterator part-way through."""
        stream = provider.stream(a_request(), CONTEXT)

        assert (await anext(stream)).delta
        await stream.aclose()


class TestAccounting:
    async def test_token_counts_are_reported(self, provider: MockLLMProvider) -> None:
        response = await provider.generate(a_request(), CONTEXT)

        assert response.usage.prompt_tokens > 0
        assert response.usage.completion_tokens > 0

    async def test_count_tokens_scales_with_prompt_length(self, provider: MockLLMProvider) -> None:
        short = await provider.count_tokens(a_request("hi"))
        long = await provider.count_tokens(a_request("hi " * 500))

        assert long.prompt_tokens > short.prompt_tokens

    async def test_an_empty_prompt_counts_zero(self, provider: MockLLMProvider) -> None:
        usage = await provider.count_tokens(CompletionRequest(model_id="mock-echo", messages=()))

        assert usage.prompt_tokens == 0

    def test_generating_locally_costs_nothing(self, provider: MockLLMProvider) -> None:
        """A fabricated mock price would poison the cost-tracking pipeline."""
        from agent_platform_sdk.dto.completion import TokenUsage

        assert provider.estimate_cost("mock-echo", TokenUsage(prompt_tokens=1_000_000)) == Decimal(
            0
        )

    async def test_the_reported_cost_is_zero(self, provider: MockLLMProvider) -> None:
        response = await provider.generate(a_request(), CONTEXT)

        assert response.estimated_cost == Decimal(0)


class TestConfiguration:
    async def test_the_identifiers_are_configurable(self) -> None:
        """Nothing hardcodes a provider or model name."""
        provider = MockLLMProvider(
            provider_id="custom", model_id="custom-model", chunk_delay_seconds=0.0
        )

        response = await provider.generate(
            CompletionRequest(
                model_id="custom-model",
                messages=(Message(role=MessageRole.USER, content="hi"),),
            ),
            CONTEXT,
        )

        assert provider.provider_id == "custom"
        assert response.provider_id == "custom"
