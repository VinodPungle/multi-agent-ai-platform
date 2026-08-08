"""Chat service behaviour.

Since Milestone 03 the service holds no memory of its own and calls no gateway:
it validates a message, maps a conversation onto a runtime turn, and translates
runtime output into SSE event types. These tests cover exactly that boundary.

What used to be tested here — context assembly, memory writes, model selection —
moved with the code, to ``tests/unit/runtime/test_agent_runtime.py``. Testing it
in both places would mean two suites asserting one behaviour, and the one that
did not move would slowly stop being true.

The service is driven over a real runtime with a fake gateway, because the
translation only means anything against real runtime output.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from agent_platform.application.chat_service import ChatService
from agent_platform.domain.chat import (
    ChatCompletedEvent,
    ChatDeltaEvent,
    ChatErrorEvent,
    ChatStartedEvent,
)
from agent_platform.exceptions.base import (
    NotFoundError,
    PolicyViolationError,
    ProviderError,
    ValidationError,
)
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.types.enums import MessageRole

pytestmark = pytest.mark.unit

CONTEXT = ExecutionContext()
CONVERSATION = "conversation-1"


@pytest.fixture
def build_service(build_stack: Callable[..., Any]) -> Callable[..., Any]:
    """Return a factory producing a service over a real runtime."""

    def _build(**kwargs: Any) -> tuple[ChatService, Any]:  # noqa: ANN401 - forwards kwargs
        max_prompt_characters = kwargs.pop("max_prompt_characters", 32_000)
        stack = build_stack(**kwargs)
        service = ChatService(
            runtime=stack.runtime,
            memory=stack.memory,
            agent_id="chat-agent",
            max_prompt_characters=max_prompt_characters,
        )
        return service, stack

    return _build


class TestPromptValidation:
    """An invalid message must cost nothing."""

    @pytest.mark.parametrize("prompt", ["", "   ", "\n\t "])
    async def test_a_blank_message_is_rejected(
        self, build_service: Callable[..., Any], prompt: str
    ) -> None:
        service, stack = build_service()

        with pytest.raises(ValidationError, match="cannot be empty"):
            await service.send(CONVERSATION, prompt, CONTEXT)

        assert not stack.gateway.requests

    async def test_an_oversized_message_is_rejected(
        self, build_service: Callable[..., Any]
    ) -> None:
        service, stack = build_service(max_prompt_characters=10)

        with pytest.raises(ValidationError, match="cannot exceed"):
            await service.send(CONVERSATION, "x" * 11, CONTEXT)

        assert not stack.gateway.requests

    async def test_the_message_is_trimmed(self, build_service: Callable[..., Any]) -> None:
        service, stack = build_service()

        await service.send(CONVERSATION, "  hello  ", CONTEXT)

        assert stack.gateway.requests[0].messages[-1].content == "hello"

    async def test_a_blank_message_is_rejected_before_a_stream_opens(
        self, build_service: Callable[..., Any]
    ) -> None:
        """Failing here still allows a proper HTTP status; failing later does not."""
        service, stack = build_service()

        with pytest.raises(ValidationError):
            _ = await service.stream(CONVERSATION, "  ", CONTEXT)

        assert not stack.gateway.requests


class TestRuntimeFailuresBeforeTheStream:
    """A runtime refusal must reach the caller as a status code, not an event."""

    async def test_an_unregistered_agent_fails_before_the_stream(
        self, build_service: Callable[..., Any]
    ) -> None:
        service, _ = build_service(register_agent=False)

        with pytest.raises(NotFoundError):
            _ = await service.stream(CONVERSATION, "hello", CONTEXT)

    async def test_a_disabled_agent_fails_before_the_stream(
        self, build_service: Callable[..., Any]
    ) -> None:
        service, _ = build_service(is_enabled=False)

        with pytest.raises(PolicyViolationError):
            _ = await service.stream(CONVERSATION, "hello", CONTEXT)


class TestCompleteTurns:
    async def test_a_turn_returns_the_answer(self, build_service: Callable[..., Any]) -> None:
        service, _ = build_service()

        turn = await service.send(CONVERSATION, "question", CONTEXT)

        assert turn.message.content == "The answer."
        assert turn.conversation_id == CONVERSATION

    async def test_the_serving_model_and_provider_are_reported(
        self, build_service: Callable[..., Any]
    ) -> None:
        service, _ = build_service()

        turn = await service.send(CONVERSATION, "question", CONTEXT)

        assert turn.model_id == "test-model"
        assert turn.provider_id == "fake"

    async def test_usage_is_reported(self, build_service: Callable[..., Any]) -> None:
        service, _ = build_service()

        turn = await service.send(CONVERSATION, "question", CONTEXT)

        assert turn.usage.prompt_tokens == 10
        assert turn.usage.completion_tokens == 5


class TestConversationState:
    async def test_history_returns_what_the_runtime_stored(
        self, build_service: Callable[..., Any]
    ) -> None:
        service, _ = build_service()
        await service.send(CONVERSATION, "question", CONTEXT)

        history = await service.history(CONVERSATION, CONTEXT)

        assert [message.content for message in history.messages] == ["question", "The answer."]

    async def test_an_unknown_conversation_is_empty(
        self, build_service: Callable[..., Any]
    ) -> None:
        service, _ = build_service()

        assert (await service.history("never-seen", CONTEXT)).is_empty

    async def test_clearing_forgets_the_conversation(
        self, build_service: Callable[..., Any]
    ) -> None:
        service, _ = build_service()
        await service.send(CONVERSATION, "question", CONTEXT)

        await service.clear(CONVERSATION, CONTEXT)

        assert (await service.history(CONVERSATION, CONTEXT)).is_empty


class TestStreaming:
    async def test_the_event_sequence_is_started_deltas_completed(
        self, build_service: Callable[..., Any]
    ) -> None:
        service, _ = build_service(chunks=("Hello", " ", "world"))

        events = [event async for event in await service.stream(CONVERSATION, "hi", CONTEXT)]

        assert isinstance(events[0], ChatStartedEvent)
        assert all(isinstance(event, ChatDeltaEvent) for event in events[1:-1])
        assert isinstance(events[-1], ChatCompletedEvent)

    async def test_deltas_reassemble_into_the_completed_content(
        self, build_service: Callable[..., Any]
    ) -> None:
        service, _ = build_service(chunks=("Hello", " ", "world"))

        events = [event async for event in await service.stream(CONVERSATION, "hi", CONTEXT)]

        deltas = "".join(event.delta for event in events if isinstance(event, ChatDeltaEvent))
        completed = next(event for event in events if isinstance(event, ChatCompletedEvent))
        assert deltas == completed.content == "Hello world"

    async def test_the_message_id_is_stable_across_the_stream(
        self, build_service: Callable[..., Any]
    ) -> None:
        """A client creates the element on `started` and reconciles it on `completed`."""
        service, _ = build_service()

        events = [event async for event in await service.stream(CONVERSATION, "hi", CONTEXT)]

        started = next(event for event in events if isinstance(event, ChatStartedEvent))
        completed = next(event for event in events if isinstance(event, ChatCompletedEvent))
        assert started.message_id == completed.message_id

    async def test_the_started_event_reports_the_resolved_model(
        self, build_service: Callable[..., Any]
    ) -> None:
        service, _ = build_service()

        events = [event async for event in await service.stream(CONVERSATION, "hi", CONTEXT)]

        assert isinstance(events[0], ChatStartedEvent)
        assert events[0].model_id == "test-model"

    async def test_a_streamed_turn_is_recorded(self, build_service: Callable[..., Any]) -> None:
        service, _ = build_service(chunks=("one", " two"))

        _ = [event async for event in await service.stream(CONVERSATION, "hi", CONTEXT)]

        history = await service.history(CONVERSATION, CONTEXT)
        assert [message.content for message in history.messages] == ["hi", "one two"]


class TestStreamFailures:
    """A stream that has sent bytes cannot change its HTTP status."""

    async def test_a_failure_after_the_stream_opens_becomes_an_error_event(
        self, build_service: Callable[..., Any]
    ) -> None:
        service, _ = build_service(
            chunks=("partial", " never sent"),
            failure=ProviderError("upstream died"),
            fail_after_chunks=1,
        )

        events = [event async for event in await service.stream(CONVERSATION, "hi", CONTEXT)]

        assert isinstance(events[-1], ChatErrorEvent)
        assert events[-1].message == "upstream died"

    async def test_a_failing_stream_does_not_raise(self, build_service: Callable[..., Any]) -> None:
        """Raising mid-stream would abort the response with no explanation."""
        service, _ = build_service(failure=ProviderError("down"))

        events = [event async for event in await service.stream(CONVERSATION, "hi", CONTEXT)]

        assert isinstance(events[-1], ChatErrorEvent)

    async def test_the_error_event_carries_the_correlation_id(
        self, build_service: Callable[..., Any]
    ) -> None:
        service, _ = build_service(failure=ProviderError("down"))
        context = ExecutionContext(correlation_id="corr-123")

        events = [event async for event in await service.stream(CONVERSATION, "hi", context)]

        error = next(event for event in events if isinstance(event, ChatErrorEvent))
        assert error.correlation_id == "corr-123"

    async def test_text_generated_before_a_failure_is_kept(
        self, build_service: Callable[..., Any]
    ) -> None:
        """The user has already read it; a history that omits it is more confusing."""
        service, _ = build_service(
            chunks=("partial", " never sent"),
            failure=ProviderError("died"),
            fail_after_chunks=1,
        )

        _ = [event async for event in await service.stream(CONVERSATION, "hi", CONTEXT)]

        history = await service.history(CONVERSATION, CONTEXT)
        assert [message.content for message in history.messages] == ["hi", "partial"]


class TestRegeneration:
    async def test_it_re_answers_the_last_user_message(
        self, build_service: Callable[..., Any]
    ) -> None:
        service, stack = build_service()
        await service.send(CONVERSATION, "the question", CONTEXT)

        _ = [event async for event in await service.regenerate(CONVERSATION, CONTEXT)]

        assert stack.gateway.requests[-1].messages[-1].content == "the question"

    async def test_the_discarded_answer_is_not_used_as_context(
        self, build_service: Callable[..., Any]
    ) -> None:
        """Otherwise each regeneration continues the answer it was meant to replace."""
        service, stack = build_service()
        await service.send(CONVERSATION, "the question", CONTEXT)

        _ = [event async for event in await service.regenerate(CONVERSATION, CONTEXT)]

        assert [message.content for message in stack.gateway.requests[-1].messages] == [
            "the question"
        ]

    async def test_the_question_is_not_duplicated_in_history(
        self, build_service: Callable[..., Any]
    ) -> None:
        service, _ = build_service()
        await service.send(CONVERSATION, "the question", CONTEXT)

        _ = [event async for event in await service.regenerate(CONVERSATION, CONTEXT)]

        history = await service.history(CONVERSATION, CONTEXT)
        assert [message.content for message in history.messages] == [
            "the question",
            "The answer.",
        ]

    async def test_earlier_turns_survive(self, build_service: Callable[..., Any]) -> None:
        service, _ = build_service()
        await service.send(CONVERSATION, "first", CONTEXT)
        await service.send(CONVERSATION, "second", CONTEXT)

        _ = [event async for event in await service.regenerate(CONVERSATION, CONTEXT)]

        history = await service.history(CONVERSATION, CONTEXT)
        assert [message.role for message in history.messages] == [
            MessageRole.USER,
            MessageRole.ASSISTANT,
            MessageRole.USER,
            MessageRole.ASSISTANT,
        ]

    async def test_regenerating_an_empty_conversation_is_rejected(
        self, build_service: Callable[..., Any]
    ) -> None:
        service, _ = build_service()

        with pytest.raises(ValidationError, match="no message to regenerate"):
            _ = await service.regenerate("never-seen", CONTEXT)
