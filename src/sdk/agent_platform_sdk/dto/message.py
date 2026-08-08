"""Conversation message contracts.

Provider-neutral by design: every provider translates these into its own wire
format inside `agent_platform.providers`, so business logic never sees a vendor
message shape.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from agent_platform_sdk.types.enums import MessageRole

__all__ = ["Message", "ToolCall"]


class ToolCall(BaseModel):
    """A model's request to invoke a tool.

    Arguments are carried as a raw string rather than a parsed object because
    models emit malformed JSON often enough that parsing must be a validation
    step the runtime controls, not an implicit part of deserialisation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    call_id: str = Field(description="Provider-assigned id, used to correlate the result.")
    tool_id: str = Field(description="Identifier of the tool in the tool registry.")
    arguments: str = Field(description="Raw JSON arguments as emitted by the model.")


class Message(BaseModel):
    """A single message in a conversation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: MessageRole = Field(description="Author of the message.")
    content: str = Field(description="Text content. May be empty when tool calls are present.")
    name: str | None = Field(
        default=None,
        description="Optional author name, used by some providers for multi-participant chats.",
    )
    tool_calls: tuple[ToolCall, ...] = Field(
        default=(),
        description="Tool invocations requested by an assistant message.",
    )
    tool_call_id: str | None = Field(
        default=None,
        description="For a tool-role message, the ToolCall.call_id this responds to.",
    )
