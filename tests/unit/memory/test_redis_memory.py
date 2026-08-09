"""Durable conversation memory.

Driven through `fakeredis`, which implements the Redis command set in-process:
no server, no container, no network. That matters because these tests must pass
in CI and on a laptop that has never installed Redis.

The failure tests are the important ones. A memory backend that is down must not
take chat down with it, and that behaviour only ever runs when something is
already wrong — which is exactly when nobody is watching.
"""

from __future__ import annotations

from typing import Any

import pytest
from fakeredis.aioredis import FakeRedis
from redis.exceptions import ConnectionError as RedisConnectionError

from agent_platform.memory.redis_memory import RedisConversationMemoryProvider
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.dto.message import Message
from agent_platform_sdk.interfaces.memory_provider import MemoryProvider
from agent_platform_sdk.types.enums import HealthStatus, MessageRole

pytestmark = pytest.mark.unit

CONTEXT = ExecutionContext()
CONVERSATION = "conversation-1"


def build_provider(**overrides: Any) -> RedisConversationMemoryProvider:  # noqa: ANN401
    fields: dict[str, Any] = {
        "url": "redis://localhost:6379",
        "client": FakeRedis(decode_responses=True),
    }
    fields.update(overrides)
    return RedisConversationMemoryProvider(**fields)


def a_message(content: str, role: MessageRole = MessageRole.USER) -> Message:
    return Message(role=role, content=content)


class TestContractConformance:
    def test_it_satisfies_the_memory_contract(self) -> None:
        assert isinstance(build_provider(), MemoryProvider)


class TestPersistence:
    async def test_an_appended_message_is_returned(self) -> None:
        provider = build_provider()
        await provider.initialize()

        await provider.append(CONVERSATION, a_message("hello"), CONTEXT)
        loaded = await provider.load(CONVERSATION, CONTEXT)

        assert [message.content for message in loaded] == ["hello"]

    async def test_order_is_preserved(self) -> None:
        """History read out of order is worse than no history."""
        provider = build_provider()
        await provider.initialize()

        for text in ("first", "second", "third"):
            await provider.append(CONVERSATION, a_message(text), CONTEXT)

        loaded = await provider.load(CONVERSATION, CONTEXT)

        assert [message.content for message in loaded] == ["first", "second", "third"]

    async def test_roles_survive_the_round_trip(self) -> None:
        provider = build_provider()
        await provider.initialize()

        await provider.append(CONVERSATION, a_message("q", MessageRole.USER), CONTEXT)
        await provider.append(CONVERSATION, a_message("a", MessageRole.ASSISTANT), CONTEXT)

        loaded = await provider.load(CONVERSATION, CONTEXT)

        assert [message.role for message in loaded] == [
            MessageRole.USER,
            MessageRole.ASSISTANT,
        ]

    async def test_conversations_do_not_leak_into_each_other(self) -> None:
        provider = build_provider()
        await provider.initialize()

        await provider.append("conversation-a", a_message("mine"), CONTEXT)
        await provider.append("conversation-b", a_message("theirs"), CONTEXT)

        loaded = await provider.load("conversation-a", CONTEXT)

        assert [message.content for message in loaded] == ["mine"]

    async def test_an_unknown_conversation_is_empty_not_an_error(self) -> None:
        """A first message in a new conversation is the normal case."""
        provider = build_provider()
        await provider.initialize()

        assert await provider.load("never-seen", CONTEXT) == ()

    async def test_save_replaces_rather_than_appends(self) -> None:
        provider = build_provider()
        await provider.initialize()
        await provider.append(CONVERSATION, a_message("old"), CONTEXT)

        await provider.save(CONVERSATION, (a_message("new"),), CONTEXT)

        loaded = await provider.load(CONVERSATION, CONTEXT)
        assert [message.content for message in loaded] == ["new"]

    async def test_saving_nothing_empties_the_conversation(self) -> None:
        provider = build_provider()
        await provider.initialize()
        await provider.append(CONVERSATION, a_message("old"), CONTEXT)

        await provider.save(CONVERSATION, (), CONTEXT)

        assert await provider.load(CONVERSATION, CONTEXT) == ()


class TestBounds:
    async def test_a_conversation_is_capped(self) -> None:
        """An unbounded list fed by an HTTP endpoint is a way to exhaust the store."""
        provider = build_provider(max_messages_per_conversation=3)
        await provider.initialize()

        for index in range(10):
            await provider.append(CONVERSATION, a_message(f"message {index}"), CONTEXT)

        loaded = await provider.load(CONVERSATION, CONTEXT)

        assert len(loaded) == 3

    async def test_the_cap_keeps_the_newest(self) -> None:
        """Dropping the recent end would discard the context that matters most."""
        provider = build_provider(max_messages_per_conversation=2)
        await provider.initialize()

        for index in range(5):
            await provider.append(CONVERSATION, a_message(f"message {index}"), CONTEXT)

        loaded = await provider.load(CONVERSATION, CONTEXT)

        assert [message.content for message in loaded] == ["message 3", "message 4"]

    async def test_save_also_respects_the_cap(self) -> None:
        provider = build_provider(max_messages_per_conversation=2)
        await provider.initialize()

        await provider.save(
            CONVERSATION,
            tuple(a_message(f"m{index}") for index in range(5)),
            CONTEXT,
        )

        assert len(await provider.load(CONVERSATION, CONTEXT)) == 2

    async def test_a_ttl_is_set_and_refreshed(self) -> None:
        """A conversation in active use must not expire because it started yesterday."""
        client = FakeRedis(decode_responses=True)
        provider = build_provider(client=client, ttl_seconds=120)
        await provider.initialize()

        await provider.append(CONVERSATION, a_message("first"), CONTEXT)
        ttl = await client.ttl("maap:conversation:conversation-1")

        assert 0 < ttl <= 120


class TestDeletion:
    async def test_a_conversation_can_be_deleted(self) -> None:
        provider = build_provider()
        await provider.initialize()
        await provider.append(CONVERSATION, a_message("hello"), CONTEXT)

        await provider.delete(CONVERSATION, CONTEXT)

        assert await provider.load(CONVERSATION, CONTEXT) == ()

    async def test_deleting_an_unknown_conversation_succeeds(self) -> None:
        """The caller's intent is already satisfied."""
        provider = build_provider()
        await provider.initialize()

        await provider.delete("never-seen", CONTEXT)

    async def test_clear_removes_only_this_platforms_keys(self) -> None:
        """`FLUSHDB` would delete another application's data from a shared instance."""
        client = FakeRedis(decode_responses=True)
        provider = build_provider(client=client)
        await provider.initialize()
        await provider.append(CONVERSATION, a_message("ours"), CONTEXT)
        await client.set("someone-elses-key", "theirs")

        await provider.clear(CONTEXT)

        assert await provider.load(CONVERSATION, CONTEXT) == ()
        assert await client.get("someone-elses-key") == "theirs"


class TestSearchAndSummary:
    async def test_search_returns_the_most_recent(self) -> None:
        """Recency, not relevance — and the contract permits exactly that."""
        provider = build_provider()
        await provider.initialize()
        for index in range(5):
            await provider.append(CONVERSATION, a_message(f"m{index}"), CONTEXT)

        found = await provider.search(CONVERSATION, "anything", 2, CONTEXT)

        assert [message.content for message in found] == ["m3", "m4"]

    async def test_summarize_declines_rather_than_calling_a_model(self) -> None:
        """A memory provider that called a model would couple storage to inference."""
        provider = build_provider()
        await provider.initialize()

        assert await provider.summarize(CONVERSATION, CONTEXT) is None


class TestDegradedOperation:
    """A memory backend that is down must not take chat down with it."""

    class BrokenClient:
        """Fails every operation, the way an unreachable server does."""

        async def lrange(self, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
            raise RedisConnectionError("unreachable")

        async def delete(self, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
            raise RedisConnectionError("unreachable")

        async def ping(self) -> Any:  # noqa: ANN401
            raise RedisConnectionError("unreachable")

        def pipeline(self, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
            raise RedisConnectionError("unreachable")

        def scan_iter(self, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
            raise RedisConnectionError("unreachable")

        async def aclose(self) -> None:
            return None

    async def test_a_read_degrades_to_empty(self) -> None:
        """The user loses history — visible and survivable — rather than the turn."""
        provider = build_provider(client=self.BrokenClient())

        assert await provider.load(CONVERSATION, CONTEXT) == ()

    async def test_a_write_does_not_raise(self) -> None:
        provider = build_provider(client=self.BrokenClient())

        await provider.append(CONVERSATION, a_message("hello"), CONTEXT)
        await provider.save(CONVERSATION, (a_message("hello"),), CONTEXT)
        await provider.delete(CONVERSATION, CONTEXT)
        await provider.clear(CONTEXT)

    async def test_health_reports_degraded_not_unhealthy(self) -> None:
        """Unhealthy would fail readiness and remove a replica that can still answer."""
        provider = build_provider(client=self.BrokenClient())

        health = await provider.health_check()

        assert health.status is HealthStatus.DEGRADED
        assert "chat continues" in (health.detail or "")

    async def test_an_unreadable_message_is_skipped_not_fatal(self) -> None:
        """Losing one message is degraded; raising loses the conversation and the turn."""
        client = FakeRedis(decode_responses=True)
        provider = build_provider(client=client)
        await provider.initialize()

        await provider.append(CONVERSATION, a_message("good"), CONTEXT)
        await client.rpush("maap:conversation:conversation-1", "{not valid json")

        loaded = await provider.load(CONVERSATION, CONTEXT)

        assert [message.content for message in loaded] == ["good"]


class TestHealth:
    async def test_a_reachable_backend_is_healthy(self) -> None:
        provider = build_provider()
        await provider.initialize()

        assert (await provider.health_check()).status is HealthStatus.HEALTHY

    async def test_health_is_unknown_before_initialisation(self) -> None:
        provider = RedisConversationMemoryProvider(url="redis://localhost:6379")

        assert (await provider.health_check()).status is HealthStatus.UNKNOWN

    async def test_the_url_never_appears_in_logs(self, caplog: pytest.LogCaptureFixture) -> None:
        """It carries the password when a deployment authenticates with a key."""
        provider = build_provider(url="redis://user:hunter2@example.com:6379")

        with caplog.at_level("DEBUG"):
            await provider.initialize()

        assert "hunter2" not in caplog.text
