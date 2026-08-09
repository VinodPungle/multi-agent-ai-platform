"""Shared pytest fixtures.

Two rules govern the whole suite:

* **No network access.** Unit tests exercise business logic through injected
  fakes. Anything that would open a socket belongs behind a provider interface,
  and the interface is what gets faked.
* **No shared application.** Every test that needs an app builds its own from
  explicit settings, so tests cannot leak configuration or container state into
  one another.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_platform.agents.chat_agent import ChatAgent
from agent_platform.api.app import create_app
from agent_platform.configuration.settings import (
    AppSettings,
    ChatSettings,
    Environment,
    LoggingSettings,
    PlatformSettings,
    ServerSettings,
    TelemetrySettings,
    get_settings,
)
from agent_platform.evaluation.cost_analytics import (
    CompositeEvaluationProvider,
    InMemoryCostAnalytics,
)
from agent_platform.evaluation.logging_evaluation_provider import (
    LoggingEvaluationProvider,
)
from agent_platform.events.publisher import LoggingEventPublisher
from agent_platform.gateway.llm_gateway import DefaultLLMGateway
from agent_platform.gateway.registry_resolver import RegistryBackedProviderResolver
from agent_platform.memory.session_memory import InMemorySessionMemoryProvider
from agent_platform.providers.mock.mock_llm_provider import MockLLMProvider
from agent_platform.registries import AgentRegistry, KeyedRegistry, ModelRegistry
from agent_platform.routing.policies import (
    AvailabilityPolicy,
    CapabilityPolicy,
    ContextWindowPolicy,
    ObjectivePolicy,
    PinnedModelPolicy,
)
from agent_platform.routing.policy_router import PolicyModelRouter
from agent_platform.runtime.agent_runtime import AgentRuntime
from agent_platform.search.mock_search_provider import MockSearchProvider
from agent_platform.tools.internet_search_tool import (
    INTERNET_SEARCH_TOOL_ID,
    InternetSearchTool,
)
from agent_platform.tools.tool_executor import ToolExecutor
from agent_platform.workflow.direct_engine import DirectWorkflowEngine
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.contracts.health import ComponentHealth
from agent_platform_sdk.dto.agent import AgentDescriptor
from agent_platform_sdk.dto.completion import (
    CompletionChunk,
    CompletionRequest,
    CompletionResponse,
    TokenUsage,
)
from agent_platform_sdk.dto.message import Message
from agent_platform_sdk.dto.model import ModelDescriptor
from agent_platform_sdk.dto.prompt import PromptAsset, PromptVariable
from agent_platform_sdk.interfaces.agent import Agent
from agent_platform_sdk.interfaces.tool_provider import ToolProvider
from agent_platform_sdk.interfaces.workflow_engine import WorkflowEngine
from agent_platform_sdk.policies.retry import RetryPolicy
from agent_platform_sdk.policies.timeout import TimeoutPolicy
from agent_platform_sdk.types.enums import Capability, HealthStatus, MessageRole

__all__ = [
    "FakeClock",
    "app",
    "client",
    "isolated_environment",
    "test_settings",
]

#: Anchored to this file, not the working directory. `isolated_environment`
#: chdirs every test into a temporary directory, so any relative path resolves
#: somewhere empty.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class FakeClock:
    """A controllable :class:`~agent_platform_shared.clock.Clock`.

    Latency assertions against the real clock are inherently flaky. Advancing
    time explicitly makes them exact.
    """

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 1, 1, tzinfo=UTC)
        self._monotonic = 0.0

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._monotonic

    def advance(self, seconds: float) -> None:
        """Move both clocks forward by ``seconds``."""
        self._monotonic += seconds


@pytest.fixture(autouse=True)
def isolated_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pytest.TempPathFactory | Path,
) -> Iterator[None]:
    """Isolate every test from ambient configuration.

    Autouse and non-negotiable. Without it a developer's local setup changes test
    outcomes, producing failures that reproduce on one machine and not another.

    Two sources have to be neutralised, and missing the second one let a real
    bug ship: settings are read from the process environment **and** from a
    ``.env`` file resolved relative to the working directory. Clearing the
    environment alone left the suite reading the repository's own ``.env``, so
    tests passed on a clean checkout and failed the moment anyone followed the
    setup guide.

    Running each test in an empty temporary directory removes that file from the
    search path entirely. A test that wants a ``.env`` writes one and changes
    directory itself, which makes the dependency explicit.
    """
    for key in list(os.environ):
        if key.startswith("PLATFORM_"):
            monkeypatch.delenv(key, raising=False)

    monkeypatch.chdir(tmp_path)  # type: ignore[arg-type]  # pytest supplies a Path

    # `get_settings` memoises. A value cached by an earlier test would otherwise
    # be handed to the next one.
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def test_settings() -> PlatformSettings:
    """Settings for an in-process test application.

    Telemetry is disabled: installing a global tracer provider per test leaks
    state across the session and the OpenTelemetry SDK refuses to replace one
    that is already set.

    The prompts directory is an absolute path to the real ``prompts/`` tree.
    The default is relative, so it resolved against whatever directory pytest
    happened to run from — which loaded nothing, and left the suite asserting
    that a platform holding no prompts was healthy and ready. It is not: every
    agent turn resolves a prompt.
    """
    return PlatformSettings(
        app=AppSettings(
            name="test-platform",
            version="0.0.0-test",
            environment=Environment.TESTING,
            debug=True,
        ),
        server=ServerSettings(cors_origins=("http://localhost:5173",)),
        logging=LoggingSettings(level="DEBUG", renderer="json"),
        telemetry=TelemetrySettings(enabled=False),
        chat=ChatSettings(prompts_directory=str(REPOSITORY_ROOT / "prompts")),
    )


@pytest.fixture
def app(test_settings: PlatformSettings) -> FastAPI:
    """A fully wired application built from :func:`test_settings`."""
    return create_app(test_settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """An HTTP client for ``app``.

    Used as a context manager so the lifespan actually runs — without that,
    startup and shutdown code is never exercised by the suite.
    """
    with TestClient(app) as test_client:
        yield test_client


# --- Runtime test doubles ----------------------------------------------------
# Shared by the runtime and chat-service suites. They live here rather than in a
# second conftest because `tests` is not a package: two modules named `conftest`
# are indistinguishable to mypy, and a helper class can be reached through a
# fixture but never through an import.


def split_preserving_spaces(text: str) -> tuple[str, ...]:
    """Split into chunks whose concatenation is exactly ``text``.

    Whitespace stays attached to the preceding word, matching the guarantee the
    real provider gives. A fake whose stream and non-stream paths disagree makes
    correct code look broken.
    """
    words = text.split(" ")
    return tuple(
        word if index == len(words) - 1 else f"{word} " for index, word in enumerate(words)
    )


class FakeGateway:
    """A gateway that records what it was asked and answers as instructed.

    Satisfies :class:`~agent_platform_sdk.interfaces.llm_gateway.LLMGateway`
    structurally.
    """

    def __init__(
        self,
        answer: str = "The answer.",
        chunks: tuple[str, ...] | None = None,
        failure: Exception | None = None,
        fail_after_chunks: int | None = None,
    ) -> None:
        self._answer = answer
        self._chunks = chunks if chunks is not None else split_preserving_spaces(answer)
        self._failure = failure
        self._fail_after_chunks = fail_after_chunks
        self.requests: list[CompletionRequest] = []

    async def generate(
        self, request: CompletionRequest, context: ExecutionContext
    ) -> CompletionResponse:
        del context
        self.requests.append(request)
        if self._failure is not None:
            raise self._failure
        return CompletionResponse(
            message=Message(role=MessageRole.ASSISTANT, content=self._answer),
            model_id=request.model_id,
            provider_id="fake",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5),
            estimated_cost=Decimal("0.01"),
            finish_reason="stop",
        )

    async def stream(
        self, request: CompletionRequest, context: ExecutionContext
    ) -> AsyncIterator[CompletionChunk]:
        del context
        self.requests.append(request)

        if self._failure is not None and self._fail_after_chunks is None:
            raise self._failure

        for index, chunk in enumerate(self._chunks):
            if self._fail_after_chunks is not None and index >= self._fail_after_chunks:
                assert self._failure is not None
                raise self._failure
            yield CompletionChunk(delta=chunk)

        yield CompletionChunk(
            delta="",
            finish_reason="stop",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5),
        )

    async def count_tokens(
        self, request: CompletionRequest, context: ExecutionContext
    ) -> TokenUsage:
        del request, context
        return TokenUsage(prompt_tokens=10)

    async def estimate_cost(
        self, model_id: str, usage: TokenUsage, context: ExecutionContext
    ) -> Decimal:
        del model_id, usage, context
        return Decimal(0)


class StubPromptProvider:
    """Serves one prompt asset without touching the filesystem.

    Satisfies :class:`~agent_platform_sdk.interfaces.prompt_provider.PromptProvider`.
    """

    def __init__(self, asset: PromptAsset | None = None) -> None:
        self.asset = asset or PromptAsset(
            prompt_id="chat-agent-system",
            version="1.0",
            template="You are a test assistant.",
        )
        self.requested: list[tuple[str, str | None]] = []

    @property
    def provider_id(self) -> str:
        return "stub-prompts"

    async def initialize(self) -> None: ...

    async def health_check(self) -> ComponentHealth:
        return ComponentHealth(name=self.provider_id, status=HealthStatus.HEALTHY)

    def supports(self, capability: Capability) -> bool:
        del capability
        return False

    async def close(self) -> None: ...

    async def get(self, prompt_id: str, version: str | None = None) -> PromptAsset:
        self.requested.append((prompt_id, version))
        return self.asset

    async def list_versions(self, prompt_id: str) -> tuple[str, ...]:
        del prompt_id
        return (self.asset.version,)


class ManualClock:
    """A clock that only moves when a test moves it."""

    def __init__(self) -> None:
        self._monotonic = 0.0

    def now(self) -> datetime:
        return datetime(2026, 1, 1, tzinfo=UTC)

    def monotonic(self) -> float:
        return self._monotonic

    def advance(self, seconds: float) -> None:
        self._monotonic += seconds


def a_descriptor(**overrides: object) -> AgentDescriptor:
    """Build an agent descriptor with test-friendly defaults."""
    fields: dict[str, object] = {
        "agent_id": "chat-agent",
        "name": "Chat Agent",
        "description": "Test agent.",
        "provider_id": "fake",
        "model_id": "test-model",
        "prompt_id": "chat-agent-system",
    }
    fields.update(overrides)
    return AgentDescriptor(**fields)  # type: ignore[arg-type]  # keyword forwarding


def a_model_catalogue(*descriptors: ModelDescriptor) -> ModelRegistry:
    """Build a model registry holding ``descriptors``."""
    registry: ModelRegistry = KeyedRegistry("model")
    for descriptor in descriptors:
        registry.register(descriptor.model_id, descriptor)
    return registry


def a_model(model_id: str, **overrides: Any) -> ModelDescriptor:  # noqa: ANN401
    """Build a model descriptor with generous, test-friendly defaults.

    Capable and roomy by default so that a test which is not about routing does
    not have to think about it. Tests that *are* about routing override the
    field they care about.
    """
    fields: dict[str, Any] = {
        "model_id": model_id,
        "provider_id": "fake",
        "display_name": model_id,
        "capabilities": frozenset(
            {Capability.STREAMING, Capability.TOOL_CALLING, Capability.COST_REPORTING}
        ),
        "max_context_tokens": 128_000,
        "max_output_tokens": 4_096,
    }
    fields.update(overrides)
    return ModelDescriptor(**fields)


def a_model_router(descriptor: AgentDescriptor) -> PolicyModelRouter:
    """Build the real routing chain over a catalogue containing one model.

    The production chain, not a stub. Routing sits in the path of every turn
    now, so a stub here would quietly excuse the runtime from working with the
    thing it actually depends on.
    """
    return PolicyModelRouter(
        models=a_model_catalogue(a_model(descriptor.model_id, provider_id=descriptor.provider_id)),
        policies=(
            PinnedModelPolicy(),
            AvailabilityPolicy(),
            CapabilityPolicy(),
            ContextWindowPolicy(),
            ObjectivePolicy(),
        ),
    )


class RuntimeStack:
    """Everything a runtime test needs, assembled and individually reachable."""

    def __init__(
        self,
        runtime: AgentRuntime,
        gateway: FakeGateway,
        memory: InMemorySessionMemoryProvider,
        prompts: StubPromptProvider,
        agents: AgentRegistry,
        clock: ManualClock,
        analytics: InMemoryCostAnalytics,
    ) -> None:
        self.runtime = runtime
        self.gateway = gateway
        self.memory = memory
        self.prompts = prompts
        self.agents = agents
        self.analytics = analytics
        self.clock = clock


def _tool_capable_gateway() -> DefaultLLMGateway:
    """A real gateway over the real mock provider, which emits tool calls."""
    provider = MockLLMProvider(chunk_delay_seconds=0.0)
    return DefaultLLMGateway(
        resolver=RegistryBackedProviderResolver((provider,), KeyedRegistry("model")),
        clock=ManualClock(),
        retry_policy=RetryPolicy(max_attempts=1),
        timeout_policy=TimeoutPolicy(),
    )


def _tool_executor(clock: ManualClock, search_fails: bool = False) -> ToolExecutor:
    """A real executor over the real internet-search tool and a mock backend."""
    from agent_platform.exceptions.base import ProviderError
    from agent_platform_sdk.dto.search import SearchQuery, SearchResults

    class FailingSearch(MockSearchProvider):
        async def search(self, query: SearchQuery, context: ExecutionContext) -> SearchResults:
            del query, context
            message = "search backend unreachable"
            raise ProviderError(message)

    backend = FailingSearch() if search_fails else MockSearchProvider()
    tool: ToolProvider = InternetSearchTool(backend)

    registry: KeyedRegistry[ToolProvider] = KeyedRegistry("tool")
    registry.register(tool.descriptor.tool_id, tool)

    return ToolExecutor(tools=registry, events=LoggingEventPublisher(), clock=clock)


@pytest.fixture
def build_stack() -> Callable[..., RuntimeStack]:
    """Return a factory that assembles a runtime over a fake gateway.

    Every knob a test needs is a keyword here rather than an object the test
    constructs, because `tests` is not an importable package — a helper class
    can be reached through a fixture but not through an import. Keeping the
    assembly in one place is worth the slightly wider signature.
    """

    def _build(
        *,
        answer: str = "The answer.",
        chunks: tuple[str, ...] | None = None,
        failure: Exception | None = None,
        fail_after_chunks: int | None = None,
        engine: WorkflowEngine | None = None,
        register_agent: bool = True,
        prompt_template: str = "You are a test assistant.",
        prompt_variables: tuple[PromptVariable, ...] = (),
        with_tools: bool = False,
        search_fails: bool = False,
        **descriptor_overrides: object,
    ) -> RuntimeStack:
        # `with_tools` swaps the fake gateway for a real one over the real mock
        # provider, because only the real provider emits tool calls. A fake that
        # emitted them would be testing the fake's idea of the protocol.
        gateway: Any = (
            _tool_capable_gateway()
            if with_tools
            else FakeGateway(
                answer=answer,
                chunks=chunks,
                failure=failure,
                fail_after_chunks=fail_after_chunks,
            )
        )
        prompts = StubPromptProvider(
            PromptAsset(
                prompt_id="chat-agent-system",
                version="1.0",
                template=prompt_template,
                variables=prompt_variables,
            )
        )
        if with_tools:
            descriptor_overrides.setdefault("tool_ids", (INTERNET_SEARCH_TOOL_ID,))
            descriptor_overrides.setdefault("model_id", "mock-echo")
            descriptor_overrides.setdefault("provider_id", "mock")

        descriptor = a_descriptor(**descriptor_overrides)
        memory = InMemorySessionMemoryProvider()
        clock = ManualClock()

        tool_executor = _tool_executor(clock, search_fails=search_fails) if with_tools else None

        analytics = InMemoryCostAnalytics()
        evaluation = CompositeEvaluationProvider((LoggingEvaluationProvider(), analytics))

        agents: AgentRegistry = KeyedRegistry("agent")
        if register_agent:
            agent: Agent = ChatAgent(descriptor, gateway)
            agents.register(descriptor.agent_id, agent)

        runtime = AgentRuntime(
            agents=agents,
            # `direct` by default: these tests are about the runtime, and
            # compiling a graph per call would slow the suite without changing
            # what is being asserted. The LangGraph engine has its own tests.
            workflow_engine=engine or DirectWorkflowEngine(tool_executor),
            memory=memory,
            prompts=prompts,
            events=LoggingEventPublisher(),
            clock=clock,
            # The real router over a real catalogue, not a stub returning the
            # descriptor's model. A stub would agree with whatever the runtime
            # asked for and prove nothing about the two working together —
            # which is the failure mode this suite has hit three times.
            model_router=a_model_router(descriptor),
            # The real composite over the real sinks, so a test exercises
            # the same fan-out production does — and so `RuntimeStack`
            # can assert on what a turn actually recorded.
            evaluation=evaluation,
        )

        return RuntimeStack(runtime, gateway, memory, prompts, agents, clock, analytics)

    return _build


@pytest.fixture
def langgraph_engine() -> WorkflowEngine:
    """The real LangGraph engine, for tests that assert engine independence."""
    from agent_platform.workflow.langgraph_engine import LangGraphWorkflowEngine

    return LangGraphWorkflowEngine()
