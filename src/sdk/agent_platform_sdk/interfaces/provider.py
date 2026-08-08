"""Base contract shared by every provider.

Providers are the platform's ports to the outside world. Whatever the provider
does — inference, memory, search, embeddings — the runtime needs the same four
things from all of them: an id, a lifecycle, a health probe, and a way to ask
what it can do.

Protocols rather than abstract base classes: an implementation satisfies the
contract structurally, so a provider never has to import a platform base class
and a test double never has to subclass anything.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent_platform_sdk.contracts.health import ComponentHealth
from agent_platform_sdk.types.enums import Capability

__all__ = ["Provider"]


@runtime_checkable
class Provider(Protocol):
    """Lifecycle, identity and capability reporting common to all providers."""

    @property
    def provider_id(self) -> str:
        """Stable identifier under which this provider is registered."""
        ...

    async def initialize(self) -> None:
        """Acquire resources needed before first use.

        Called once during application startup. Doing this eagerly means a
        misconfigured provider fails at boot rather than on a user's request.
        Implementations must be idempotent.
        """
        ...

    async def health_check(self) -> ComponentHealth:
        """Report current health.

        Must not raise: an unreachable dependency is an ``UNHEALTHY`` result,
        not an exception, so that one failing provider cannot break the health
        endpoint for every other component.
        """
        ...

    def supports(self, capability: Capability) -> bool:
        """Return whether this provider offers ``capability``.

        Routing decisions check capabilities, never provider identity
        (``architecture.md`` §44).
        """
        ...

    async def close(self) -> None:
        """Release resources held by the provider.

        Called during graceful shutdown. Must be safe to call more than once,
        and safe to call on a provider that was never initialised.
        """
        ...
