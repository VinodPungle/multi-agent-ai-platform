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

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_platform.agents.chat_agent import ChatAgent
from agent_platform.api.app import create_app
from agent_platform.configuration.settings import (
    AppSettings,
    Environment,
    LoggingSettings,
    PlatformSettings,
    ServerSettings,
    TelemetrySettings,
    get_settings,
)
from agent_platform.events.publisher import LoggingEventPublisher
from agent_platform.memory.session_memory import InMemorySessionMemoryProvider
from agent_platform.registries import AgentRegistry, KeyedRegistry
from agent_platform.runtime.agent_runtime import AgentRuntime
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
from agent_platform_sdk.dto.prompt import PromptAsset, PromptVariable
from agent_platform_sdk.interfaces.agent import Agent
from agent_platform_sdk.interfaces.workflow_engine import WorkflowEngine
from agent_platform_sdk.types.enums import Capability, HealthStatus, MessageRole

__all__ = [
    "FakeClock",
    "app",
    "client",
    "isolated_environment",
    "test_settings",
]


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
    ) -> None:
        self.runtime = runtime
        self.gateway = gateway
        self.memory = memory
        self.prompts = prompts
        self.agents = agents
        self.clock = clock


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
        **descriptor_overrides: object,
    ) -> RuntimeStack:
        gateway = FakeGateway(
            answer=answer,
            chunks=chunks,
            failure=failure,
            fail_after_chunks=fail_after_chunks,
        )
        prompts = StubPromptProvider(
            PromptAsset(
                prompt_id="chat-agent-system",
                version="1.0",
                template=prompt_template,
                variables=prompt_variables,
            )
        )
        descriptor = a_descriptor(**descriptor_overrides)
        memory = InMemorySessionMemoryProvider()
        clock = ManualClock()

        agents: AgentRegistry = KeyedRegistry("agent")
        if register_agent:
            agent: Agent = ChatAgent(descriptor, gateway)
            agents.register(descriptor.agent_id, agent)

        runtime = AgentRuntime(
            agents=agents,
            # `direct` by default: these tests are about the runtime, and
            # compiling a graph per call would slow the suite without changing
            # what is being asserted. The LangGraph engine has its own tests.
            workflow_engine=engine or DirectWorkflowEngine(),
            memory=memory,
            prompts=prompts,
            events=LoggingEventPublisher(),
            clock=clock,
        )

        return RuntimeStack(runtime, gateway, memory, prompts, agents, clock)

    return _build


@pytest.fixture
def langgraph_engine() -> WorkflowEngine:
    """The real LangGraph engine, for tests that assert engine independence."""
    from agent_platform.workflow.langgraph_engine import LangGraphWorkflowEngine

    return LangGraphWorkflowEngine()
