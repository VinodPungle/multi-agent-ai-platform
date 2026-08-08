"""The chat use case.

Adapts chat-shaped concerns — a conversation id, a transcript, an SSE event
stream — onto the Agent Runtime. It is the *chat* bounded context, not the
orchestration engine: since Milestone 03 it holds no memory of its own, chooses
no model and calls no gateway.

What changed when the runtime arrived, and why it matters
    This service used to load history, assemble a prompt and call the
    :class:`LLMGateway` itself. All three moved into the runtime, where they are
    done once for every agent rather than once per caller. What is left here is
    genuinely chat's own: validating a user's message, mapping a conversation id
    onto a turn, and translating runtime output into the event types the SSE
    endpoint sends.

    That is the test of whether the runtime earned its place. If a second entry
    point — a scheduled agent, an agent-to-agent call, a queue consumer — had to
    re-implement memory retrieval and prompt assembly, it would not have.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator

from agent_platform.domain.chat import (
    ChatCompletedEvent,
    ChatDeltaEvent,
    ChatErrorEvent,
    ChatStartedEvent,
    ChatStreamEvent,
    ChatToolEvent,
    ChatTurn,
    ConversationHistory,
)
from agent_platform.exceptions.base import PlatformError, ValidationError
from agent_platform.runtime.agent_runtime import AgentRuntime, RuntimeTurn
from agent_platform.telemetry.logging import get_logger
from agent_platform.telemetry.tracing import get_tracer
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.dto.completion import TokenUsage
from agent_platform_sdk.dto.message import Message, ToolCall
from agent_platform_sdk.interfaces.memory_provider import MemoryProvider
from agent_platform_sdk.types.enums import MessageRole
from agent_platform_shared import new_message_id

__all__ = ["ChatService"]

_logger = get_logger(__name__)
_tracer = get_tracer(__name__)


class ChatService:
    """Runs one conversational turn through the Agent Runtime."""

    def __init__(
        self,
        runtime: AgentRuntime,
        memory: MemoryProvider,
        agent_id: str,
        max_prompt_characters: int = 32_000,
    ) -> None:
        """Create the service.

        Args:
            runtime: The Agent Runtime. Execution, memory coordination, prompt
                assembly, model selection and policy all belong to it.
            memory: Read access for the transcript endpoints. The runtime owns
                *writing* memory during a turn; this reads and clears it on
                behalf of the API, which is a conversation-management concern
                rather than an execution one.
            agent_id: Agent that answers chat turns. Configuration, so pointing
                chat at a different agent needs no code change.
            max_prompt_characters: Rejection threshold for a single message.
                Characters rather than tokens because no tokeniser exists before
                a provider is chosen; the model registry enforces the real
                context window.
        """
        self._runtime = runtime
        self._memory = memory
        self._agent_id = agent_id
        self._max_prompt_characters = max_prompt_characters

    # -- Conversation state ------------------------------------------------

    async def history(
        self,
        conversation_id: str,
        context: ExecutionContext,
    ) -> ConversationHistory:
        """Return everything stored for a conversation."""
        messages = await self._memory.load(conversation_id, context)
        return ConversationHistory(conversation_id=conversation_id, messages=messages)

    async def clear(self, conversation_id: str, context: ExecutionContext) -> None:
        """Forget a conversation. Clearing an unknown one succeeds."""
        await self._memory.delete(conversation_id, context)
        _logger.info("chat.conversation_cleared", **context.to_log_fields())

    # -- Turns -------------------------------------------------------------

    async def send(
        self,
        conversation_id: str,
        prompt: str,
        context: ExecutionContext,
    ) -> ChatTurn:
        """Run one turn and return the complete answer.

        Raises:
            ValidationError: the message is empty or too long.
            NotFoundError: the configured agent is not registered.
            PolicyViolationError: the agent is disabled.
            ProviderError: the provider failed and retries were exhausted.
        """
        cleaned = self._validate_prompt(prompt)

        with _tracer.start_as_current_span("chat.send") as span:
            span.set_attribute("chat.streaming", False)

            turn = await self._runtime.prepare(self._agent_id, cleaned, context, conversation_id)
            result = await self._runtime.execute(turn)

            _logger.info(
                "chat.turn_completed",
                streaming=False,
                prompt_characters=len(cleaned),
                completion_characters=len(result.message.content),
                **turn.context.to_log_fields(),
            )

            return ChatTurn(
                conversation_id=conversation_id,
                message_id=new_message_id(),
                message=result.message,
                model_id=result.model_id,
                provider_id=result.provider_id,
                usage=result.usage,
                finish_reason=result.finish_reason,
                latency_ms=result.latency_ms,
                estimated_cost=result.estimated_cost,
            )

    async def stream(
        self,
        conversation_id: str,
        prompt: str,
        context: ExecutionContext,
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        """Validate and prepare the turn, then return the events it will emit.

        An ``async def`` that *returns* an iterator rather than an async
        generator that yields one, and the distinction is load-bearing. A
        generator body does not run until it is first iterated — and a
        ``StreamingResponse`` iterates only after the 200 and the SSE headers
        have gone out. Validation inside the generator would therefore reject a
        request the client has already been told succeeded.

        Everything that can fail cheaply — an empty message, an unknown or
        disabled agent, a missing prompt — happens here, before the response
        starts. Everything after the first byte is reported in-band.

        Raises:
            ValidationError: the message is empty or too long.
            NotFoundError: the configured agent is not registered.
            PolicyViolationError: the agent is disabled.
        """
        cleaned = self._validate_prompt(prompt)
        turn = await self._runtime.prepare(self._agent_id, cleaned, context, conversation_id)
        return self._emit(turn, conversation_id)

    async def regenerate(
        self,
        conversation_id: str,
        context: ExecutionContext,
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        """Re-answer the most recent user message.

        Drops the trailing turn from memory first, so the discarded answer does
        not become context for its own replacement — which would make each
        regeneration a continuation rather than a fresh attempt.

        Raises:
            ValidationError: the conversation has no user message to re-answer.
        """
        messages = await self._memory.load(conversation_id, context)
        prompt = self._last_user_message(messages)

        if prompt is None:
            message = "There is no message to regenerate in this conversation."
            raise ValidationError(message, details={"conversation_id": conversation_id})

        await self._memory.save(conversation_id, self._without_last_turn(messages), context)
        _logger.info("chat.regenerating", **context.to_log_fields())

        return await self.stream(conversation_id, prompt, context)

    # -- Internals ---------------------------------------------------------

    async def _emit(
        self,
        turn: RuntimeTurn,
        conversation_id: str,
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        """Translate runtime chunks into chat events.

        Never raises. A stream that has already sent bytes cannot change its
        HTTP status, so a failure becomes a :class:`ChatErrorEvent` and the
        stream ends normally.
        """
        message_id = new_message_id()
        chunks: list[str] = []
        usage = TokenUsage()
        finish_reason: str | None = None

        yield ChatStartedEvent(
            conversation_id=conversation_id,
            message_id=message_id,
            model_id=turn.request.model_id,
        )

        try:
            async for chunk in self._runtime.stream(turn):
                # A chunk carrying tool calls and no text is the loop announcing
                # what it is about to run, not content. Forwarded as its own
                # event so the client can say "searching…" instead of showing an
                # empty bubble for several seconds.
                for call in chunk.tool_calls:
                    yield ChatToolEvent(
                        tool_id=call.tool_id,
                        summary=_summarise_tool_call(call),
                    )

                if chunk.delta:
                    chunks.append(chunk.delta)
                    yield ChatDeltaEvent(delta=chunk.delta)
                if chunk.usage is not None:
                    usage = chunk.usage
                if chunk.finish_reason is not None:
                    finish_reason = chunk.finish_reason

        except PlatformError as error:
            _logger.warning(
                "chat.turn_failed",
                error_type=type(error).__name__,
                error_category=error.category.value,
                **turn.context.to_log_fields(),
            )
            yield ChatErrorEvent(
                category=error.category,
                message=error.message,
                correlation_id=turn.context.correlation_id,
            )
            return

        content = "".join(chunks)
        _logger.info(
            "chat.turn_completed",
            streaming=True,
            chunk_count=len(chunks),
            completion_characters=len(content),
            **turn.context.to_log_fields(),
        )

        yield ChatCompletedEvent(
            message_id=message_id,
            content=content,
            usage=usage,
            finish_reason=finish_reason,
        )

    def _validate_prompt(self, prompt: str) -> str:
        """Return the trimmed message, or reject it.

        Raises:
            ValidationError: the message is blank or exceeds the character cap.
        """
        cleaned = prompt.strip()

        if not cleaned:
            message = "A message cannot be empty."
            raise ValidationError(message)

        if len(cleaned) > self._max_prompt_characters:
            message = (
                f"A message cannot exceed {self._max_prompt_characters:,} characters. "
                f"This one is {len(cleaned):,}."
            )
            raise ValidationError(message, details={"characters": len(cleaned)})

        return cleaned

    @staticmethod
    def _last_user_message(messages: tuple[Message, ...]) -> str | None:
        """Return the most recent user message, or ``None``."""
        for message in reversed(messages):
            if message.role is MessageRole.USER:
                return message.content
        return None

    @staticmethod
    def _without_last_turn(messages: tuple[Message, ...]) -> tuple[Message, ...]:
        """Return ``messages`` with the trailing user/assistant pair removed.

        Both halves go: the user message is re-sent by the regenerated turn and
        would otherwise be duplicated in history.
        """
        kept = list(messages)

        while kept and kept[-1].role is not MessageRole.USER:
            kept.pop()
        if kept and kept[-1].role is MessageRole.USER:
            kept.pop()

        return tuple(kept)


def _summarise_tool_call(call: ToolCall) -> str:
    """Render a tool call as one short line a user can read.

    Arguments arrive as a raw JSON string that may be malformed — models emit
    invalid JSON often enough that parsing has to be defensive. A summary that
    raised would fail a turn to render a caption.

    Only the recognised, displayable fields are surfaced. Echoing arbitrary
    arguments into the UI would eventually put something in front of a user that
    was never meant for them.
    """
    try:
        arguments = json.loads(call.arguments) if call.arguments.strip() else {}
    except json.JSONDecodeError:
        return ""

    if not isinstance(arguments, dict):
        return ""

    query = arguments.get("query")
    return str(query)[:200] if isinstance(query, str) else ""
