"""In-process conversation memory.

The first :class:`~agent_platform_sdk.interfaces.memory_provider.MemoryProvider`
implementation. It holds conversations in a dictionary, which is exactly what
Milestone 02 needs — memory that survives a page navigation and is gone on
restart — and exactly what production must not use.

Its two limits are properties of the design, not gaps to fill in later:

**Bound to one process.** Two replicas do not share it. A conversation is
answered correctly only while requests land on the same instance, so this
provider must never be enabled behind a load balancer. Redis and Cosmos DB
implementations replace it by configuration, with no change to any caller.

**Bounded on purpose.** Both the number of conversations and the messages per
conversation are capped. An unbounded dictionary fed by an HTTP endpoint is a
memory-exhaustion vector: anyone able to send requests can allocate until the
process dies. Eviction is least-recently-used, so an active conversation is
never dropped in favour of an abandoned one.

Concurrency
    Every mutation happens under an :class:`asyncio.Lock`. The operations look
    atomic in Python, but each is a read-modify-write across an ``await``, and
    two requests for the same conversation interleave there. Without the lock,
    a concurrent append and load can drop a message.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict

from agent_platform.telemetry.logging import get_logger
from agent_platform.telemetry.tracing import get_tracer
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.contracts.health import ComponentHealth
from agent_platform_sdk.dto.message import Message
from agent_platform_sdk.types.enums import Capability, HealthStatus

__all__ = ["InMemorySessionMemoryProvider"]

_logger = get_logger(__name__)
_tracer = get_tracer(__name__)


class InMemorySessionMemoryProvider:
    """Conversation storage in a bounded, process-local dictionary.

    Satisfies :class:`MemoryProvider` structurally.
    """

    def __init__(
        self,
        provider_id: str = "session-memory",
        max_conversations: int = 500,
        max_messages_per_conversation: int = 200,
    ) -> None:
        """Create the provider.

        Args:
            provider_id: Identifier it registers under.
            max_conversations: Cap on concurrently held conversations. The
                least recently used is evicted beyond this.
            max_messages_per_conversation: Cap on messages in one conversation.
                The oldest are dropped first, which is also what keeps a long
                conversation inside a model's context window.
        """
        self._provider_id = provider_id
        self._max_conversations = max_conversations
        self._max_messages = max_messages_per_conversation

        # `OrderedDict` rather than `dict`: eviction needs an explicit
        # recency order, and `move_to_end` makes that O(1).
        self._conversations: OrderedDict[str, list[Message]] = OrderedDict()
        self._lock = asyncio.Lock()

    # -- Provider ----------------------------------------------------------

    @property
    def provider_id(self) -> str:
        """Identifier this provider is registered under."""
        return self._provider_id

    async def initialize(self) -> None:
        """No resources to acquire."""
        _logger.info(
            "memory.initialized",
            provider_id=self._provider_id,
            max_conversations=self._max_conversations,
            max_messages_per_conversation=self._max_messages,
            detail="In-process memory. Not shared between replicas.",
        )

    async def health_check(self) -> ComponentHealth:
        """Report occupancy.

        Always healthy — a dictionary cannot be unreachable — but the detail
        carries the conversation count, which is the number an operator wants
        when a process is using more memory than expected.
        """
        async with self._lock:
            occupancy = len(self._conversations)

        return ComponentHealth(
            name=self._provider_id,
            status=HealthStatus.HEALTHY,
            detail=f"{occupancy}/{self._max_conversations} conversations held in process",
        )

    def supports(self, capability: Capability) -> bool:
        """Declare nothing. This provider has no semantic search or summarisation."""
        del capability
        return False

    async def close(self) -> None:
        """Drop every conversation.

        Called during graceful shutdown. The data is process-local and about to
        be lost anyway; clearing explicitly means a restarted worker in the same
        process cannot observe a previous run's conversations.
        """
        async with self._lock:
            self._conversations.clear()

    # -- Memory ------------------------------------------------------------

    async def load(self, conversation_id: str, context: ExecutionContext) -> tuple[Message, ...]:
        """Return the stored messages, oldest first.

        An unknown conversation returns an empty tuple: the first message of a
        new conversation is the normal case, not an error.
        """
        del context

        async with self._lock:
            messages = self._conversations.get(conversation_id)
            if messages is None:
                return ()
            # Reading counts as use, or an actively read conversation would be
            # evicted while an idle one that was written once survives.
            self._conversations.move_to_end(conversation_id)
            return tuple(messages)

    async def save(
        self,
        conversation_id: str,
        messages: tuple[Message, ...],
        context: ExecutionContext,
    ) -> None:
        """Replace the stored messages for a conversation."""
        del context

        async with self._lock:
            self._conversations[conversation_id] = list(messages)[-self._max_messages :]
            self._conversations.move_to_end(conversation_id)
            self._evict_if_needed()

    async def append(
        self,
        conversation_id: str,
        message: Message,
        context: ExecutionContext,
    ) -> None:
        """Add one message to a conversation, creating it if absent."""
        del context

        with _tracer.start_as_current_span("memory.append") as span:
            span.set_attribute("memory.provider_id", self._provider_id)

            async with self._lock:
                messages = self._conversations.setdefault(conversation_id, [])
                messages.append(message)

                if len(messages) > self._max_messages:
                    dropped = len(messages) - self._max_messages
                    del messages[:dropped]
                    _logger.info(
                        "memory.truncated",
                        conversation_id=conversation_id,
                        dropped_messages=dropped,
                        detail="Oldest messages dropped; the conversation exceeded its cap.",
                    )

                self._conversations.move_to_end(conversation_id)
                self._evict_if_needed()

                span.set_attribute("memory.message_count", len(messages))

    async def delete(self, conversation_id: str, context: ExecutionContext) -> None:
        """Remove a conversation. Deleting an unknown one succeeds."""
        del context

        async with self._lock:
            self._conversations.pop(conversation_id, None)

    async def search(
        self,
        conversation_id: str,
        query: str,
        limit: int,
        context: ExecutionContext,
    ) -> tuple[Message, ...]:
        """Return messages containing ``query``, most recent first.

        Substring matching, not semantic search, and the interface documents
        that callers must not assume ranking semantics. A provider that claimed
        relevance ranking it does not have would be worse than one that is
        explicit about matching literally.
        """
        del context

        needle = query.casefold()
        async with self._lock:
            messages = self._conversations.get(conversation_id, [])
            matches = [
                message for message in reversed(messages) if needle in message.content.casefold()
            ]
        return tuple(matches[:limit])

    async def clear(self, context: ExecutionContext) -> None:
        """Remove every conversation held by this provider.

        Intended for local development and tests. A persistent implementation
        must gate this behind an explicit permission; here the data is
        process-local and disposable by construction.
        """
        del context

        async with self._lock:
            count = len(self._conversations)
            self._conversations.clear()

        _logger.warning("memory.cleared", conversation_count=count)

    async def summarize(self, conversation_id: str, context: ExecutionContext) -> str | None:
        """Return ``None``: this provider cannot summarise.

        Summarising requires a model call, which would make memory depend on
        inference and invert the layering. The runtime falls back to truncation,
        which is what the message cap already does.
        """
        del conversation_id, context
        return None

    # -- Internals ---------------------------------------------------------

    def _evict_if_needed(self) -> None:
        """Drop least-recently-used conversations until the cap is respected.

        Caller must hold the lock.
        """
        while len(self._conversations) > self._max_conversations:
            evicted_id, _ = self._conversations.popitem(last=False)
            _logger.info(
                "memory.evicted",
                conversation_id=evicted_id,
                detail="Least recently used conversation dropped; provider at capacity.",
            )
