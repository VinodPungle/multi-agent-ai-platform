"""Chat endpoints.

Five routes, one use case behind all of them:

=========================================  ==========================================
``POST   /api/v1/chat/messages``           One turn, complete answer
``POST   /api/v1/chat/messages/stream``    One turn, streamed as SSE
``POST   /api/v1/chat/conversations/{id}/regenerate``  Re-answer the last message
``GET    /api/v1/chat/conversations/{id}`` Stored history
``DELETE /api/v1/chat/conversations/{id}`` Forget a conversation
=========================================  ==========================================

The route layer does three things and nothing else: translate the wire contract
into domain arguments, build the execution context, and encode what comes back.
Every decision about memory, model selection and policy belongs to
:class:`~agent_platform.application.chat_service.ChatService`.

Streaming is ``POST``, not ``GET``, so the browser's ``EventSource`` cannot be
used — it only issues ``GET`` and cannot send a body. That is the right trade:
prompts belong in a body rather than a query string, which is logged by proxies
and capped in length. The frontend reads the response stream with ``fetch``
instead, which also gives it working cancellation.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from agent_platform.api.sse import SSE_HEADERS, SSE_MEDIA_TYPE, sse_stream
from agent_platform.dependencies.providers import ChatServiceDep, ExecutionContextDep
from agent_platform.domain.chat import (
    ChatOptions,
    ChatStreamEvent,
    ChatTurn,
    ConversationHistory,
)
from agent_platform_sdk.dto.conversation import ConversationSummary
from agent_platform_shared import new_conversation_id

__all__ = [
    "ChatMessageRequest",
    "ChatTurnResponse",
    "ConversationResponse",
    "MessageResponse",
    "router",
]

router = APIRouter(tags=["chat"])

#: Applied to the conversation identifier in a path. Conversation ids are
#: server-generated UUIDs; constraining the shape here rejects a path traversal
#: or an oversized key at the boundary rather than passing it to a memory
#: provider that may use it as a storage key.
_CONVERSATION_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"


class ChatMessageRequest(BaseModel):
    """A user's message, and the conversation it belongs to."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    message: str = Field(
        min_length=1,
        max_length=32_000,
        description="The user's message. Whitespace-only messages are rejected.",
    )
    conversation_id: str | None = Field(
        default=None,
        pattern=_CONVERSATION_ID_PATTERN,
        description=(
            "Conversation to continue. Omit to start a new one — the server generates "
            "the identifier and returns it, so a client never has to invent one."
        ),
    )

    # Per-request overrides. Exposed on the public API deliberately, and the
    # trade is worth naming: choosing a model is choosing a bill, and there is
    # no authorisation layer yet to decide who may. Each is therefore bounded —
    # an unknown model is refused rather than substituted, and `max_output_tokens`
    # has a ceiling — so the worst a caller can do is pick an expensive model
    # from the catalogue an operator already chose to register.
    model_id: str | None = Field(
        default=None,
        max_length=200,
        description=(
            "Pin the model for this turn, from those /api/v1/models lists. Omit "
            "to let routing policy choose. A model that cannot serve the turn is "
            "refused, never quietly replaced."
        ),
    )
    temperature: float | None = Field(
        default=None,
        ge=0.0,
        le=2.0,
        description="Sampling temperature. Zero means deterministic, not unset.",
    )
    max_output_tokens: int | None = Field(
        default=None,
        gt=0,
        le=32_000,
        description="Cap on generated tokens. Budget policy still applies on top.",
    )

    def to_options(self) -> ChatOptions:
        """Return the generation overrides this request carries."""
        return ChatOptions(
            model_id=self.model_id,
            temperature=self.temperature,
            max_output_tokens=self.max_output_tokens,
        )


class MessageResponse(BaseModel):
    """One stored message."""

    model_config = ConfigDict(frozen=True)

    role: str = Field(description="Author: system, user, assistant or tool.")
    content: str = Field(description="Message text.")


class ChatTurnResponse(BaseModel):
    """The complete result of one turn."""

    model_config = ConfigDict(frozen=True)

    conversation_id: str
    message_id: str
    content: str = Field(description="The assistant's reply.")
    model_id: str
    provider_id: str
    prompt_tokens: int
    completion_tokens: int
    finish_reason: str | None = None
    latency_ms: float | None = None

    @classmethod
    def from_turn(cls, turn: ChatTurn) -> ChatTurnResponse:
        """Project the domain result onto the wire contract.

        Cost is deliberately not exposed. It is recorded in telemetry for
        operators; returning it to every client would publish commercial detail
        to a surface that has no use for it.
        """
        return cls(
            conversation_id=turn.conversation_id,
            message_id=turn.message_id,
            content=turn.message.content,
            model_id=turn.model_id,
            provider_id=turn.provider_id,
            prompt_tokens=turn.usage.prompt_tokens,
            completion_tokens=turn.usage.completion_tokens,
            finish_reason=turn.finish_reason,
            latency_ms=turn.latency_ms,
        )


class ConversationResponse(BaseModel):
    """Stored history for one conversation."""

    model_config = ConfigDict(frozen=True)

    conversation_id: str
    messages: tuple[MessageResponse, ...] = Field(
        default=(),
        description="Stored messages, oldest first. Empty for an unknown conversation.",
    )

    @classmethod
    def from_history(cls, history: ConversationHistory) -> ConversationResponse:
        """Project stored history onto the wire contract."""
        return cls(
            conversation_id=history.conversation_id,
            messages=tuple(
                MessageResponse(role=message.role.value, content=message.content)
                for message in history.messages
            ),
        )


def _streaming_response(events: AsyncIterator[ChatStreamEvent]) -> StreamingResponse:
    """Wrap a validated domain event stream in an SSE response.

    The caller must ``await`` the service before calling this. Once a
    ``StreamingResponse`` exists, the 200 and the SSE headers are committed, and
    a later failure can no longer be reported as a status code — so everything
    that can fail cheaply has to have failed already.
    """
    return StreamingResponse(
        sse_stream(events),
        media_type=SSE_MEDIA_TYPE,
        headers=dict(SSE_HEADERS),
    )


@router.post(
    "/messages",
    response_model=ChatTurnResponse,
    summary="Send a message and wait for the complete answer",
    description=(
        "Runs one conversational turn and returns the whole answer. Use the streaming "
        "endpoint for an interactive interface; this one exists for integrations that "
        "cannot consume a stream."
    ),
)
async def send_message(
    request: ChatMessageRequest,
    service: ChatServiceDep,
    context: ExecutionContextDep,
) -> ChatTurnResponse:
    """Run one turn and return the complete answer."""
    conversation_id = request.conversation_id or new_conversation_id()
    turn = await service.send(
        conversation_id,
        request.message,
        context.derive(conversation_id=conversation_id),
        options=request.to_options(),
    )
    return ChatTurnResponse.from_turn(turn)


@router.post(
    "/messages/stream",
    summary="Send a message and stream the answer",
    description=(
        "Runs one conversational turn, streaming server-sent events: `started`, then "
        "`delta` per increment, then `completed` — or `error` if generation fails after "
        "the stream has opened. Closing the connection stops generation and keeps the "
        "partial answer."
    ),
    responses={
        200: {
            "content": {SSE_MEDIA_TYPE: {}},
            "description": "An SSE stream of chat events.",
        }
    },
)
async def stream_message(
    request: ChatMessageRequest,
    service: ChatServiceDep,
    context: ExecutionContextDep,
) -> StreamingResponse:
    """Run one turn, streaming the answer as it is generated."""
    conversation_id = request.conversation_id or new_conversation_id()
    turn_context = context.derive(conversation_id=conversation_id)

    # Awaited here, not inside the response: validation must fail while a status
    # code is still available to carry the failure.
    events = await service.stream(
        conversation_id,
        request.message,
        turn_context,
        options=request.to_options(),
    )
    return _streaming_response(events)


@router.post(
    "/conversations/{conversation_id}/regenerate",
    summary="Re-answer the most recent message",
    description=(
        "Discards the last assistant reply and answers the preceding user message again, "
        "streaming the result. The discarded answer is not used as context for its "
        "replacement."
    ),
    responses={
        200: {
            "content": {SSE_MEDIA_TYPE: {}},
            "description": "An SSE stream of chat events.",
        }
    },
)
async def regenerate(
    conversation_id: str,
    service: ChatServiceDep,
    context: ExecutionContextDep,
) -> StreamingResponse:
    """Re-answer the most recent user message in a conversation."""
    events = await service.regenerate(
        conversation_id, context.derive(conversation_id=conversation_id)
    )
    return _streaming_response(events)


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationResponse,
    summary="Read a conversation",
    description=(
        "Returns the stored messages, oldest first. An unknown conversation returns an "
        "empty list rather than 404: a conversation that has not been written to yet is "
        "the normal case for a client restoring its view."
    ),
)
async def read_conversation(
    conversation_id: str,
    service: ChatServiceDep,
    context: ExecutionContextDep,
) -> ConversationResponse:
    """Return everything stored for a conversation."""
    history = await service.history(
        conversation_id,
        context.derive(conversation_id=conversation_id),
    )
    return ConversationResponse.from_history(history)


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Clear a conversation",
    description=(
        "Forgets a conversation. Succeeds whether or not it existed — the caller's "
        "intent is already satisfied either way."
    ),
)
async def clear_conversation(
    conversation_id: str,
    service: ChatServiceDep,
    context: ExecutionContextDep,
) -> None:
    """Forget a conversation."""
    await service.clear(conversation_id, context.derive(conversation_id=conversation_id))


class ConversationListResponse(BaseModel):
    """Recent conversations, for a history list."""

    model_config = ConfigDict(frozen=True)

    conversations: tuple[ConversationSummary, ...]


@router.get(
    "/conversations",
    response_model=ConversationListResponse,
    summary="Recent conversations",
    description=(
        "Conversations this deployment still holds, most recent first where the memory "
        "provider tracks recency. Summaries rather than transcripts: opening one fetches "
        "its messages. In-process memory loses these on restart; Redis does not."
    ),
)
async def list_conversations(
    service: ChatServiceDep,
    context: ExecutionContextDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ConversationListResponse:
    """Return recent conversations."""
    return ConversationListResponse(
        conversations=await service.list_conversations(context, limit=limit),
    )
