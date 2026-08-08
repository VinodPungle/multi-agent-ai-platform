"""Composition root.

The one place in the platform allowed to construct implementations. Everything
else declares what it needs and receives it (``CLAUDE.md``, "Dependency
Injection"). Keeping construction here is what makes a provider swappable by
configuration and makes every consumer testable with a fake.

Where a choice is conditional it is a module-level function rather than a
declarative expression — a conditional written in `dependency-injector`'s syntax
is harder to read and cannot be unit-tested on its own. Each of those functions
is covered directly by `tests/unit/dependencies/test_container.py`.
"""

from __future__ import annotations

from pathlib import Path

from dependency_injector import containers, providers

from agent_platform.agents.chat_agent import ChatAgent
from agent_platform.application.chat_service import ChatService
from agent_platform.application.health_service import HealthService
from agent_platform.configuration.settings import PlatformSettings
from agent_platform.events.publisher import LoggingEventPublisher
from agent_platform.gateway.llm_gateway import DefaultLLMGateway
from agent_platform.gateway.provider_resolver import ConfiguredProviderResolver
from agent_platform.memory.session_memory import InMemorySessionMemoryProvider
from agent_platform.prompts.file_prompt_provider import FilePromptProvider
from agent_platform.providers.mock.mock_llm_provider import MockLLMProvider
from agent_platform.registries import (
    AgentRegistry,
    KeyedRegistry,
    ModelRegistry,
    ProviderRegistry,
    ToolRegistry,
)
from agent_platform.runtime.agent_runtime import AgentRuntime
from agent_platform.workflow.direct_engine import DirectWorkflowEngine
from agent_platform.workflow.langgraph_engine import LangGraphWorkflowEngine
from agent_platform_sdk.dto.agent import AgentDescriptor
from agent_platform_sdk.interfaces.agent import Agent
from agent_platform_sdk.interfaces.llm_gateway import LLMGateway
from agent_platform_sdk.interfaces.llm_provider import LLMProvider
from agent_platform_sdk.interfaces.memory_provider import MemoryProvider
from agent_platform_sdk.interfaces.provider import Provider
from agent_platform_sdk.interfaces.workflow_engine import WorkflowEngine
from agent_platform_shared.clock import SystemClock

__all__ = [
    "ApplicationContainer",
    "build_agent_registry",
    "build_health_probes",
    "build_llm_providers",
    "build_model_registry",
    "build_provider_registry",
    "build_workflow_engine",
]


def build_llm_providers(settings: PlatformSettings) -> tuple[LLMProvider, ...]:
    """Return the LLM providers this deployment should register.

    The mock provider is the only entry today, and configuration validation
    already refuses to start a production-like environment with it enabled — so
    the environment check here is a second line of defence, not the first. Azure
    AI Foundry is appended in Milestone 05, and nothing else changes.
    """
    llm_providers: list[LLMProvider] = []

    if settings.mock_provider.enabled and not settings.app.environment.is_production_like:
        llm_providers.append(
            MockLLMProvider(
                provider_id=settings.mock_provider.provider_id,
                model_id=settings.mock_provider.model_id,
                chunk_delay_seconds=settings.mock_provider.chunk_delay_seconds,
            )
        )

    return tuple(llm_providers)


def build_provider_registry(llm_providers: tuple[LLMProvider, ...]) -> ProviderRegistry:
    """Catalogue the registered providers by id."""
    registry: ProviderRegistry = KeyedRegistry("LLM provider")
    for provider in llm_providers:
        registry.register(provider.provider_id, provider)
    return registry


def build_model_registry() -> ModelRegistry:
    """Return an empty model catalogue.

    Populated during application startup by awaiting each provider's
    ``list_models()`` — see :func:`agent_platform.api.app.initialize_platform`.
    It cannot be filled here, because a provider's catalogue is an async call
    and a real provider's is a network call.

    The registry is the authoritative source of model information
    (``architecture.md`` §30), and the runtime uses it to refuse an agent that
    names a model nothing can serve — a configuration typo that would otherwise
    surface as a provider error on a user's first request.
    """
    return KeyedRegistry("model")


def build_workflow_engine(settings: PlatformSettings) -> WorkflowEngine:
    """Return the configured workflow engine.

    Two implementations of one protocol. `direct` involves no graph library at
    all, which makes it a way to rule orchestration out when diagnosing a
    problem — and proof that the abstraction is not LangGraph-shaped.
    """
    if settings.workflow.engine == "direct":
        return DirectWorkflowEngine()
    return LangGraphWorkflowEngine()


def build_agent_registry(settings: PlatformSettings, gateway: LLMGateway) -> AgentRegistry:
    """Register every agent this deployment serves.

    One agent today, described entirely by configuration. Adding an agent is an
    entry here plus a prompt asset — no change to the runtime, the gateway, or
    any existing agent, which is the property `architecture.md` §74 requires.
    """
    registry: AgentRegistry = KeyedRegistry("agent")

    descriptor = AgentDescriptor(
        agent_id=settings.agent.agent_id,
        name="Chat Agent",
        description="General conversational agent.",
        provider_id=settings.agent.provider_id,
        model_id=settings.agent.model_id,
        prompt_id=settings.agent.prompt_id,
        prompt_version=settings.agent.prompt_version,
        temperature=settings.agent.temperature,
        max_output_tokens=settings.agent.max_output_tokens,
    )
    agent: Agent = ChatAgent(descriptor, gateway)
    registry.register(descriptor.agent_id, agent)

    return registry


def build_health_probes(
    memory: MemoryProvider,
    prompts: FilePromptProvider,
    llm_providers: tuple[LLMProvider, ...],
) -> tuple[Provider, ...]:
    """Return every component ``/ready`` should probe.

    Order is deliberate — memory, prompts, then inference. A readiness payload
    reads top to bottom, and the cheapest, most fundamental dependencies should
    be the first lines an operator sees.
    """
    return (memory, prompts, *llm_providers)


class ApplicationContainer(containers.DeclarativeContainer):
    """Wires the platform's object graph.

    Provider choice is deliberate:

    ``Object``
        For the already-constructed settings instance. Configuration is
        validated before the container exists, so it is passed in rather than
        built here.
    ``Singleton``
        For stateless collaborators that are safe to share across requests, and
        for registries, which are written at startup and read thereafter.
    ``Factory``
        For anything holding per-request state.
    """

    #: Settings are supplied by the application factory after validation, so a
    #: configuration failure aborts startup before any wiring is attempted.
    settings = providers.Dependency(instance_of=PlatformSettings)

    #: Injectable time source. Tests substitute a fake so latency assertions are
    #: deterministic instead of racing the wall clock.
    clock = providers.Singleton(SystemClock)

    # -- Infrastructure ----------------------------------------------------

    #: Conversation state. The interface is what every consumer depends on;
    #: replacing this with Redis is a change to this line alone.
    memory_provider = providers.Singleton(
        InMemorySessionMemoryProvider,
        max_conversations=settings.provided.memory.max_conversations,
        max_messages_per_conversation=settings.provided.memory.max_messages_per_conversation,
    )

    #: Versioned prompt assets, loaded from disk once during startup.
    prompt_provider = providers.Singleton(
        FilePromptProvider,
        root=providers.Callable(Path, settings.provided.chat.prompts_directory),
    )

    #: Registered LLM providers, chosen by configuration.
    llm_providers = providers.Singleton(build_llm_providers, settings)

    #: Runtime event fan-out. A bus implementation replaces this without the
    #: runtime's publish call sites changing.
    event_publisher = providers.Singleton(LoggingEventPublisher)

    # -- Registries --------------------------------------------------------

    provider_registry = providers.Singleton(build_provider_registry, llm_providers)
    model_registry = providers.Singleton(build_model_registry)

    #: Tool metadata. Empty until Milestone 04 — present now so the runtime's
    #: tool-resolution path exists rather than being inserted later.
    tool_registry: providers.Singleton[ToolRegistry] = providers.Singleton(KeyedRegistry, "tool")

    # -- Inference ---------------------------------------------------------

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

    # -- Runtime -----------------------------------------------------------

    agent_registry = providers.Singleton(build_agent_registry, settings, llm_gateway)

    workflow_engine = providers.Singleton(build_workflow_engine, settings)

    #: The heart of the platform. Depends on interfaces only, so what it
    #: orchestrates is entirely a matter of what was registered above.
    agent_runtime = providers.Singleton(
        AgentRuntime,
        agents=agent_registry,
        workflow_engine=workflow_engine,
        memory=memory_provider,
        prompts=prompt_provider,
        events=event_publisher,
        clock=clock,
    )

    # -- Application -------------------------------------------------------

    #: Aggregates component health for the readiness endpoint.
    health_service = providers.Singleton(
        HealthService,
        settings=settings,
        clock=clock,
        providers=providers.Callable(
            build_health_probes, memory_provider, prompt_provider, llm_providers
        ),
    )

    #: The chat use case. Adapts chat-shaped concerns onto the runtime; it holds
    #: no memory of its own and calls no gateway.
    chat_service = providers.Singleton(
        ChatService,
        runtime=agent_runtime,
        memory=memory_provider,
        agent_id=settings.provided.chat.agent_id,
        max_prompt_characters=settings.provided.chat.max_prompt_characters,
    )
