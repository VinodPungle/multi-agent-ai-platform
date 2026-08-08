"""Registry behaviour.

One implementation backs every registry in the platform, so a defect here is a
defect in agent, provider, model, tool and memory lookup simultaneously. The
tests that matter are the two behaviours that are choices rather than
conveniences: duplicate registration is refused, and a miss names what exists.
"""

from __future__ import annotations

import pytest

from agent_platform.exceptions.base import ConflictError, NotFoundError
from agent_platform.registries import KeyedRegistry
from agent_platform_sdk.interfaces.registry import Registry

pytestmark = pytest.mark.unit


@pytest.fixture
def registry() -> KeyedRegistry[str]:
    return KeyedRegistry("agent")


class TestContractConformance:
    def test_it_satisfies_the_registry_contract(self, registry: KeyedRegistry[str]) -> None:
        assert isinstance(registry, Registry)


class TestRegistration:
    def test_a_registered_item_is_returned(self, registry: KeyedRegistry[str]) -> None:
        registry.register("chat-agent", "the agent")

        assert registry.get("chat-agent") == "the agent"

    def test_duplicate_registration_is_refused(self, registry: KeyedRegistry[str]) -> None:
        """Silently keeping whichever loaded last differs between machines."""
        registry.register("chat-agent", "first")

        with pytest.raises(ConflictError, match="already registered"):
            registry.register("chat-agent", "second")

    def test_the_first_registration_survives_a_rejected_duplicate(
        self, registry: KeyedRegistry[str]
    ) -> None:
        registry.register("chat-agent", "first")

        with pytest.raises(ConflictError):
            registry.register("chat-agent", "second")

        assert registry.get("chat-agent") == "first"

    @pytest.mark.parametrize("key", ["", "   "])
    def test_a_blank_key_is_refused(self, registry: KeyedRegistry[str], key: str) -> None:
        with pytest.raises(ConflictError, match="blank key"):
            registry.register(key, "item")


class TestLookup:
    def test_a_miss_raises(self, registry: KeyedRegistry[str]) -> None:
        with pytest.raises(NotFoundError):
            registry.get("nothing")

    def test_the_error_names_what_is_registered(self, registry: KeyedRegistry[str]) -> None:
        """The usual cause is a typo, and the answer is then on screen."""
        registry.register("chat-agent", "item")

        with pytest.raises(NotFoundError, match="chat-agent"):
            registry.get("chat-agnet")

    def test_the_error_names_the_kind_of_thing_that_is_missing(self) -> None:
        """'No agent registered' tells an operator what to look for; 'No item' does not."""
        with pytest.raises(NotFoundError, match="No model registered"):
            KeyedRegistry[str]("model").get("gpt-5")

    def test_try_get_returns_none_for_a_miss(self, registry: KeyedRegistry[str]) -> None:
        """For callers where absence is an expected branch rather than an error."""
        assert registry.try_get("nothing") is None

    def test_contains_reports_membership(self, registry: KeyedRegistry[str]) -> None:
        registry.register("present", "item")

        assert registry.contains("present") is True
        assert registry.contains("absent") is False


class TestDiscovery:
    def test_keys_are_returned_in_registration_order(self, registry: KeyedRegistry[str]) -> None:
        """Operator tooling must present a stable list across restarts."""
        for key in ("first", "second", "third"):
            registry.register(key, key)

        assert registry.keys() == ("first", "second", "third")

    def test_items_are_returned_in_registration_order(self, registry: KeyedRegistry[str]) -> None:
        registry.register("a", "one")
        registry.register("b", "two")

        assert registry.items() == (("a", "one"), ("b", "two"))

    def test_an_empty_registry_reports_nothing(self, registry: KeyedRegistry[str]) -> None:
        assert registry.keys() == ()
        assert len(registry) == 0
