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

from agent_platform.application.chat_service import ChatService
from agent_platform.application.health_service import HealthService
from agent_platform.configuration.settings import PlatformSettings
from agent_platform.gateway.llm_gateway import DefaultLLMGateway
from agent_platform.gateway.provider_resolver import ConfiguredProviderResolver
from agent_platform.memory.session_memory import InMemorySessionMemoryProvider
from agent_platform.providers.mock.mock_llm_provider import MockLLMProvider
from agent_platform_sdk.interfaces.llm_provider import LLMProvider
from agent_platform_sdk.interfaces.memory_provider import MemoryProvider
from agent_platform_sdk.interfaces.provider import Provider
from agent_platform_shared.clock import SystemClock

__all__ = ["ApplicationContainer", "build_health_probes", "build_llm_providers"]


def build_llm_providers(settings: PlatformSettings) -> tuple[LLMProvider, ...]:
    """Return the LLM providers this deployment should register.

    A function rather than a container expression because the choice is
    conditional, and a conditional expressed in `dependency-injector`'s
    declarative syntax is harder to read and impossible to unit-test on its own.

    The mock provider is the only entry today, and configuration validation
    already refuses to start a production-like environment with it enabled — so
    this is a second line of defence, not the first. Azure AI Foundry is
    appended here in Milestone 05, and nothing else changes.
    """
    providers: list[LLMProvider] = []

    if settings.mock_provider.enabled and not settings.app.environment.is_production_like:
        providers.append(
            MockLLMProvider(
                provider_id=settings.mock_provider.provider_id,
                model_id=settings.mock_provider.model_id,
                chunk_delay_seconds=settings.mock_provider.chunk_delay_seconds,
            )
        )

    return tuple(providers)


def build_health_probes(
    memory: MemoryProvider,
    llm_providers: tuple[LLMProvider, ...],
) -> tuple[Provider, ...]:
    """Return every component ``/ready`` should probe.

    A function for the same reason as :func:`build_llm_providers`, plus a typing
    one: the health service takes a tuple of :class:`Provider`, and assembling
    it here keeps that contract intact instead of handing the container's list
    provider to a parameter that expects a tuple.

    Order is deliberate — memory first, then inference. A readiness payload
    reads top to bottom, and the cheapest, most fundamental dependency should
    be the first line an operator sees.
    """
    return (memory, *llm_providers)


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

    #: Conversation state. The interface is what every consumer depends on;
    #: replacing this with Redis is a change to this line alone.
    memory_provider = providers.Singleton(
        InMemorySessionMemoryProvider,
        max_conversations=settings.provided.memory.max_conversations,
        max_messages_per_conversation=settings.provided.memory.max_messages_per_conversation,
    )

    #: Registered LLM providers, chosen by configuration. Azure AI Foundry joins
    #: the mock provider here in Milestone 05 — no consumer of the gateway
    #: changes when it does.
    llm_providers = providers.Singleton(build_llm_providers, settings)

    #: Aggregates component health for the readiness endpoint. Every registered
    #: component is probed, so `/ready` reports the real state of the system
    #: rather than only of the process.
    health_service = providers.Singleton(
        HealthService,
        settings=settings,
        clock=clock,
        providers=providers.Callable(build_health_probes, memory_provider, llm_providers),
    )

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

    #: The chat use case. Depends on the gateway and memory protocols only, so
    #: it is unaffected by which provider or memory backend is configured.
    chat_service = providers.Singleton(
        ChatService,
        gateway=llm_gateway,
        memory=memory_provider,
        clock=clock,
        model_id=settings.provided.chat.model_id,
        system_prompt=settings.provided.chat.system_prompt,
        max_prompt_characters=settings.provided.chat.max_prompt_characters,
    )
