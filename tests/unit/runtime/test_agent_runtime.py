"""Agent Runtime behaviour.

The runtime owns the request lifecycle, so these tests cover the stages that go
wrong silently: does the agent see the conversation, is the right prompt version
resolved, does a turn survive a failure, and does memory end up matching what
the user saw.

Everything but the gateway is real. A test that faked the agent, the engine and
memory would assert that the runtime calls its collaborators, which is a
restatement of the implementation rather than a check on it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from agent_platform.exceptions.base import (
    NotFoundError,
    PolicyViolationError,
    ProviderError,
)
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.dto.prompt import PromptVariable
from agent_platform_sdk.interfaces.workflow_engine import WorkflowEngine
from agent_platform_sdk.policies.budget import BudgetPolicy
from agent_platform_sdk.types.enums import MessageRole

pytestmark = pytest.mark.unit

CONTEXT = ExecutionContext()
CONVERSATION = "conversation-1"


class TestAgentResolution:
    """An unknown agent and a disabled one are different problems."""

    async def test_an_unregistered_agent_is_not_found(
        self, build_stack: Callable[..., Any]
    ) -> None:
        stack = build_stack(register_agent=False)

        with pytest.raises(NotFoundError, match="No agent registered"):
            await stack.runtime.prepare("chat-agent", "hello", CONTEXT)

    async def test_the_error_lists_what_is_registered(
        self, build_stack: Callable[..., Any]
    ) -> None:
        """The usual cause is a typo, and the answer is then on screen."""
        stack = build_stack()

        with pytest.raises(NotFoundError, match="chat-agent"):
            await stack.runtime.prepare("chat-agnet", "hello", CONTEXT)

    async def test_a_disabled_agent_is_a_policy_violation_not_a_miss(
        self, build_stack: Callable[..., Any]
    ) -> None:
        """Reporting it as missing would send someone hunting a registration bug."""
        stack = build_stack(is_enabled=False)

        with pytest.raises(PolicyViolationError, match="disabled"):
            await stack.runtime.prepare("chat-agent", "hello", CONTEXT)

    async def test_registered_agents_are_discoverable(
        self, build_stack: Callable[..., Any]
    ) -> None:
        stack = build_stack()

        assert stack.runtime.list_agents() == ("chat-agent",)


class TestContextAssembly:
    """The agent must see the conversation, and only the conversation."""

    async def test_the_first_turn_sends_only_the_new_message(
        self, build_stack: Callable[..., Any]
    ) -> None:
        stack = build_stack()

        turn = await stack.runtime.prepare("chat-agent", "first", CONTEXT, CONVERSATION)
        await stack.runtime.execute(turn)

        assert [message.content for message in stack.gateway.requests[0].messages] == ["first"]

    async def test_a_later_turn_sends_the_whole_history(
        self, build_stack: Callable[..., Any]
    ) -> None:
        stack = build_stack()

        first = await stack.runtime.prepare("chat-agent", "first", CONTEXT, CONVERSATION)
        await stack.runtime.execute(first)
        second = await stack.runtime.prepare("chat-agent", "second", CONTEXT, CONVERSATION)
        await stack.runtime.execute(second)

        assert [message.content for message in stack.gateway.requests[1].messages] == [
            "first",
            "The answer.",
            "second",
        ]

    async def test_a_turn_without_a_conversation_has_no_history(
        self, build_stack: Callable[..., Any]
    ) -> None:
        """A one-shot execution — a scheduled agent, an internal call — is stateless."""
        stack = build_stack()

        turn = await stack.runtime.prepare("chat-agent", "hello", CONTEXT)

        assert turn.request.history == ()

    async def test_the_resolved_prompt_reaches_the_agent(
        self, build_stack: Callable[..., Any]
    ) -> None:
        stack = build_stack()

        turn = await stack.runtime.prepare("chat-agent", "hello", CONTEXT, CONVERSATION)
        await stack.runtime.execute(turn)

        assert stack.gateway.requests[0].system_prompt == "You are a test assistant."

    async def test_a_pinned_prompt_version_is_requested(
        self, build_stack: Callable[..., Any]
    ) -> None:
        """Pinning is what makes behaviour reproducible across a prompt change."""
        stack = build_stack(prompt_version="1.0")

        await stack.runtime.prepare("chat-agent", "hello", CONTEXT)

        assert stack.prompts.requested == [("chat-agent-system", "1.0")]

    async def test_prompt_variables_are_rendered(self, build_stack: Callable[..., Any]) -> None:
        stack = build_stack(
            prompt_template="Answer in {{ locale }}.",
            prompt_variables=(PromptVariable(name="locale", required=True),),
        )

        turn = await stack.runtime.prepare("chat-agent", "hello", CONTEXT, CONVERSATION)
        await stack.runtime.execute(turn)

        assert stack.gateway.requests[0].system_prompt == "Answer in en-US."


class TestExecutionContextPropagation:
    """Telemetry is joinable only if every layer carries the same identifiers."""

    async def test_the_agent_and_model_are_stamped_on_the_context(
        self, build_stack: Callable[..., Any]
    ) -> None:
        stack = build_stack()

        turn = await stack.runtime.prepare("chat-agent", "hello", CONTEXT)

        assert turn.context.agent_id == "chat-agent"
        assert turn.context.model_id == "test-model"
        assert turn.context.provider_id == "fake"

    async def test_an_execution_id_is_issued(self, build_stack: Callable[..., Any]) -> None:
        stack = build_stack()

        turn = await stack.runtime.prepare("chat-agent", "hello", CONTEXT)

        assert turn.context.execution_id

    async def test_the_correlation_id_survives(self, build_stack: Callable[..., Any]) -> None:
        """The whole execution tree has to stay joinable."""
        stack = build_stack()
        context = ExecutionContext(correlation_id="corr-123")

        turn = await stack.runtime.prepare("chat-agent", "hello", context)

        assert turn.context.correlation_id == "corr-123"

    async def test_an_existing_execution_id_is_not_replaced(
        self, build_stack: Callable[..., Any]
    ) -> None:
        """A nested execution keeps the id its caller established."""
        stack = build_stack()
        context = ExecutionContext(execution_id="exec-outer")

        turn = await stack.runtime.prepare("chat-agent", "hello", context)

        assert turn.context.execution_id == "exec-outer"

    async def test_the_caller_context_is_not_mutated(self, build_stack: Callable[..., Any]) -> None:
        stack = build_stack()
        context = ExecutionContext()

        await stack.runtime.prepare("chat-agent", "hello", context)

        assert context.agent_id is None


class TestMemoryCoordination:
    """The runtime owns memory, so an agent cannot forget to write it."""

    async def test_a_completed_turn_stores_both_messages(
        self, build_stack: Callable[..., Any]
    ) -> None:
        stack = build_stack()

        turn = await stack.runtime.prepare("chat-agent", "question", CONTEXT, CONVERSATION)
        await stack.runtime.execute(turn)

        stored = await stack.memory.load(CONVERSATION, CONTEXT)
        assert [(message.role, message.content) for message in stored] == [
            (MessageRole.USER, "question"),
            (MessageRole.ASSISTANT, "The answer."),
        ]

    async def test_a_failed_turn_still_records_the_question(
        self, build_stack: Callable[..., Any]
    ) -> None:
        """A retry needs the history, and the user should see what they asked."""
        stack = build_stack(failure=ProviderError("upstream down"))

        turn = await stack.runtime.prepare("chat-agent", "question", CONTEXT, CONVERSATION)
        with pytest.raises(ProviderError):
            await stack.runtime.execute(turn)

        stored = await stack.memory.load(CONVERSATION, CONTEXT)
        assert [message.content for message in stored] == ["question"]

    async def test_nothing_is_stored_without_a_conversation(
        self, build_stack: Callable[..., Any]
    ) -> None:
        stack = build_stack()

        turn = await stack.runtime.prepare("chat-agent", "hello", CONTEXT)
        await stack.runtime.execute(turn)

        assert await stack.memory.load("", CONTEXT) == ()


class TestStreaming:
    async def test_chunks_reach_the_caller(self, build_stack: Callable[..., Any]) -> None:
        stack = build_stack(chunks=("Hello", " ", "world"))

        turn = await stack.runtime.prepare("chat-agent", "hi", CONTEXT, CONVERSATION)
        deltas = [chunk.delta async for chunk in stack.runtime.stream(turn)]

        assert "".join(deltas) == "Hello world"

    async def test_a_streamed_turn_is_recorded(self, build_stack: Callable[..., Any]) -> None:
        stack = build_stack(chunks=("one", " two"))

        turn = await stack.runtime.prepare("chat-agent", "hi", CONTEXT, CONVERSATION)
        _ = [chunk async for chunk in stack.runtime.stream(turn)]

        stored = await stack.memory.load(CONVERSATION, CONTEXT)
        assert [message.content for message in stored] == ["hi", "one two"]

    async def test_a_partial_answer_is_stored_when_the_caller_stops(
        self, build_stack: Callable[..., Any]
    ) -> None:
        """Stopping is a consumer closing the iterator. What was read is kept."""
        stack = build_stack(chunks=("one", " two", " three", " four"))

        turn = await stack.runtime.prepare("chat-agent", "hi", CONTEXT, CONVERSATION)
        stream = stack.runtime.stream(turn)
        collected = 0
        async for chunk in stream:
            if chunk.delta:
                collected += 1
                if collected == 2:
                    break
        await stream.aclose()

        stored = await stack.memory.load(CONVERSATION, CONTEXT)
        assert [message.content for message in stored] == ["hi", "one two"]

    async def test_a_mid_stream_failure_propagates(self, build_stack: Callable[..., Any]) -> None:
        """The runtime does not know it is behind HTTP; the caller decides how to report."""
        stack = build_stack(
            chunks=("partial", " never sent"), failure=ProviderError("died"), fail_after_chunks=1
        )

        turn = await stack.runtime.prepare("chat-agent", "hi", CONTEXT, CONVERSATION)

        with pytest.raises(ProviderError):
            _ = [chunk async for chunk in stack.runtime.stream(turn)]

    async def test_text_generated_before_a_failure_is_kept(
        self, build_stack: Callable[..., Any]
    ) -> None:
        stack = build_stack(
            chunks=("partial", " never sent"), failure=ProviderError("died"), fail_after_chunks=1
        )

        turn = await stack.runtime.prepare("chat-agent", "hi", CONTEXT, CONVERSATION)
        with pytest.raises(ProviderError):
            _ = [chunk async for chunk in stack.runtime.stream(turn)]

        stored = await stack.memory.load(CONVERSATION, CONTEXT)
        assert [message.content for message in stored] == ["hi", "partial"]


class TestEngineIndependence:
    """The runtime must not be able to tell which engine it is using."""

    async def test_langgraph_and_direct_produce_the_same_result(
        self, build_stack: Callable[..., Any], langgraph_engine: WorkflowEngine
    ) -> None:
        direct = build_stack()
        graph = build_stack(engine=langgraph_engine)

        direct_turn = await direct.runtime.prepare("chat-agent", "hello", CONTEXT, CONVERSATION)
        graph_turn = await graph.runtime.prepare("chat-agent", "hello", CONTEXT, CONVERSATION)

        direct_result = await direct.runtime.execute(direct_turn)
        graph_result = await graph.runtime.execute(graph_turn)

        assert direct_result.message == graph_result.message
        assert direct_result.usage == graph_result.usage

    async def test_a_provider_failure_survives_the_graph_unchanged(
        self, build_stack: Callable[..., Any], langgraph_engine: WorkflowEngine
    ) -> None:
        """A provider outage must not become an opaque orchestration failure."""
        stack = build_stack(failure=ProviderError("upstream down"), engine=langgraph_engine)

        turn = await stack.runtime.prepare("chat-agent", "hello", CONTEXT, CONVERSATION)

        with pytest.raises(ProviderError, match="upstream down"):
            await stack.runtime.execute(turn)


class TestBudgetPolicy:
    """A breach is reported, not enforced by discarding paid-for work."""

    async def test_a_breached_token_budget_does_not_discard_the_answer(
        self, build_stack: Callable[..., Any]
    ) -> None:
        stack = build_stack(budget=BudgetPolicy(max_total_tokens=1))

        turn = await stack.runtime.prepare("chat-agent", "hello", CONTEXT, CONVERSATION)
        result = await stack.runtime.execute(turn)

        # The work is done and paid for. Discarding it would waste the spend and
        # deny the user the result; the breach is logged instead.
        assert result.message.content == "The answer."
