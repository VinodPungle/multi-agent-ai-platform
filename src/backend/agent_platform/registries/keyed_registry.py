"""The one registry implementation.

Every registry in the platform — agents, providers, models, prompts, tools,
memory — is this class at a different type parameter. `architecture.md` §26 gives
them all the same four responsibilities (registration, discovery, validation,
metadata lookup) and forbids all of them from executing business logic, so six
near-identical classes would be six places to fix the same bug.

Two behaviours are worth stating outright, because both are choices:

**Duplicate registration is an error, never an overwrite.** Two components
registered under one key is a configuration mistake. Silently keeping whichever
loaded last produces a system that works on one machine and not another, and the
difference is invisible until something misbehaves under load.

**Lookup is synchronous.** Registries are written once at startup and read on
every request. An ``await`` on each read would add nothing but noise to hot paths.
"""

from __future__ import annotations

from agent_platform.exceptions.base import ConflictError, NotFoundError

__all__ = ["KeyedRegistry"]


class KeyedRegistry[TItem]:
    """A keyed catalogue satisfying
    :class:`~agent_platform_sdk.interfaces.registry.Registry`.

    Not thread-safe, and deliberately not: registration happens during startup on
    one thread, and everything afterwards is a read. A lock would pay a cost on
    every request to protect against a write that cannot happen.
    """

    def __init__(self, label: str = "item") -> None:
        """Create an empty registry.

        Args:
            label: What this registry holds, used in error messages. "No agent
                registered under 'chat-agent'" tells an operator what to look
                for; "No item registered under 'chat-agent'" does not.
        """
        self._label = label
        # A plain dict: insertion-ordered since 3.7, which is what gives
        # `keys()` and `items()` their stable ordering across restarts.
        self._items: dict[str, TItem] = {}

    def register(self, key: str, item: TItem) -> None:
        """Add ``item`` under ``key``.

        Raises:
            ValidationError: ``key`` is blank.
            ConflictError: ``key`` is already registered.
        """
        if not key.strip():
            message = f"A {self._label} cannot be registered under a blank key."
            raise ConflictError(message)

        if key in self._items:
            message = (
                f"A {self._label} is already registered under {key!r}. "
                "Each must have a unique id — a duplicate is a configuration mistake, "
                "and overwriting silently would hide it."
            )
            raise ConflictError(message, details={"key": key, "registry": self._label})

        self._items[key] = item

    def get(self, key: str) -> TItem:
        """Return the item registered under ``key``.

        Raises:
            NotFoundError: nothing is registered under ``key``. The message
                lists what *is* registered, because the usual cause is a typo
                and the answer is then on screen.
        """
        item = self._items.get(key)
        if item is None:
            message = (
                f"No {self._label} registered under {key!r}. "
                f"Registered: {', '.join(sorted(self._items)) or 'none'}."
            )
            raise NotFoundError(message, details={"key": key, "registry": self._label})
        return item

    def try_get(self, key: str) -> TItem | None:
        """Return the item registered under ``key``, or ``None`` if absent."""
        return self._items.get(key)

    def contains(self, key: str) -> bool:
        """Return whether ``key`` is registered."""
        return key in self._items

    def keys(self) -> tuple[str, ...]:
        """Return every registered key, in registration order."""
        return tuple(self._items)

    def items(self) -> tuple[tuple[str, TItem], ...]:
        """Return every registered pair, in registration order."""
        return tuple(self._items.items())

    def __len__(self) -> int:
        """Return how many items are registered."""
        return len(self._items)

    def __repr__(self) -> str:
        return f"KeyedRegistry(label={self._label!r}, count={len(self._items)})"
