"""Memory provider contract.

Memory is a *platform* capability, not an agent capability (``CLAUDE.md``).
Agents talk to this interface; whether it is backed by a dict, Redis, Cosmos DB
or a vector store is a configuration concern.

Operations required by ``architecture.md`` §36: load, save, append, delete,
search, clear, summarize.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.dto.message import Message
from agent_platform_sdk.interfaces.provider import Provider

__all__ = ["MemoryProvider"]


@runtime_checkable
class MemoryProvider(Provider, Protocol):
    """Conversation state storage and retrieval."""

    async def load(self, conversation_id: str, context: ExecutionContext) -> tuple[Message, ...]:
        """Return the stored messages for a conversation, oldest first.

        An unknown conversation returns an empty tuple rather than raising: a
        first message in a new conversation is the normal case, not an error.
        """
        ...

    async def save(
        self,
        conversation_id: str,
        messages: tuple[Message, ...],
        context: ExecutionContext,
    ) -> None:
        """Replace the stored messages for a conversation."""
        ...

    async def append(
        self,
        conversation_id: str,
        message: Message,
        context: ExecutionContext,
    ) -> None:
        """Add a single message to a conversation.

        Separate from :meth:`save` because appending is the hot path and a
        persistent backend can implement it without reading the whole history.
        """
        ...

    async def delete(self, conversation_id: str, context: ExecutionContext) -> None:
        """Remove a conversation entirely.

        Deleting an unknown conversation succeeds — the caller's intent is
        already satisfied.
        """
        ...

    async def search(
        self,
        conversation_id: str,
        query: str,
        limit: int,
        context: ExecutionContext,
    ) -> tuple[Message, ...]:
        """Return messages relevant to ``query``.

        Providers that declare no semantic search may fall back to a documented
        strategy such as recency. Callers must not assume ranking semantics.
        """
        ...

    async def clear(self, context: ExecutionContext) -> None:
        """Remove all conversations held by this provider.

        Intended for local development and tests. Production implementations
        should refuse or gate this behind an explicit permission.
        """
        ...

    async def summarize(
        self,
        conversation_id: str,
        context: ExecutionContext,
    ) -> str | None:
        """Return a condensed form of the conversation, if supported.

        Used to keep long conversations inside a model's context window.
        Returns ``None`` when the provider cannot summarise, which lets the
        runtime fall back to truncation.
        """
        ...
