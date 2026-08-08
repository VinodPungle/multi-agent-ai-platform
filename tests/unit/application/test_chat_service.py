"""Chat service behaviour.

The service is where a turn becomes a model call and a memory write, so these
tests cover the three things that go wrong there and are invisible until a user
hits them: context assembly (does the model see the conversation?), recording
(does the conversation survive the turn?), and what happens when a stream ends
early — by failure or because the user pressed stop.

The gateway is faked and memory is real. Faking the gateway keeps the tests
provider-independent, which is the property the architecture exists to have;
using the real memory provider means the interaction between the two is
exercised rather than assumed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from agent_platform.application.chat_service import ChatService
from agent_platform.domain.chat import (
    ChatCompletedEvent,
    ChatDeltaEvent,
    ChatErrorEvent,
    ChatStartedEvent,
)
from agent_platform.exceptions.base import ProviderError, ValidationError
from agent_platform.memory.session_memory import InMemorySessionMemoryProvider
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.dto.completion import (
    CompletionChunk,
    CompletionRequest,
    CompletionResponse,
    TokenUsage,
)
from agent_platform_sdk.dto.message import Message
from agent_platform_sdk.interfaces.llm_gateway import LLMGateway
from agent_platform_sdk.types.enums import MessageRole

pytestmark = pytest.mark.unit

CONTEXT = ExecutionContext()
CONVERSATION = "conversation-1"


def _split_preserving_spaces(text: str) -> tuple[str, ...]:
    """Split into word chunks whose concatenation is exactly ``text``."""
    words = text.split(" ")
    return tuple(
        word if index == len(words) - 1 else f"{word} " for index, word in enumerate(words)
    )


class FakeGateway:
    """A gateway that records what it was asked and answers as instructed.

    Satisfies :class:`LLMGateway` structurally.
    """

    def __init__(
        self,
        answer: str = "The answer.",
        chunks: tuple[str, ...] | None = None,
        failure: Exception | None = None,
        fail_after_chunks: int | None = None,
    ) -> None:
        self._answer = answer
        # Whitespace stays attached to the preceding word, so concatenating the
        # chunks reproduces `answer` exactly — the same guarantee the real
        # provider gives. A fake whose stream and non-stream paths disagree
        # would make the service look broken when it is not.
        self._chunks = chunks if chunks is not None else _split_preserving_spaces(answer)
        self._failure = failure
        self._fail_after_chunks = fail_after_chunks
        self.requests: list[CompletionRequest] = []

    async def generate(
        self, request: CompletionRequest, context: ExecutionContext
    ) -> CompletionResponse:
        del context
        self.requests.append(request)
        if self._failure is not None:
            raise self._failure
        return CompletionResponse(
            message=Message(role=MessageRole.ASSISTANT, content=self._answer),
            model_id=request.model_id,
            provider_id="fake",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5),
            estimated_cost=Decimal("0.01"),
            finish_reason="stop",
        )

    async def stream(
        self, request: CompletionRequest, context: ExecutionContext
    ) -> AsyncIterator[CompletionChunk]:
        del context
        self.requests.append(request)

        if self._failure is not None and self._fail_after_chunks is None:
            raise self._failure

        for index, chunk in enumerate(self._chunks):
            if self._fail_after_chunks is not None and index >= self._fail_after_chunks:
                assert self._failure is not None
                raise self._failure
            yield CompletionChunk(delta=chunk)

        yield CompletionChunk(
            delta="",
            finish_reason="stop",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5),
        )

    async def count_tokens(
        self, request: CompletionRequest, context: ExecutionContext
    ) -> TokenUsage:
        del request, context
        return TokenUsage(prompt_tokens=10)

    async def estimate_cost(
        self, model_id: str, usage: TokenUsage, context: ExecutionContext
    ) -> Decimal:
        del model_id, usage, context
        return Decimal(0)


class ManualClock:
    """A clock that only moves when a test moves it."""

    def __init__(self) -> None:
        self._monotonic = 0.0

    def now(self) -> datetime:
        return datetime(2026, 1, 1, tzinfo=UTC)

    def monotonic(self) -> float:
        return self._monotonic

    def advance(self, seconds: float) -> None:
        self._monotonic += seconds


def build_service(
    gateway: FakeGateway | None = None,
    memory: InMemorySessionMemoryProvider | None = None,
    max_prompt_characters: int = 32_000,
) -> tuple[ChatService, FakeGateway, InMemorySessionMemoryProvider]:
    """Assemble a service over a fake gateway and real memory."""
    resolved_gateway = gateway or FakeGateway()
    resolved_memory = memory or InMemorySessionMemoryProvider()
    service = ChatService(
        gateway=resolved_gateway,
        memory=resolved_memory,
        clock=ManualClock(),
        model_id="test-model",
        system_prompt="You are a test assistant.",
        max_prompt_characters=max_prompt_characters,
    )
    return service, resolved_gateway, resolved_memory


class TestContractConformance:
    def test_the_fake_gateway_satisfies_the_contract(self) -> None:
        """If it did not, these tests would be proving something else."""
        assert isinstance(FakeGateway(), LLMGateway)


class TestPromptValidation:
    """An invalid prompt must cost nothing."""

    @pytest.mark.parametrize("prompt", ["", "   ", "\n\t "])
    async def test_a_blank_prompt_is_rejected(self, prompt: str) -> None:
        service, gateway, _ = build_service()

        with pytest.raises(ValidationError, match="cannot be empty"):
            await service.send(CONVERSATION, prompt, CONTEXT)

        assert not gateway.requests

    async def test_an_oversized_prompt_is_rejected(self) -> None:
        service, gateway, _ = build_service(max_prompt_characters=10)

        with pytest.raises(ValidationError, match="cannot exceed"):
            await service.send(CONVERSATION, "x" * 11, CONTEXT)

        assert not gateway.requests

    async def test_the_prompt_is_trimmed_before_use(self) -> None:
        service, gateway, _ = build_service()

        await service.send(CONVERSATION, "  hello  ", CONTEXT)

        assert gateway.requests[0].messages[-1].content == "hello"

    async def test_a_blank_prompt_is_rejected_before_a_stream_opens(self) -> None:
        """Failing here still allows a proper HTTP status; failing later does not."""
        service, gateway, _ = build_service()

        with pytest.raises(ValidationError):
            _ = await service.stream(CONVERSATION, "  ", CONTEXT)

        assert not gateway.requests


class TestContextAssembly:
    """The model must see the conversation, and only the conversation."""

    async def test_the_first_turn_sends_only_the_new_message(self) -> None:
        service, gateway, _ = build_service()

        await service.send(CONVERSATION, "first question", CONTEXT)

        assert [message.content for message in gateway.requests[0].messages] == ["first question"]

    async def test_a_later_turn_sends_the_whole_history(self) -> None:
        service, gateway, _ = build_service()

        await service.send(CONVERSATION, "first", CONTEXT)
        await service.send(CONVERSATION, "second", CONTEXT)

        assert [message.content for message in gateway.requests[1].messages] == [
            "first",
            "The answer.",
            "second",
        ]

    async def test_conversations_do_not_leak_into_each_other(self) -> None:
        service, gateway, _ = build_service()

        await service.send("conversation-a", "secret", CONTEXT)
        await service.send("conversation-b", "unrelated", CONTEXT)

        assert [message.content for message in gateway.requests[1].messages] == ["unrelated"]

    async def test_the_system_prompt_is_carried_on_the_request(self) -> None:
        service, gateway, _ = build_service()

        await service.send(CONVERSATION, "hello", CONTEXT)

        assert gateway.requests[0].system_prompt == "You are a test assistant."

    async def test_the_system_prompt_is_never_stored_as_a_message(self) -> None:
        """Storing it would replay it as if the user had said it, and freeze it in history."""
        service, _, memory = build_service()

        await service.send(CONVERSATION, "hello", CONTEXT)

        stored = await memory.load(CONVERSATION, CONTEXT)
        assert all(message.role is not MessageRole.SYSTEM for message in stored)

    async def test_the_model_comes_from_configuration(self) -> None:
        service, gateway, _ = build_service()

        await service.send(CONVERSATION, "hello", CONTEXT)

        assert gateway.requests[0].model_id == "test-model"


class TestRecording:
    async def test_a_completed_turn_stores_both_messages(self) -> None:
        service, _, memory = build_service()

        await service.send(CONVERSATION, "question", CONTEXT)

        stored = await memory.load(CONVERSATION, CONTEXT)
        assert [(message.role, message.content) for message in stored] == [
            (MessageRole.USER, "question"),
            (MessageRole.ASSISTANT, "The answer."),
        ]

    async def test_a_failed_turn_does_not_store_an_assistant_message(self) -> None:
        service, _, memory = build_service(FakeGateway(failure=ProviderError("upstream down")))

        with pytest.raises(ProviderError):
            await service.send(CONVERSATION, "question", CONTEXT)

        stored = await memory.load(CONVERSATION, CONTEXT)
        assert all(message.role is not MessageRole.ASSISTANT for message in stored)

    async def test_history_returns_what_was_stored(self) -> None:
        service, _, _ = build_service()
        await service.send(CONVERSATION, "question", CONTEXT)

        history = await service.history(CONVERSATION, CONTEXT)

        assert history.conversation_id == CONVERSATION
        assert len(history.messages) == 2

    async def test_an_unknown_conversation_has_an_empty_history(self) -> None:
        service, _, _ = build_service()

        history = await service.history("never-seen", CONTEXT)

        assert history.is_empty

    async def test_clearing_forgets_the_conversation(self) -> None:
        service, _, _ = build_service()
        await service.send(CONVERSATION, "question", CONTEXT)

        await service.clear(CONVERSATION, CONTEXT)

        assert (await service.history(CONVERSATION, CONTEXT)).is_empty


class TestStreaming:
    async def test_the_event_sequence_is_started_deltas_completed(self) -> None:
        service, _, _ = build_service(FakeGateway(chunks=("Hello", " ", "world")))

        events = [event async for event in await service.stream(CONVERSATION, "hi", CONTEXT)]

        assert isinstance(events[0], ChatStartedEvent)
        assert all(isinstance(event, ChatDeltaEvent) for event in events[1:-1])
        assert isinstance(events[-1], ChatCompletedEvent)

    async def test_deltas_reassemble_into_the_completed_content(self) -> None:
        service, _, _ = build_service(FakeGateway(chunks=("Hello", " ", "world")))

        events = [event async for event in await service.stream(CONVERSATION, "hi", CONTEXT)]

        deltas = "".join(event.delta for event in events if isinstance(event, ChatDeltaEvent))
        completed = next(event for event in events if isinstance(event, ChatCompletedEvent))
        assert deltas == completed.content == "Hello world"

    async def test_the_message_id_is_stable_across_the_stream(self) -> None:
        """A client creates the element on `started` and reconciles it on `completed`."""
        service, _, _ = build_service()

        events = [event async for event in await service.stream(CONVERSATION, "hi", CONTEXT)]

        started = next(event for event in events if isinstance(event, ChatStartedEvent))
        completed = next(event for event in events if isinstance(event, ChatCompletedEvent))
        assert started.message_id == completed.message_id

    async def test_a_streamed_turn_is_recorded(self) -> None:
        service, _, memory = build_service(FakeGateway(chunks=("one", " two")))

        _ = [event async for event in await service.stream(CONVERSATION, "hi", CONTEXT)]

        stored = await memory.load(CONVERSATION, CONTEXT)
        assert [message.content for message in stored] == ["hi", "one two"]

    async def test_usage_is_reported_on_completion(self) -> None:
        service, _, _ = build_service()

        events = [event async for event in await service.stream(CONVERSATION, "hi", CONTEXT)]

        completed = next(event for event in events if isinstance(event, ChatCompletedEvent))
        assert completed.usage.completion_tokens == 5
        assert completed.finish_reason == "stop"


class TestStreamFailures:
    """A stream that has sent bytes cannot change its HTTP status."""

    async def test_a_failure_after_the_stream_opens_becomes_an_error_event(self) -> None:
        service, _, _ = build_service(
            FakeGateway(
                chunks=("partial", " answer"),
                failure=ProviderError("upstream died"),
                fail_after_chunks=1,
            )
        )

        events = [event async for event in await service.stream(CONVERSATION, "hi", CONTEXT)]

        assert isinstance(events[-1], ChatErrorEvent)
        assert events[-1].message == "upstream died"

    async def test_a_failing_stream_does_not_raise(self) -> None:
        """Raising mid-stream would abort the response with no explanation for the client."""
        service, _, _ = build_service(FakeGateway(failure=ProviderError("down")))

        events = [event async for event in await service.stream(CONVERSATION, "hi", CONTEXT)]

        assert isinstance(events[-1], ChatErrorEvent)

    async def test_the_error_event_carries_the_correlation_id(self) -> None:
        service, _, _ = build_service(FakeGateway(failure=ProviderError("down")))
        context = ExecutionContext(correlation_id="corr-123")

        events = [event async for event in await service.stream(CONVERSATION, "hi", context)]

        error = next(event for event in events if isinstance(event, ChatErrorEvent))
        assert error.correlation_id == "corr-123"

    async def test_text_generated_before_a_failure_is_kept(self) -> None:
        """The user has already read it; a history that omits it is more confusing."""
        service, _, memory = build_service(
            FakeGateway(
                chunks=("partial", " answer"),
                failure=ProviderError("died"),
                fail_after_chunks=1,
            )
        )

        _ = [event async for event in await service.stream(CONVERSATION, "hi", CONTEXT)]

        stored = await memory.load(CONVERSATION, CONTEXT)
        assert [message.content for message in stored] == ["hi", "partial"]

    async def test_the_question_is_recorded_even_when_nothing_was_generated(self) -> None:
        """A retry needs the history, and the user should see what they asked."""
        service, _, memory = build_service(FakeGateway(failure=ProviderError("down")))

        _ = [event async for event in await service.stream(CONVERSATION, "hi", CONTEXT)]

        stored = await memory.load(CONVERSATION, CONTEXT)
        assert [message.content for message in stored] == ["hi"]


class TestStopGeneration:
    """Stopping is the consumer closing the iterator."""

    async def test_a_partial_answer_is_stored_when_the_client_stops(self) -> None:
        service, _, memory = build_service(FakeGateway(chunks=("one", " two", " three", " four")))

        stream = await service.stream(CONVERSATION, "hi", CONTEXT)
        collected: list[str] = []
        async for event in stream:
            if isinstance(event, ChatDeltaEvent):
                collected.append(event.delta)
                if len(collected) == 2:
                    break
        await stream.aclose()

        stored = await memory.load(CONVERSATION, CONTEXT)
        assert [message.content for message in stored] == ["hi", "one two"]


class TestRegeneration:
    async def test_it_re_answers_the_last_user_message(self) -> None:
        service, gateway, _ = build_service()
        await service.send(CONVERSATION, "the question", CONTEXT)

        _ = [event async for event in await service.regenerate(CONVERSATION, CONTEXT)]

        assert gateway.requests[-1].messages[-1].content == "the question"

    async def test_the_discarded_answer_is_not_used_as_context(self) -> None:
        """Otherwise each regeneration continues the answer it was meant to replace."""
        service, gateway, _ = build_service()
        await service.send(CONVERSATION, "the question", CONTEXT)

        _ = [event async for event in await service.regenerate(CONVERSATION, CONTEXT)]

        contents = [message.content for message in gateway.requests[-1].messages]
        assert contents == ["the question"]

    async def test_the_question_is_not_duplicated_in_history(self) -> None:
        service, _, memory = build_service()
        await service.send(CONVERSATION, "the question", CONTEXT)

        _ = [event async for event in await service.regenerate(CONVERSATION, CONTEXT)]

        stored = await memory.load(CONVERSATION, CONTEXT)
        assert [message.content for message in stored] == ["the question", "The answer."]

    async def test_earlier_turns_survive_a_regeneration(self) -> None:
        service, _, memory = build_service()
        await service.send(CONVERSATION, "first", CONTEXT)
        await service.send(CONVERSATION, "second", CONTEXT)

        _ = [event async for event in await service.regenerate(CONVERSATION, CONTEXT)]

        stored = await memory.load(CONVERSATION, CONTEXT)
        assert [message.content for message in stored] == [
            "first",
            "The answer.",
            "second",
            "The answer.",
        ]

    async def test_regenerating_an_empty_conversation_is_rejected(self) -> None:
        service, _, _ = build_service()

        with pytest.raises(ValidationError, match="no message to regenerate"):
            _ = await service.regenerate("never-seen", CONTEXT)
