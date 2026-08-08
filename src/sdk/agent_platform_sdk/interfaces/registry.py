"""Registry contract.

``architecture.md`` §26 gives every registry the same responsibilities:
registration, discovery, validation and metadata lookup — and forbids registries
from executing business logic.

A single generic protocol means the agent, model, provider, tool, prompt and
memory registries all behave identically, so operator tooling and tests written
against one work against all of them.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["Registry"]


@runtime_checkable
class Registry[TItem](Protocol):
    """A keyed catalogue of platform capabilities.

    Registries are populated during startup by the composition root. They are
    read-mostly afterwards, which is why lookup is synchronous — an ``await`` on
    every registry read would add nothing but noise on hot paths.
    """

    def register(self, key: str, item: TItem) -> None:
        """Add ``item`` under ``key``.

        Raises:
            ConflictError: when ``key`` is already registered. Silent overwrites
                are rejected because a duplicate registration is a configuration
                mistake that is otherwise invisible until something misbehaves
                at runtime.
        """
        ...

    def get(self, key: str) -> TItem:
        """Return the item registered under ``key``.

        Raises:
            NotFoundError: when nothing is registered under ``key``.
        """
        ...

    def try_get(self, key: str) -> TItem | None:
        """Return the item registered under ``key``, or ``None`` if absent.

        For callers where absence is an expected branch rather than an error.
        """
        ...

    def contains(self, key: str) -> bool:
        """Return whether ``key`` is registered."""
        ...

    def keys(self) -> tuple[str, ...]:
        """Return all registered keys, in registration order.

        Order is preserved so that discovery endpoints and operator tooling
        present a stable list across restarts.
        """
        ...

    def items(self) -> tuple[tuple[str, TItem], ...]:
        """Return all registered pairs, in registration order."""
        ...
