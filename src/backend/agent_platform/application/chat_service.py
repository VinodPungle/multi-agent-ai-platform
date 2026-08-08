"""The chat use case.

Assembles context, calls a model through the gateway, and records the result —
the subset of the agent lifecycle (``architecture.md`` §14) that Milestone 02
covers. Tool planning, evaluation and multi-agent orchestration join it in later
milestones, at the same seam.

What this service depends on:

============================  ==============================================
``LLMGateway``                The only path to a model. Never an ``LLMProvider``.
``MemoryProvider``            Conversation state. Never a dictionary of its own.
``Clock``                     Injected, so latency assertions are deterministic.
============================  ==============================================

None of those is a concrete class, so this file survives Azure AI Foundry
arriving, Redis replacing in-process memory, and LangGraph taking over
orchestration.

Streaming and non-streaming share one code path for assembling context and one
for recording the result. Two copies would drift, and the streamed path is the
one users actually exercise — a divergence would be found in production first.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from agent_platform.domain.chat import (
    ChatCompletedEvent,
    ChatDeltaEvent,
    ChatErrorEvent,
    ChatStartedEvent,
    ChatStreamEvent,
    ChatTurn,
    ConversationHistory,
)
from agent_platform.exceptions.base import PlatformError, ValidationError
from agent_platform.telemetry.logging import get_logger
from agent_platform.telemetry.tracing import get_tracer
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.dto.completion import CompletionRequest, TokenUsage
from agent_platform_sdk.dto.message import Message
from agent_platform_sdk.interfaces.llm_gateway import LLMGateway
from agent_platform_sdk.interfaces.memory_provider import MemoryProvider
from agent_platform_sdk.types.enums import MessageRole
from agent_platform_shared import new_message_id
from agent_platform_shared.clock import Clock

__all__ = ["ChatService"]

_logger = get_logger(__name__)
_tracer = get_tracer(__name__)


class ChatService:
    """Runs one conversational turn, streamed or complete."""

    def __init__(
        self,
        gateway: LLMGateway,
        memory: MemoryProvider,
        clock: Clock,
        model_id: str,
        system_prompt: str,
        max_prompt_characters: int = 32_000,
    ) -> None:
        """Create the service.

        Args:
            gateway: Provider-independent access to inference.
            memory: Conversation storage.
            clock: Injected time source, used to measure turn latency.
            model_id: Model to request. Resolved from configuration, never
                hardcoded, so switching models is a settings change.
            system_prompt: Instruction prepended to every turn. Carried on the
                request rather than pushed into the message history, so it is
                never stored as if the user had said it and can be changed
                without rewriting past conversations.
            max_prompt_characters: Rejection threshold for a single message.
                Characters rather than tokens because no tokeniser is available
                before the provider is chosen; it exists to stop an obviously
                abusive payload, not to enforce the context window, which the
                model registry does from Milestone 03.
        """
        self._gateway = gateway
        self._memory = memory
        self._clock = clock
        self._model_id = model_id
        self._system_prompt = system_prompt
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
            ValidationError: the prompt is empty or too long.
            NotFoundError: no provider could be resolved.
            ProviderError: the provider failed and retries were exhausted.
        """
        cleaned = self._validate_prompt(prompt)

        with _tracer.start_as_current_span("chat.send") as span:
            span.set_attribute("chat.streaming", False)

            request = await self._build_request(conversation_id, cleaned, context)
            started = self._clock.monotonic()
            response = await self._gateway.generate(request, context)
            elapsed_ms = (self._clock.monotonic() - started) * 1000

            message_id = new_message_id()
            await self._record_turn(conversation_id, cleaned, response.message.content, context)

            _logger.info(
                "chat.turn_completed",
                streaming=False,
                prompt_characters=len(cleaned),
                completion_characters=len(response.message.content),
                **context.to_log_fields(),
            )

            return ChatTurn(
                conversation_id=conversation_id,
                message_id=message_id,
                message=response.message,
                model_id=response.model_id,
                provider_id=response.provider_id,
                usage=response.usage,
                finish_reason=response.finish_reason,
                latency_ms=response.latency_ms or elapsed_ms,
                estimated_cost=response.estimated_cost,
            )

    async def stream(
        self,
        conversation_id: str,
        prompt: str,
        context: ExecutionContext,
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        """Validate the turn, then return the stream of events it will emit.

        An ``async def`` that *returns* an iterator rather than an async
        generator that yields one, and the distinction is load-bearing. A
        generator body does not run until it is first iterated — and a
        ``StreamingResponse`` iterates only after the 200 and the SSE headers
        have gone out. Validation inside the generator would therefore reject a
        request that the client has already been told succeeded, with no way
        left to send it a 422.

        Everything that can fail cheaply happens here, before the response
        starts. Everything after the first byte is reported in-band as a
        :class:`ChatErrorEvent`.

        Raises:
            ValidationError: the prompt is empty or too long.
        """
        cleaned = self._validate_prompt(prompt)
        request = await self._build_request(conversation_id, cleaned, context)
        return self._emit(conversation_id, cleaned, request, context)

    async def _emit(
        self,
        conversation_id: str,
        cleaned: str,
        request: CompletionRequest,
        context: ExecutionContext,
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        """Emit the events of a validated turn.

        Never raises. A stream that has already sent bytes cannot change its
        HTTP status, so a failure becomes a :class:`ChatErrorEvent` and the
        stream ends normally.

        Stopping generation is a client disconnect: the consumer closes the
        iterator, and the ``finally`` block stores whatever was generated. A
        user who read half an answer keeps it.
        """
        message_id = new_message_id()
        chunks: list[str] = []
        completed = False
        started = self._clock.monotonic()

        yield ChatStartedEvent(
            conversation_id=conversation_id,
            message_id=message_id,
            model_id=request.model_id,
        )

        try:
            usage = TokenUsage()
            finish_reason: str | None = None

            async for chunk in self._gateway.stream(request, context):
                if chunk.delta:
                    chunks.append(chunk.delta)
                    yield ChatDeltaEvent(delta=chunk.delta)
                if chunk.usage is not None:
                    usage = chunk.usage
                if chunk.finish_reason is not None:
                    finish_reason = chunk.finish_reason

            completed = True
            content = "".join(chunks)
            elapsed_ms = (self._clock.monotonic() - started) * 1000

            _logger.info(
                "chat.turn_completed",
                streaming=True,
                chunk_count=len(chunks),
                completion_characters=len(content),
                latency_ms=round(elapsed_ms, 2),
                **context.to_log_fields(),
            )

            yield ChatCompletedEvent(
                message_id=message_id,
                content=content,
                usage=usage,
                finish_reason=finish_reason,
                latency_ms=elapsed_ms,
            )

        except PlatformError as error:
            completed = True
            _logger.warning(
                "chat.turn_failed",
                error_type=type(error).__name__,
                error_category=error.category.value,
                **context.to_log_fields(),
            )
            yield ChatErrorEvent(
                category=error.category,
                message=error.message,
                correlation_id=context.correlation_id,
            )

        finally:
            # Runs on success, on failure, and on the consumer closing the
            # iterator — which is what "stop generation" is. Storing a partial
            # answer is deliberate: the user has already read it, and a
            # conversation that omits what was on screen is more confusing than
            # one that ends mid-sentence.
            partial = "".join(chunks)
            if partial or completed:
                await self._record_turn(conversation_id, cleaned, partial, context)
            else:
                # Nothing was generated and the turn failed before any text.
                # The user's message is still recorded so the conversation
                # shows what was asked, and a retry has the history it needs.
                await self._memory.append(
                    conversation_id,
                    Message(role=MessageRole.USER, content=cleaned),
                    context,
                )

    async def regenerate(
        self,
        conversation_id: str,
        context: ExecutionContext,
    ) -> AsyncGenerator[ChatStreamEvent, None]:
        """Re-answer the most recent user message.

        Drops the trailing assistant message first, so the discarded answer does
        not become context for its own replacement — which would make each
        regeneration a continuation rather than a fresh attempt.

        Validates eagerly for the same reason as :meth:`stream`: a conversation
        with nothing to regenerate must produce a status code, not a stream that
        opens and immediately reports an error.

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

    def _validate_prompt(self, prompt: str) -> str:
        """Return the trimmed prompt, or reject it.

        Raises:
            ValidationError: the prompt is blank or exceeds the character cap.
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

    async def _build_request(
        self,
        conversation_id: str,
        prompt: str,
        context: ExecutionContext,
    ) -> CompletionRequest:
        """Assemble the model request from stored history plus the new message.

        Deterministic and side-effect free, which is what makes context
        assembly testable (``architecture.md``, "Context Assembly"). The new
        message is *not* stored here — recording happens after the model has
        answered, so a failed turn does not leave a question in history that was
        never asked of a model.
        """
        history = await self._memory.load(conversation_id, context)

        return CompletionRequest(
            model_id=self._model_id,
            messages=(*history, Message(role=MessageRole.USER, content=prompt)),
            system_prompt=self._system_prompt,
            metadata={"conversation_id": conversation_id},
        )

    async def _record_turn(
        self,
        conversation_id: str,
        prompt: str,
        answer: str,
        context: ExecutionContext,
    ) -> None:
        """Store the user message and the assistant reply, in order."""
        await self._memory.append(
            conversation_id,
            Message(role=MessageRole.USER, content=prompt),
            context,
        )
        if answer:
            await self._memory.append(
                conversation_id,
                Message(role=MessageRole.ASSISTANT, content=answer),
                context,
            )

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
