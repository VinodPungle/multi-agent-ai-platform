"""Conversation memory backed by Redis.

The platform's first *durable* memory. Until this, history lived in the
process: it did not survive a restart, a deployment or a scale-to-zero timeout,
and it was not shared between replicas — so a scaled-out deployment could lose a
user's conversation mid-way through it, depending on which instance answered.

That was the largest remaining gap in the deployed platform, and it is the one
users notice.

What changes, and what deliberately does not
    Only the storage. `MemoryProvider` is unchanged, no agent knows this exists,
    and switching between backends is one configuration value. That is the
    property the interface was written for (``CLAUDE.md``, "Memory is a platform
    capability").

Why a list per conversation
    `append` is the hot path — every turn writes two messages — and `RPUSH` is
    O(1) with no read-modify-write. Storing a conversation as one serialised
    blob would make every append a full round trip plus a rewrite, and would
    lose a message whenever two requests for one conversation overlapped.

Expiry rather than eviction
    Each conversation carries a TTL, refreshed on write. An in-process store
    needs an LRU cap because the process's memory is finite and shared with
    everything else; Redis has its own eviction policy and its own memory
    budget, so the platform's job is to say how long a conversation is *worth*
    keeping rather than how many to hold.

Failure posture
    A memory backend that is down must not take chat down with it. Reads
    degrade to empty — the user loses history, which is visible and survivable —
    and writes are logged and swallowed. The alternative is a total outage
    because a cache is unavailable, which is a worse trade for a conversational
    platform than answering without context.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

from redis.asyncio import Redis
from redis.exceptions import RedisError

from agent_platform.memory.session_memory import preview_of
from agent_platform.telemetry.logging import get_logger
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.contracts.health import ComponentHealth
from agent_platform_sdk.dto.conversation import ConversationSummary
from agent_platform_sdk.dto.message import Message
from agent_platform_sdk.types.enums import Capability, HealthStatus

if TYPE_CHECKING:
    from redis.credentials import CredentialProvider

__all__ = ["RedisConversationMemoryProvider"]

_logger = get_logger(__name__)

#: Prefix for every key this provider owns, so a shared Redis instance can be
#: inspected — and cleared — without guessing which keys belong to the platform.
_KEY_PREFIX = "maap:conversation:"


class RedisConversationMemoryProvider:
    """Durable conversation history, shared across replicas.

    Satisfies :class:`~agent_platform_sdk.interfaces.memory_provider.MemoryProvider`
    structurally — it inherits nothing, per ADR-0004.
    """

    def __init__(
        self,
        url: str,
        provider_id: str = "redis-memory",
        ttl_seconds: int = 86_400,
        max_messages_per_conversation: int = 100,
        client: Redis | None = None,
        credential_provider: object | None = None,
    ) -> None:
        """Create the provider.

        Args:
            url: Redis connection URL, e.g. ``rediss://host:6380``. Contains
                credentials when the deployment uses an access key, which is why
                it is a `SecretStr` in configuration and never logged here.
            provider_id: Identifier it registers under.
            ttl_seconds: How long a conversation survives without a write.
                A day by default: long enough that a user returning after lunch
                keeps their thread, short enough that abandoned conversations do
                not accumulate indefinitely.
            max_messages_per_conversation: Messages retained per conversation.
                A cap is mandatory, not tuning — an unbounded list fed by an
                HTTP endpoint lets anyone who can send requests exhaust the
                store, and every message is also context spent on the next
                prompt.
            client: Injected client, so tests exercise the whole provider
                without a server and without patching a global.
            credential_provider: Supplies credentials on every connect. When
                set, the URL carries no password and authentication is by Entra
                token — see
                :mod:`agent_platform.memory.entra_credentials`. ``None`` means
                the URL is the whole story, which is the local and Compose case.

                Typed ``object`` rather than redis-py's ``CredentialProvider``
                because that class is a concrete base, and importing it here to
                use it as a type would make the provider claim a dependency it
                only forwards.
        """
        self._url = url
        self._provider_id = provider_id
        self._ttl_seconds = ttl_seconds
        self._max_messages = max_messages_per_conversation
        self._client = client
        self._owns_client = client is None
        self._credential_provider = credential_provider

    @property
    def provider_id(self) -> str:
        """Identifier this provider is registered under."""
        return self._provider_id

    # -- Lifecycle ---------------------------------------------------------

    async def initialize(self) -> None:
        """Open the connection pool.

        Deliberately does not ping. A memory backend that is briefly
        unreachable must not stop the platform from starting — chat degrades to
        no history, which is survivable, whereas refusing to boot is not.
        Reachability is reported by :meth:`health_check`.
        """
        if self._client is None:
            self._client = Redis.from_url(
                self._url,
                # Strings in, strings out. The alternative is decoding bytes at
                # every call site, and one missed decode is a message rendered
                # as b'...' to a user.
                decode_responses=True,
                socket_timeout=5.0,
                socket_connect_timeout=5.0,
                # A read that hangs holds a chat turn open for as long as the
                # server cares to take.
                retry_on_timeout=True,
                # Also what makes Entra tokens rotate: an expired token closes
                # the connection, and the next health check reconnects, which
                # asks the credential provider for a fresh one.
                health_check_interval=30,
                # `None` is the default, so the un-authenticated local case is
                # unaffected. The cast states the structural claim explicitly:
                # redis-py only ever calls `get_credentials_async`, and this
                # provider deliberately inherits nothing (ADR-0004).
                credential_provider=cast(
                    "CredentialProvider | None",
                    self._credential_provider,
                ),
            )

        _logger.info(
            "memory.initialized",
            provider_id=self._provider_id,
            ttl_seconds=self._ttl_seconds,
            max_messages=self._max_messages,
            auth="entra" if self._credential_provider is not None else "url",
            # No URL: it may carry a password.
            detail="Redis conversation memory. Durable and shared across replicas.",
        )

    async def close(self) -> None:
        """Close the connection pool, if this provider opened it."""
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    def supports(self, capability: Capability) -> bool:
        """Declare nothing. Storage is not a model capability."""
        del capability
        return False

    async def health_check(self) -> ComponentHealth:
        """Report reachability.

        This one *does* probe, unlike the model provider's. A `PING` is cheap
        and unbilled, and the failure it detects — a memory backend that is
        gone — is otherwise invisible until a user notices their conversation
        has no history.
        """
        if self._client is None:
            return ComponentHealth(
                name=self._provider_id,
                status=HealthStatus.UNKNOWN,
                detail="Not initialised.",
            )

        try:
            await self._client.ping()
        except (RedisError, OSError) as error:
            # DEGRADED, not UNHEALTHY: chat still works without history, so this
            # instance should keep serving traffic. Reporting unhealthy would
            # fail readiness and remove a replica that can still answer.
            return ComponentHealth(
                name=self._provider_id,
                status=HealthStatus.DEGRADED,
                detail=(
                    f"Redis unreachable ({type(error).__name__}). Conversations "
                    f"will not persist; chat continues without history."
                ),
            )

        return ComponentHealth(
            name=self._provider_id,
            status=HealthStatus.HEALTHY,
            detail=f"Redis reachable. TTL {self._ttl_seconds}s, {self._max_messages} messages max.",
        )

    # -- Memory ------------------------------------------------------------

    async def load(self, conversation_id: str, context: ExecutionContext) -> tuple[Message, ...]:
        """Return the stored messages, oldest first.

        An unreachable backend returns empty rather than raising: the user loses
        history, which they can see and work around, instead of losing the turn.
        """
        client = self._client
        if client is None:
            return ()

        try:
            raw = await client.lrange(self._key(conversation_id), 0, -1)
        except (RedisError, OSError) as error:
            self._log_degraded("load", error, context)
            return ()

        return tuple(message for item in raw if (message := self._decode(item)) is not None)

    async def save(
        self,
        conversation_id: str,
        messages: tuple[Message, ...],
        context: ExecutionContext,
    ) -> None:
        """Replace the stored messages for a conversation."""
        client = self._client
        if client is None:
            return

        key = self._key(conversation_id)
        kept = messages[-self._max_messages :]

        try:
            # A pipeline, so a reader never observes the window between the
            # delete and the write — which would look like a conversation that
            # had lost its history.
            async with client.pipeline(transaction=True) as pipe:
                pipe.delete(key)
                if kept:
                    pipe.rpush(key, *[self._encode(message) for message in kept])
                    pipe.expire(key, self._ttl_seconds)
                await pipe.execute()
        except (RedisError, OSError) as error:
            self._log_degraded("save", error, context)

    async def append(
        self,
        conversation_id: str,
        message: Message,
        context: ExecutionContext,
    ) -> None:
        """Add one message.

        The hot path: `RPUSH` plus `LTRIM` is O(1) amortised and needs no read,
        so two concurrent turns on one conversation cannot lose a message the
        way a read-modify-write would.
        """
        client = self._client
        if client is None:
            return

        key = self._key(conversation_id)

        try:
            async with client.pipeline(transaction=True) as pipe:
                pipe.rpush(key, self._encode(message))
                # Trim to the newest N. Negative indices count from the end, so
                # this keeps the tail and drops the oldest.
                pipe.ltrim(key, -self._max_messages, -1)
                # Refreshed on every write: a conversation being used should not
                # expire because it started a day ago.
                pipe.expire(key, self._ttl_seconds)
                await pipe.execute()
        except (RedisError, OSError) as error:
            self._log_degraded("append", error, context)

    async def delete(self, conversation_id: str, context: ExecutionContext) -> None:
        """Remove a conversation. Deleting an unknown one succeeds."""
        client = self._client
        if client is None:
            return

        try:
            await client.delete(self._key(conversation_id))
        except (RedisError, OSError) as error:
            self._log_degraded("delete", error, context)

    async def search(
        self,
        conversation_id: str,
        query: str,
        limit: int,
        context: ExecutionContext,
    ) -> tuple[Message, ...]:
        """Return the most recent messages, ignoring ``query``.

        Recency, not relevance, and the contract permits exactly this: "providers
        that declare no semantic search may fall back to a documented strategy".
        Documented here rather than implied — a caller expecting ranking would
        otherwise silently get chronology.

        Semantic search needs an embedding provider and a vector index. When
        those exist, this becomes a different provider rather than a flag on
        this one.
        """
        del query
        messages = await self.load(conversation_id, context)
        return messages[-limit:] if limit > 0 else ()

    async def list_conversations(
        self,
        context: ExecutionContext,
        limit: int = 50,
    ) -> tuple[ConversationSummary, ...]:
        """Return conversations this provider holds.

        **Not ordered by recency**, and the contract permits that. Redis keys
        have no creation time, and `SCAN` returns them in whatever order the
        keyspace happens to yield — so ordering would need a sorted set
        maintained on every write, which is a second thing to keep correct for
        a sidebar. When history ordering matters more than it does today, that
        index is the change; until then this is honest about what it gives.

        Bounded by `limit` while scanning rather than after, because a shared
        instance may hold far more conversations than a list wants and reading
        every one of them to show twenty is the kind of query that is fine
        until it is not.
        """
        client = self._client
        if client is None:
            return ()

        summaries: list[ConversationSummary] = []

        try:
            async for key in client.scan_iter(match=f"{_KEY_PREFIX}*", count=100):
                if len(summaries) >= limit:
                    break
                conversation_id = _conversation_id_of(key)
                messages = await self.load(conversation_id, context)
                if not messages:
                    continue
                summaries.append(
                    ConversationSummary(
                        conversation_id=conversation_id,
                        message_count=len(messages),
                        preview=preview_of(messages),
                    )
                )
        except (RedisError, OSError) as error:
            self._log_degraded("list_conversations", error, context)
            return ()

        return tuple(summaries)

    async def clear(self, context: ExecutionContext) -> None:
        """Remove every conversation this provider owns.

        Scans by key prefix rather than `FLUSHDB`, which would delete another
        application's data from a shared instance. `SCAN` rather than `KEYS`,
        which blocks the server for the duration on a large keyspace.
        """
        client = self._client
        if client is None:
            return

        try:
            async for key in client.scan_iter(match=f"{_KEY_PREFIX}*", count=100):
                await client.delete(key)
        except (RedisError, OSError) as error:
            self._log_degraded("clear", error, context)

    async def summarize(self, conversation_id: str, context: ExecutionContext) -> str | None:
        """Not supported.

        Summarising means calling a model, and a memory provider that called one
        would couple storage to inference and spend tokens nobody asked for.
        Returning ``None`` is the contract's signal for "fall back to
        truncation", which is what the runtime already does.
        """
        del conversation_id, context
        return None

    # -- Internals ---------------------------------------------------------

    @staticmethod
    def _key(conversation_id: str) -> str:
        """Namespace a conversation id, so a shared instance stays inspectable."""
        return f"{_KEY_PREFIX}{conversation_id}"

    @staticmethod
    def _encode(message: Message) -> str:
        """Serialise a message for storage."""
        return message.model_dump_json()

    @staticmethod
    def _decode(raw: bytes | str) -> Message | None:
        """Parse a stored message, tolerating one that cannot be read.

        A message written by an older version of the schema, or corrupted, is
        skipped rather than raising. Losing one message from a history is a
        degraded answer; raising here loses the whole conversation and the turn
        with it.
        """
        try:
            # `decode_responses=True` means this is a `str` in practice, but the
            # client's type says otherwise and a mis-set option would produce
            # bytes silently. Handling both costs a line and removes the
            # possibility of a message rendered as b'...' to a user.
            text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            return Message.model_validate(json.loads(text))
        except (ValueError, TypeError, UnicodeDecodeError):
            _logger.warning(
                "memory.message_unreadable",
                detail="A stored message could not be parsed and was skipped.",
            )
            return None

    def _log_degraded(self, operation: str, error: Exception, context: ExecutionContext) -> None:
        """Record a backend failure without failing the turn."""
        _logger.warning(
            "memory.degraded",
            operation=operation,
            error_type=type(error).__name__,
            detail="Conversation memory is unavailable; the turn continues without it.",
            **context.to_log_fields(),
        )

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"RedisConversationMemoryProvider(ttl={self._ttl_seconds}s)"


def _conversation_id_of(key: str | bytes) -> str:
    """Strip the namespace prefix from a stored key."""
    text = key.decode("utf-8") if isinstance(key, bytes) else key
    return text.removeprefix(_KEY_PREFIX)
