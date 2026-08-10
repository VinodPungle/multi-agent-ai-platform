"""Conversation listing contract.

What a history sidebar needs to show a conversation without loading it. Kept
separate from the transcript because listing twenty conversations should not
mean transferring twenty full transcripts — the summary is what the list
renders, and the transcript is fetched when one is opened.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["ConversationSummary"]


class ConversationSummary(BaseModel):
    """One conversation, as a list entry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    conversation_id: str
    message_count: int = Field(ge=0)
    preview: str = Field(
        default="",
        description=(
            "Opening words of the first thing the user said. The first user "
            "message rather than the most recent, because a list is scanned to "
            "find a conversation again and people remember how one started."
        ),
    )
