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

from collections.abc import Callable

from dependency_injector import containers, providers

from agent_platform.agents.chat_agent import ChatAgent
from agent_platform.application.chat_service import ChatService
from agent_platform.application.health_service import HealthService
from agent_platform.configuration.settings import PlatformSettings
from agent_platform.events.publisher import LoggingEventPublisher
from agent_platform.gateway.llm_gateway import DefaultLLMGateway
from agent_platform.gateway.registry_resolver import RegistryBackedProviderResolver
from agent_platform.knowledge.in_memory_vector_store import InMemoryVectorStore
from agent_platform.knowledge.indexer import KnowledgeIndexer
from agent_platform.knowledge.retriever import KnowledgeRetriever
from agent_platform.memory.entra_credentials import EntraIdRedisCredentialProvider
from agent_platform.memory.redis_memory import RedisConversationMemoryProvider
from agent_platform.memory.session_memory import InMemorySessionMemoryProvider
from agent_platform.prompts.file_prompt_provider import (
    FilePromptProvider,
    resolve_prompts_directory,
)
from agent_platform.providers.azure_foundry.azure_foundry_embeddings import (
    AzureFoundryEmbeddingProvider,
)
from agent_platform.providers.azure_foundry.azure_foundry_provider import (
    AzureFoundryProvider,
)
from agent_platform.providers.mock.hashing_embedding_provider import HashingEmbeddingProvider
from agent_platform.providers.mock.mock_llm_provider import MockLLMProvider
from agent_platform.registries import (
    AgentRegistry,
    KeyedRegistry,
    ModelRegistry,
    ProviderRegistry,
)
from agent_platform.routing.policies import (
    AvailabilityPolicy,
    CapabilityPolicy,
    ContextWindowPolicy,
    ObjectivePolicy,
    PinnedModelPolicy,
)
from agent_platform.routing.policy_router import PolicyModelRouter
from agent_platform.runtime.agent_runtime import AgentRuntime
from agent_platform.search.duckduckgo_search_provider import DuckDuckGoSearchProvider
from agent_platform.search.mock_search_provider import MockSearchProvider
from agent_platform.search.tavily_search_provider import TavilySearchProvider
from agent_platform.security.credentials import build_azure_credential
from agent_platform.tools.delegate_tool import DelegateToAgentTool
from agent_platform.tools.internet_search_tool import InternetSearchTool
from agent_platform.tools.knowledge_search_tool import KnowledgeSearchTool
from agent_platform.tools.mcp.discovery import build_mcp_session
from agent_platform.tools.mcp.session import MCPSession
from agent_platform.tools.tool_executor import ToolExecutor
from agent_platform.workflow.direct_engine import DirectWorkflowEngine
from agent_platform.workflow.langgraph_engine import LangGraphWorkflowEngine
from agent_platform_sdk.dto.agent import AgentDescriptor
from agent_platform_sdk.interfaces.agent import Agent
from agent_platform_sdk.interfaces.embedding_provider import EmbeddingProvider
from agent_platform_sdk.interfaces.llm_gateway import LLMGateway
from agent_platform_sdk.interfaces.llm_provider import LLMProvider
from agent_platform_sdk.interfaces.memory_provider import MemoryProvider
from agent_platform_sdk.interfaces.model_router import ModelRouter
from agent_platform_sdk.interfaces.provider import Provider
from agent_platform_sdk.interfaces.search_provider import SearchProvider
from agent_platform_sdk.interfaces.tool_provider import ToolProvider
from agent_platform_sdk.interfaces.workflow_engine import WorkflowEngine
from agent_platform_sdk.policies.budget import BudgetPolicy
from agent_platform_shared.clock import SystemClock

__all__ = [
    "ApplicationContainer",
    "build_agent_registry",
    "build_embedding_provider",
    "build_health_probes",
    "build_llm_providers",
    "build_mcp_sessions",
    "build_memory_provider",
    "build_model_registry",
    "build_model_router",
    "build_provider_registry",
    "build_search_provider",
    "build_tool_registry",
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

    if settings.azure_foundry.enabled:
        azure = settings.azure_foundry
        llm_providers.append(
            AzureFoundryProvider(
                endpoint=azure.endpoint,
                deployment=azure.deployment,
                model_id=azure.model_id,
                # Constructed here, in the composition root, because it is the
                # only place allowed to build infrastructure. The provider
                # receives it, so tests never touch the credential chain.
                credential=build_azure_credential(),
                provider_id=azure.provider_id,
                max_context_tokens=azure.max_context_tokens,
                max_output_tokens=azure.max_output_tokens,
                input_cost_per_million_tokens=azure.input_cost_per_million_tokens,
                output_cost_per_million_tokens=azure.output_cost_per_million_tokens,
                supports_tools=azure.supports_tools,
                output_token_parameter=azure.output_token_parameter,
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


def build_model_router(
    settings: PlatformSettings,
    models: ModelRegistry,
) -> ModelRouter:
    """Return the routing chain this deployment should use.

    The order is the design: constraints first so that rankings only ever sort
    models which could actually serve the turn, and so a failure names the real
    reason rather than the last policy to touch an already-empty list.

    Pinning runs before the constraints deliberately. A pinned model that cannot
    do what the turn requires fails with the capability named — quietly routing
    elsewhere would answer with a model the caller did not ask for and would
    never hear about.
    """
    return PolicyModelRouter(
        models=models,
        policies=(
            PinnedModelPolicy(),
            AvailabilityPolicy(),
            CapabilityPolicy(),
            ContextWindowPolicy(),
            ObjectivePolicy(),
        ),
        default_objective=settings.routing.objective,
    )


def build_memory_provider(settings: PlatformSettings) -> MemoryProvider:
    """Return the configured conversation store.

    Both satisfy one interface, so no agent and no runtime code can tell which
    it has — which is why durable memory was a new module and this branch rather
    than a change to anything that reads a conversation.
    """
    if settings.memory.provider == "redis":
        # Entra in a deployed environment, nothing in Compose. Built here rather
        # than inside the provider so that the provider needs no knowledge of
        # Azure, and so a test can hand it neither.
        credential_provider = (
            EntraIdRedisCredentialProvider(
                credential=build_azure_credential(),
                principal_id=settings.memory.redis_principal_id,
            )
            if settings.memory.redis_auth_mode == "entra"
            else None
        )
        return RedisConversationMemoryProvider(
            # Unwrapped at the single point of use; it travels as a `SecretStr`
            # everywhere else so it cannot be logged by accident.
            url=settings.memory.redis_url.get_secret_value(),
            ttl_seconds=settings.memory.redis_ttl_seconds,
            max_messages_per_conversation=settings.memory.max_messages_per_conversation,
            credential_provider=credential_provider,
        )

    return InMemorySessionMemoryProvider(
        max_conversations=settings.memory.max_conversations,
        max_messages_per_conversation=settings.memory.max_messages_per_conversation,
    )


def build_search_provider(settings: PlatformSettings) -> SearchProvider:
    """Return the configured search backend.

    All three satisfy one interface, so the internet-search tool cannot tell
    which it has — which is why Tavily was a new module and this branch rather
    than a change to the tool, the runtime or any agent.

    The choice reaches every agent at once: agents declare the *tool*, not a
    search backend, so switching this switches what all of them search with.
    """
    if settings.search.provider == "mock":
        return MockSearchProvider()

    if settings.search.provider == "tavily":
        return TavilySearchProvider(
            # Unwrapped at the single point of use. It travels as a `SecretStr`
            # everywhere else so it cannot be logged by accident.
            api_key=settings.search.tavily_api_key.get_secret_value(),
            timeout_seconds=settings.search.timeout_seconds,
            search_depth=settings.search.search_depth,
        )

    return DuckDuckGoSearchProvider(timeout_seconds=settings.search.timeout_seconds)


def build_tool_registry(
    settings: PlatformSettings,
    search_provider: SearchProvider,
    runtime_provider: Callable[[], AgentRuntime],
    retriever: KnowledgeRetriever | None = None,
) -> KeyedRegistry[ToolProvider]:
    """Register every tool this deployment offers.

    Gated on `features.search`: with the flag off the tool is simply not
    registered, so an agent that declares it runs without it and the turn costs
    exactly one model call. That is a real off switch rather than a tool that
    exists and refuses.
    """
    registry: KeyedRegistry[ToolProvider] = KeyedRegistry("tool")

    if settings.features.search:
        tool = InternetSearchTool(
            provider=search_provider,
            timeout_seconds=settings.search.timeout_seconds,
            max_results=settings.search.max_results,
        )
        registry.register(tool.descriptor.tool_id, tool)

    # Retrieval is a tool, not a prompt preamble: the model decides when
    # documents are needed, so a turn that needs none spends no context on them
    # — and the runtime applies the same authorisation, timeout, retry,
    # telemetry and budget it applies to every other tool. See ADR-0015.
    if settings.knowledge.enabled and retriever is not None:
        knowledge_tool = KnowledgeSearchTool(
            retriever=retriever,
            max_passages=settings.knowledge.max_passages,
        )
        registry.register(knowledge_tool.descriptor.tool_id, knowledge_tool)

    # Delegation. Registered as a tool because a tool *is* the runtime
    # mediating: `architecture.md` §31 forbids agents calling each other
    # directly, and the tool pipeline already applies authorisation, timeouts,
    # retries, telemetry and budgets to every hop.
    if settings.research_agent.enabled:
        delegate = DelegateToAgentTool(
            runtime_provider=runtime_provider,
            # Only the agents named here, not everything registered. A
            # coordinator able to invoke whatever happens to exist is how one
            # agent's permissions quietly become everyone's.
            delegatable_agent_ids=(settings.research_agent.agent_id,),
            max_delegation_depth=settings.research_agent.max_delegation_depth,
        )
        registry.register(delegate.descriptor.tool_id, delegate)

    return registry


def build_embedding_provider(settings: PlatformSettings) -> EmbeddingProvider:
    """Return the configured embedding provider.

    The hashing provider is refused in production-like environments. It computes
    *lexical* embeddings — shared character sequences, not meaning — and a
    knowledge base built on it would answer confidently from documents that
    merely look like the question. The check here mirrors the mock LLM
    provider's, and for the same reason: something convincing enough to be
    useful in development is exactly what gets left switched on by accident.
    """
    if (
        settings.knowledge.embedding_provider == "azure-foundry"
        or settings.app.environment.is_production_like
    ):
        return AzureFoundryEmbeddingProvider(
            endpoint=settings.azure_foundry.endpoint,
            deployment=settings.knowledge.embedding_deployment,
            credential=build_azure_credential(),
            dimensions=settings.knowledge.embedding_dimensions,
        )

    return HashingEmbeddingProvider(dimensions=settings.knowledge.embedding_dimensions)


def build_mcp_sessions(settings: PlatformSettings) -> tuple[MCPSession, ...]:
    """Return a session for every enabled MCP server.

    Construction only — nothing connects here. Discovery is an async call and
    happens during startup, which is also the only place a third party's
    availability should be able to affect anything.
    """
    if not settings.mcp.enabled:
        return ()

    return tuple(build_mcp_session(server) for server in settings.mcp.servers if server.is_enabled)


def build_workflow_engine(
    settings: PlatformSettings,
    tool_executor: ToolExecutor,
) -> WorkflowEngine:
    """Return the configured workflow engine.

    Two implementations of one protocol. `direct` involves no graph library at
    all, which makes it a way to rule orchestration out when diagnosing a
    problem — and proof that the abstraction is not LangGraph-shaped.
    """
    if settings.workflow.engine == "direct":
        return DirectWorkflowEngine(tool_executor)
    return LangGraphWorkflowEngine(tool_executor)


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
        tool_ids=settings.agent.tool_ids,
        budget=BudgetPolicy(
            max_tool_invocations=settings.agent.max_tool_invocations,
            max_model_calls=settings.agent.max_model_calls,
        ),
    )
    agent: Agent = ChatAgent(descriptor, gateway)
    registry.register(descriptor.agent_id, agent)

    # The research specialist. No new class: `ChatAgent` is generic because an
    # agent's behaviour lives in its descriptor and prompt, so a specialist is
    # configuration plus a prompt asset. That is the property `architecture.md`
    # §74 asks for, demonstrated rather than asserted.
    if settings.research_agent.enabled:
        research = settings.research_agent
        research_descriptor = AgentDescriptor(
            agent_id=research.agent_id,
            name="Research Agent",
            description=("Searches for current information and answers with cited sources."),
            # Empty inherits the chat agent's, which is the common case. Setting
            # them is how one agent uses a cheaper or stronger model.
            provider_id=research.provider_id or settings.agent.provider_id,
            model_id=research.model_id or settings.agent.model_id,
            prompt_id=research.prompt_id,
            prompt_version=research.prompt_version,
            temperature=research.temperature,
            max_output_tokens=research.max_output_tokens,
            tool_ids=research.tool_ids,
            budget=BudgetPolicy(
                max_tool_invocations=research.max_tool_invocations,
                max_model_calls=research.max_model_calls,
            ),
        )
        registry.register(research_descriptor.agent_id, ChatAgent(research_descriptor, gateway))

    return registry


def build_health_probes(
    memory: MemoryProvider,
    prompts: FilePromptProvider,
    search: SearchProvider,
    llm_providers: tuple[LLMProvider, ...],
) -> tuple[Provider, ...]:
    """Return every component ``/ready`` should probe.

    Order is deliberate — memory, prompts, then inference. A readiness payload
    reads top to bottom, and the cheapest, most fundamental dependencies should
    be the first lines an operator sees.
    """
    return (memory, prompts, search, *llm_providers)


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
    ``Self``
        Only for the one genuine cycle: the tool registry is built before the
        runtime, and the runtime needs the registry. A self-reference defers
        resolution to first use instead of mutating a constructed object.
    """

    #: The container itself, so a provider declared early can reference one
    #: declared later. Used once, for delegation; a second use would be a sign
    #: the graph has an ordering problem rather than a cycle.
    __self__ = providers.Self()

    #: Settings are supplied by the application factory after validation, so a
    #: configuration failure aborts startup before any wiring is attempted.
    settings = providers.Dependency(instance_of=PlatformSettings)

    #: Injectable time source. Tests substitute a fake so latency assertions are
    #: deterministic instead of racing the wall clock.
    clock = providers.Singleton(SystemClock)

    # -- Infrastructure ----------------------------------------------------

    #: Conversation state. The interface is what every consumer depends on;
    #: replacing this with Redis is a change to this line alone.
    memory_provider = providers.Singleton(build_memory_provider, settings)

    #: Versioned prompt assets, loaded from disk once during startup.
    prompt_provider = providers.Singleton(
        FilePromptProvider,
        # Resolved rather than wrapped in `Path`: a relative value would
        # otherwise depend on the directory the process was launched from.
        root=providers.Callable(
            resolve_prompts_directory, settings.provided.chat.prompts_directory
        ),
    )

    #: Where search results come from. The interface is what the tool depends
    #: on, so a keyed provider replaces this line and nothing else.
    search_provider = providers.Singleton(build_search_provider, settings)

    #: Registered LLM providers, chosen by configuration.
    llm_providers = providers.Singleton(build_llm_providers, settings)

    #: Runtime event fan-out. A bus implementation replaces this without the
    #: runtime's publish call sites changing.
    event_publisher = providers.Singleton(LoggingEventPublisher)

    # -- Registries and tools ----------------------------------------------

    provider_registry = providers.Singleton(build_provider_registry, llm_providers)
    model_registry = providers.Singleton(build_model_registry)

    #: Executable tools, gated by the search feature flag. With the flag off the
    #: registry is empty, so an agent that declares a tool simply runs without
    #: it — a real off switch rather than a tool that exists and refuses.
    #: `agent_runtime.provider` rather than `agent_runtime`: the tool registry
    #: is built before the runtime, and the runtime needs the registry. Passing
    #: the provider defers resolution to the first delegation, by which time
    #: everything exists.
    #: Sessions for the configured MCP servers. Empty unless MCP is enabled.
    #: Nothing connects here: discovery runs during startup.
    mcp_sessions = providers.Singleton(build_mcp_sessions, settings)

    # -- Knowledge ---------------------------------------------------------
    # Indexer and retriever share one embedding provider, and that is not
    # incidental: two different models produce vectors in unrelated spaces, so
    # embedding a corpus with one and searching it with the other returns
    # confident nonsense rather than an error.

    embedding_provider = providers.Singleton(build_embedding_provider, settings)

    vector_store = providers.Singleton(InMemoryVectorStore)

    knowledge_indexer = providers.Singleton(
        KnowledgeIndexer,
        embeddings=embedding_provider,
        vectors=vector_store,
        collection=settings.provided.knowledge.collection,
        max_chunk_characters=settings.provided.knowledge.max_chunk_characters,
        chunk_overlap_characters=settings.provided.knowledge.chunk_overlap_characters,
    )

    knowledge_retriever = providers.Singleton(
        KnowledgeRetriever,
        embeddings=embedding_provider,
        vectors=vector_store,
        collection=settings.provided.knowledge.collection,
        default_limit=settings.provided.knowledge.max_passages,
        minimum_score=settings.provided.knowledge.minimum_score,
    )

    tool_registry = providers.Singleton(
        build_tool_registry,
        settings,
        search_provider,
        # Resolves to the `agent_runtime` provider, which is itself callable —
        # so the tool gets a zero-argument accessor that yields the runtime on
        # first delegation, by which time the graph is complete.
        runtime_provider=__self__.provided.agent_runtime,
        retriever=knowledge_retriever,
    )

    #: The one path through which a tool is ever run: resolve, authorise,
    #: validate, time out, retry, record. Never raises.
    tool_executor = providers.Singleton(
        ToolExecutor,
        tools=tool_registry,
        events=event_publisher,
        clock=clock,
    )

    # -- Inference ---------------------------------------------------------

    #: Resolves a model to the provider that registered it. Registry-backed
    #: rather than configured, because routing can now choose a model on a
    #: provider other than the default — and resolving to the default anyway
    #: would ask it for a model it has never heard of.
    llm_provider_resolver = providers.Singleton(
        RegistryBackedProviderResolver,
        providers=llm_providers,
        models=model_registry,
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
        circuit_breaker_policy=settings.provided.llm_gateway.circuit_breaker,
    )

    # -- Runtime -----------------------------------------------------------

    agent_registry = providers.Singleton(build_agent_registry, settings, llm_gateway)

    workflow_engine = providers.Singleton(build_workflow_engine, settings, tool_executor)

    #: The heart of the platform. Depends on interfaces only, so what it
    #: orchestrates is entirely a matter of what was registered above.
    #: Chooses which model answers a turn. The runtime asks it rather than
    #: reading the agent's descriptor, so changing routing is a configuration
    #: change (``CLAUDE.md``, "Runtime Model Selection").
    model_router = providers.Singleton(build_model_router, settings, model_registry)

    agent_runtime = providers.Singleton(
        AgentRuntime,
        agents=agent_registry,
        workflow_engine=workflow_engine,
        memory=memory_provider,
        prompts=prompt_provider,
        events=event_publisher,
        clock=clock,
        model_router=model_router,
    )

    # -- Application -------------------------------------------------------

    #: Aggregates component health for the readiness endpoint.
    health_service = providers.Singleton(
        HealthService,
        settings=settings,
        clock=clock,
        providers=providers.Callable(
            build_health_probes,
            memory_provider,
            prompt_provider,
            search_provider,
            llm_providers,
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
