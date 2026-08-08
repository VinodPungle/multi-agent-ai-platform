"""Application layer — use cases that orchestrate domain objects and providers.

Responsibility
    One class per use case ("report platform health", "send a chat message",
    "list available agents"). Application services depend on SDK *interfaces*
    and receive implementations through constructor injection, which is what
    lets a use case be tested with fakes and shipped against any provider.

Dependency rule
    May import ``domain``, ``configuration``, ``telemetry`` and
    ``agent_platform_sdk``. Must never import ``providers``, ``storage`` or
    ``security`` implementations, nor anything from ``api``.

Milestone 01 implements :class:`~agent_platform.application.health_service.HealthService`.
Conversation use cases arrive in Milestone 02.
"""

from agent_platform.application.health_service import HealthService

__all__ = ["HealthService"]
