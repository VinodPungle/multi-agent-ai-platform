"""Composition root.

The one place in the platform allowed to construct implementations. Everything
else declares what it needs and receives it (``CLAUDE.md``, "Dependency
Injection"). Keeping construction here is what makes a provider swappable by
configuration and makes every consumer testable with a fake.

Registries and providers are added to this container as later milestones land.
Milestone 01 wires configuration, the clock and the health service, which is
enough to prove the pattern works end to end.
"""

from __future__ import annotations

from dependency_injector import containers, providers

from agent_platform.application.health_service import HealthService
from agent_platform.configuration.settings import PlatformSettings
from agent_platform.gateway.llm_gateway import DefaultLLMGateway
from agent_platform.gateway.provider_resolver import ConfiguredProviderResolver
from agent_platform_shared.clock import SystemClock

__all__ = ["ApplicationContainer"]


class ApplicationContainer(containers.DeclarativeContainer):
    """Wires the platform's object graph.

    Provider choice is deliberate:

    ``Object``
        For the already-constructed settings instance. Configuration is
        validated before the container exists, so it is passed in rather than
        built here.
    ``Singleton``
        For stateless collaborators that are safe to share across requests. A
        new clock or health service per request would allocate for no benefit.
    ``Factory``
        For anything holding per-request state. Nothing needs it yet; later
        milestones use it for execution contexts and agent instances.
    """

    #: Settings are supplied by the application factory after validation, so a
    #: configuration failure aborts startup before any wiring is attempted.
    settings = providers.Dependency(instance_of=PlatformSettings)

    #: Injectable time source. Tests substitute a fake so latency assertions are
    #: deterministic instead of racing the wall clock.
    clock = providers.Singleton(SystemClock)

    #: Aggregates component health for the readiness endpoint.
    health_service = providers.Singleton(
        HealthService,
        settings=settings,
        clock=clock,
    )

    #: Registered LLM providers. Empty until Milestone 05 registers Azure AI
    #: Foundry. Declared now so that registering one is an addition here and
    #: nowhere else — no consumer of the gateway changes when it becomes
    #: non-empty.
    llm_providers = providers.Object(())

    #: Answers which provider serves a model. Replaced by a registry-backed
    #: implementation in Milestone 03; the gateway is unaffected because it
    #: depends on the resolver protocol.
    llm_provider_resolver = providers.Singleton(
        ConfiguredProviderResolver,
        providers=llm_providers,
        default_provider_id=settings.provided.llm_gateway.default_provider_id,
    )

    #: The platform's only path to model inference. Business logic depends on
    #: the `LLMGateway` protocol; this is the single place the implementation is
    #: named.
    llm_gateway = providers.Singleton(
        DefaultLLMGateway,
        resolver=llm_provider_resolver,
        clock=clock,
        retry_policy=settings.provided.llm_gateway.retry,
        timeout_policy=settings.provided.llm_gateway.timeout,
    )
