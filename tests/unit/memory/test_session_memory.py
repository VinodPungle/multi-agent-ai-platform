"""Session memory behaviour.

Memory is where a chat platform loses data quietly. A dropped message does not
raise; it produces an answer that ignores what the user just said, which looks
like a model problem and is not. These tests pin the cases where that happens:
eviction, truncation, and concurrent writes to one conversation.
"""

from __future__ import annotations

import asyncio

import pytest

from agent_platform.memory.session_memory import InMemorySessionMemoryProvider
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.dto.message import Message
from agent_platform_sdk.interfaces.memory_provider import MemoryProvider
from agent_platform_sdk.types.enums import Capability, HealthStatus, MessageRole

pytestmark = pytest.mark.unit

CONTEXT = ExecutionContext()


def user(content: str) -> Message:
    """Build a user message."""
    return Message(role=MessageRole.USER, content=content)


def assistant(content: str) -> Message:
    """Build an assistant message."""
    return Message(role=MessageRole.ASSISTANT, content=content)


@pytest.fixture
def memory() -> InMemorySessionMemoryProvider:
    return InMemorySessionMemoryProvider()


class TestContractConformance:
    def test_it_satisfies_the_memory_contract(self, memory: InMemorySessionMemoryProvider) -> None:
        assert isinstance(memory, MemoryProvider)

    def test_it_declares_no_capabilities(self, memory: InMemorySessionMemoryProvider) -> None:
        """It has neither semantic search nor summarisation, and must not claim them."""
        assert all(not memory.supports(capability) for capability in Capability)

    async def test_health_reports_occupancy(self, memory: InMemorySessionMemoryProvider) -> None:
        await memory.append("c1", user("hello"), CONTEXT)

        health = await memory.health_check()

        assert health.status is HealthStatus.HEALTHY
        assert "1/" in (health.detail or "")


class TestStorage:
    async def test_an_unknown_conversation_is_empty_not_an_error(
        self, memory: InMemorySessionMemoryProvider
    ) -> None:
        """A first message in a new conversation is the normal case."""
        assert await memory.load("never-seen", CONTEXT) == ()

    async def test_appended_messages_come_back_in_order(
        self, memory: InMemorySessionMemoryProvider
    ) -> None:
        await memory.append("c1", user("first"), CONTEXT)
        await memory.append("c1", assistant("second"), CONTEXT)
        await memory.append("c1", user("third"), CONTEXT)

        loaded = await memory.load("c1", CONTEXT)

        assert [message.content for message in loaded] == ["first", "second", "third"]

    async def test_conversations_are_isolated(self, memory: InMemorySessionMemoryProvider) -> None:
        await memory.append("c1", user("one"), CONTEXT)
        await memory.append("c2", user("two"), CONTEXT)

        assert len(await memory.load("c1", CONTEXT)) == 1
        assert len(await memory.load("c2", CONTEXT)) == 1

    async def test_save_replaces_rather_than_appends(
        self, memory: InMemorySessionMemoryProvider
    ) -> None:
        await memory.append("c1", user("original"), CONTEXT)

        await memory.save("c1", (user("replacement"),), CONTEXT)

        loaded = await memory.load("c1", CONTEXT)
        assert [message.content for message in loaded] == ["replacement"]

    async def test_the_returned_history_is_a_snapshot(
        self, memory: InMemorySessionMemoryProvider
    ) -> None:
        """A caller holding a history must not see later writes appear inside it."""
        await memory.append("c1", user("one"), CONTEXT)
        snapshot = await memory.load("c1", CONTEXT)

        await memory.append("c1", user("two"), CONTEXT)

        assert len(snapshot) == 1

    async def test_deleting_an_unknown_conversation_succeeds(
        self, memory: InMemorySessionMemoryProvider
    ) -> None:
        """The caller's intent is already satisfied."""
        await memory.delete("never-seen", CONTEXT)

    async def test_delete_removes_the_conversation(
        self, memory: InMemorySessionMemoryProvider
    ) -> None:
        await memory.append("c1", user("hello"), CONTEXT)

        await memory.delete("c1", CONTEXT)

        assert await memory.load("c1", CONTEXT) == ()

    async def test_clear_removes_every_conversation(
        self, memory: InMemorySessionMemoryProvider
    ) -> None:
        await memory.append("c1", user("one"), CONTEXT)
        await memory.append("c2", user("two"), CONTEXT)

        await memory.clear(CONTEXT)

        assert await memory.load("c1", CONTEXT) == ()
        assert await memory.load("c2", CONTEXT) == ()


class TestBounds:
    """An unbounded store fed by an HTTP endpoint is a memory-exhaustion vector."""

    async def test_a_conversation_is_truncated_to_its_cap(self) -> None:
        memory = InMemorySessionMemoryProvider(max_messages_per_conversation=3)

        for index in range(5):
            await memory.append("c1", user(f"message {index}"), CONTEXT)

        loaded = await memory.load("c1", CONTEXT)

        assert len(loaded) == 3
        # The oldest go, so the most recent context survives.
        assert [message.content for message in loaded] == ["message 2", "message 3", "message 4"]

    async def test_save_also_respects_the_message_cap(self) -> None:
        memory = InMemorySessionMemoryProvider(max_messages_per_conversation=2)

        await memory.save("c1", tuple(user(str(index)) for index in range(5)), CONTEXT)

        assert len(await memory.load("c1", CONTEXT)) == 2

    async def test_the_least_recently_used_conversation_is_evicted(self) -> None:
        memory = InMemorySessionMemoryProvider(max_conversations=2)

        await memory.append("oldest", user("a"), CONTEXT)
        await memory.append("middle", user("b"), CONTEXT)
        await memory.append("newest", user("c"), CONTEXT)

        assert await memory.load("oldest", CONTEXT) == ()
        assert len(await memory.load("middle", CONTEXT)) == 1
        assert len(await memory.load("newest", CONTEXT)) == 1

    async def test_reading_a_conversation_protects_it_from_eviction(self) -> None:
        """An actively read conversation must outlive one that was written once."""
        memory = InMemorySessionMemoryProvider(max_conversations=2)

        await memory.append("first", user("a"), CONTEXT)
        await memory.append("second", user("b"), CONTEXT)

        # Touching `first` makes `second` the least recently used.
        await memory.load("first", CONTEXT)
        await memory.append("third", user("c"), CONTEXT)

        assert len(await memory.load("first", CONTEXT)) == 1
        assert await memory.load("second", CONTEXT) == ()


class TestConcurrency:
    """Every operation is a read-modify-write across an await."""

    async def test_concurrent_appends_to_one_conversation_all_survive(
        self, memory: InMemorySessionMemoryProvider
    ) -> None:
        await asyncio.gather(
            *(memory.append("c1", user(f"message {index}"), CONTEXT) for index in range(50))
        )

        assert len(await memory.load("c1", CONTEXT)) == 50

    async def test_concurrent_writes_to_different_conversations_do_not_interfere(
        self, memory: InMemorySessionMemoryProvider
    ) -> None:
        await asyncio.gather(
            *(memory.append(f"c{index}", user("hello"), CONTEXT) for index in range(20))
        )

        for index in range(20):
            assert len(await memory.load(f"c{index}", CONTEXT)) == 1


class TestSearchAndSummary:
    async def test_search_matches_content_case_insensitively(
        self, memory: InMemorySessionMemoryProvider
    ) -> None:
        await memory.append("c1", user("The Eiffel Tower is in Paris"), CONTEXT)
        await memory.append("c1", assistant("Correct."), CONTEXT)

        matches = await memory.search("c1", "eiffel", 10, CONTEXT)

        assert len(matches) == 1

    async def test_search_returns_the_most_recent_matches_first(
        self, memory: InMemorySessionMemoryProvider
    ) -> None:
        await memory.append("c1", user("apple one"), CONTEXT)
        await memory.append("c1", user("apple two"), CONTEXT)

        matches = await memory.search("c1", "apple", 1, CONTEXT)

        assert matches[0].content == "apple two"

    async def test_search_respects_the_limit(self, memory: InMemorySessionMemoryProvider) -> None:
        for index in range(10):
            await memory.append("c1", user(f"match {index}"), CONTEXT)

        assert len(await memory.search("c1", "match", 3, CONTEXT)) == 3

    async def test_summarize_returns_none(self, memory: InMemorySessionMemoryProvider) -> None:
        """Summarising needs a model call, which would invert the layering."""
        assert await memory.summarize("c1", CONTEXT) is None


class TestLifecycle:
    async def test_close_drops_everything(self, memory: InMemorySessionMemoryProvider) -> None:
        await memory.append("c1", user("hello"), CONTEXT)

        await memory.close()

        assert await memory.load("c1", CONTEXT) == ()

    async def test_close_is_safe_on_an_uninitialised_provider(
        self, memory: InMemorySessionMemoryProvider
    ) -> None:
        await memory.close()
        await memory.close()
