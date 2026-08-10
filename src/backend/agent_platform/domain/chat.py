"""Chat domain contracts.

The vocabulary the application layer speaks: what a caller asks for, what comes
back, and what a stream emits along the way. Depends on the SDK's provider-neutral
types and on nothing else — no FastAPI, no provider, no transport.

That independence is what lets the same service be driven by an HTTP route today
and by a WebSocket, a queue consumer or an agent-to-agent call later, without the
service changing.

Streaming events are **separate types rather than one type with optional
fields**. A single event model would need every field nullable, and a consumer
would have to know by convention which fields are populated for which event. The
`type` discriminant makes that explicit, and the frontend narrows on it directly.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_platform_sdk.dto.completion import TokenUsage
from agent_platform_sdk.dto.message import Message
from agent_platform_sdk.types.enums import ErrorCategory

__all__ = [
    "ChatCompletedEvent",
    "ChatDeltaEvent",
    "ChatErrorEvent",
    "ChatEventType",
    "ChatOptions",
    "ChatStartedEvent",
    "ChatStreamEvent",
    "ChatToolEvent",
    "ChatTurn",
    "ConversationHistory",
]


class ChatEventType(StrEnum):
    """Kinds of event a streamed turn emits.

    The value is used as the SSE event name, so a browser client can attach a
    listener per type instead of parsing every payload to find out what it is.
    """

    STARTED = "started"
    TOOL = "tool"
    DELTA = "delta"
    COMPLETED = "completed"
    ERROR = "error"


class ChatStartedEvent(BaseModel):
    """First event of a stream: the turn was accepted and a provider resolved.

    Emitted before any text. It carries the identifiers the client needs to
    render an assistant bubble and to correlate a later failure — a stream that
    fails after this event still has a message the user can see.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal[ChatEventType.STARTED] = ChatEventType.STARTED
    conversation_id: str = Field(description="Conversation this turn belongs to.")
    message_id: str = Field(description="Identifier of the assistant message being generated.")
    model_id: str = Field(description="Model requested for this turn.")

    # No `provider_id`. It is resolved by the gateway when the first chunk is
    # requested, which is *after* this event has to be sent — a client waiting
    # for provider attribution before rendering an assistant bubble would wait
    # for the whole generation. Publishing an empty string instead would put a
    # field on the wire that is always wrong.
    #
    # Provider attribution is available where it is actually known: on the
    # non-streaming response, and in every log record and span for the turn.


class ChatToolEvent(BaseModel):
    """The agent decided to use a tool, and is waiting on it.

    Emitted between `started` and the first `delta`, because that gap is
    otherwise unexplained silence: a searching turn spends a whole model call
    plus the search before a single character of the answer appears, and a user
    watching a blank bubble has no way to tell that from a hang.

    It also makes the platform's behaviour legible. An answer that quietly used
    a search looks identical to one the model invented, and those two deserve
    very different amounts of trust.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal[ChatEventType.TOOL] = ChatEventType.TOOL
    tool_id: str = Field(description="Tool the agent invoked.")
    summary: str = Field(
        default="",
        description=(
            "Short human-readable description of what was asked of the tool — "
            "for search, the query. Rendered directly, so it carries no "
            "arguments a user should not see."
        ),
    )


class ChatDeltaEvent(BaseModel):
    """An increment of generated text.

    Deltas concatenate to the final content exactly. Clients append rather than
    replace, so no delta may repeat text already sent.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal[ChatEventType.DELTA] = ChatEventType.DELTA
    delta: str = Field(description="Text to append to what has already been rendered.")


class ChatCompletedEvent(BaseModel):
    """Terminal event of a successful stream.

    Carries the assembled content as well as the accounting. Sending the full
    text again is deliberate redundancy: a client that dropped a delta, or one
    that reconnected mid-stream, can correct itself instead of displaying a
    silently truncated answer.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal[ChatEventType.COMPLETED] = ChatEventType.COMPLETED
    message_id: str = Field(description="Identifier of the completed assistant message.")
    content: str = Field(description="The complete assistant message.")
    usage: TokenUsage = Field(description="Token accounting for the turn.")
    finish_reason: str | None = Field(default=None, description="Why generation stopped.")
    latency_ms: float | None = Field(default=None, ge=0, description="Total turn latency.")
    estimated_cost: Decimal | None = Field(default=None, ge=0, description="Estimated cost in USD.")
    cancelled: bool = Field(
        default=False,
        description=(
            "True when the client stopped generation. The partial answer is kept and "
            "stored: discarding what the user already read would be worse than keeping it."
        ),
    )


class ChatErrorEvent(BaseModel):
    """Terminal event of a failed stream.

    A stream that has already sent bytes cannot change its HTTP status, so a
    mid-stream failure has to be reported in-band. Without this event a client
    could not distinguish a failure from a normal end of stream.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal[ChatEventType.ERROR] = ChatEventType.ERROR
    category: ErrorCategory = Field(description="Normalised failure classification.")
    message: str = Field(description="Client-safe summary. Never contains internal detail.")
    correlation_id: str | None = Field(
        default=None,
        description="Identifier joining this failure to server logs and traces.",
    )


#: Everything a streamed turn can emit. Discriminated on `type`.
ChatStreamEvent = (
    ChatStartedEvent | ChatToolEvent | ChatDeltaEvent | ChatCompletedEvent | ChatErrorEvent
)


class ChatTurn(BaseModel):
    """The result of one complete, non-streamed exchange."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    conversation_id: str
    message_id: str = Field(description="Identifier of the assistant message.")
    message: Message = Field(description="The assistant's reply.")
    model_id: str
    provider_id: str
    usage: TokenUsage = Field(default_factory=TokenUsage)
    finish_reason: str | None = Field(default=None)
    latency_ms: float | None = Field(default=None, ge=0)
    estimated_cost: Decimal | None = Field(default=None, ge=0)


class ConversationHistory(BaseModel):
    """Everything stored for one conversation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    conversation_id: str
    messages: tuple[Message, ...] = Field(
        default=(),
        description="Stored messages, oldest first.",
    )

    @property
    def is_empty(self) -> bool:
        """Whether the conversation holds no messages."""
        return not self.messages


class ChatOptions(BaseModel):
    """Per-request overrides for one turn.

    Every field is optional and ``None`` means *keep the agent's own value*.
    That distinction matters more than it looks: a temperature of ``0.0`` is a
    deliberate request for determinism, so treating falsy as unset would
    silently discard it.

    These are a caller's *preferences*, not instructions the runtime is bound
    by. Budget policy still applies afterwards, and a pinned model that cannot
    serve the turn is refused rather than quietly replaced.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_id: str | None = Field(
        default=None,
        description=(
            "Pin the model for this turn. Must be one the catalogue holds; an "
            "unknown or unsuitable model is refused rather than substituted."
        ),
    )
    temperature: float | None = Field(
        default=None,
        ge=0.0,
        le=2.0,
        description="Sampling temperature. Zero is deterministic, not unset.",
    )
    max_output_tokens: int | None = Field(
        default=None,
        gt=0,
        le=32_000,
        description=(
            "Cap on generated tokens. Bounded here as well as by budget "
            "policy, because an unbounded value from an HTTP caller is a bill "
            "anyone can write."
        ),
    )
