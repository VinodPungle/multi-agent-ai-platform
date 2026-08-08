"""Workflow engine behaviour.

Both engines are tested against the same assertions, because that is the claim
the abstraction makes: the runtime cannot tell which one it has. A test that
covered only LangGraph would be testing LangGraph, not the seam.

The parametrisation is the point. If a future engine breaks one of these, it has
broken the contract rather than merely behaved differently.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

import pytest

from agent_platform.exceptions.base import ProviderError, WorkflowError
from agent_platform.workflow.direct_engine import DirectWorkflowEngine
from agent_platform.workflow.langgraph_engine import LangGraphWorkflowEngine
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.dto.agent import AgentDescriptor
from agent_platform_sdk.dto.completion import CompletionChunk, TokenUsage
from agent_platform_sdk.dto.execution import AgentRequest, AgentResult
from agent_platform_sdk.dto.message import Message
from agent_platform_sdk.interfaces.workflow_engine import WorkflowEngine
from agent_platform_sdk.types.enums import MessageRole

pytestmark = pytest.mark.unit

CONTEXT = ExecutionContext()

#: Every engine implementation. A new one is added here and inherits the whole
#: contract suite rather than acquiring its own, partial one.
ENGINES: list[Callable[[], WorkflowEngine]] = [DirectWorkflowEngine, LangGraphWorkflowEngine]


class RecordingAgent:
    """An agent that answers as instructed and records that it ran."""

    def __init__(
        self,
        answer: str = "The answer.",
        failure: Exception | None = None,
        chunks: tuple[str, ...] = ("one", " two"),
    ) -> None:
        self._answer = answer
        self._failure = failure
        self._chunks = chunks
        self.execute_calls = 0
        self.stream_calls = 0
        self.closed = False

    @property
    def descriptor(self) -> AgentDescriptor:
        return AgentDescriptor(
            agent_id="test-agent",
            name="Test",
            description="Test agent.",
            provider_id="fake",
            model_id="test-model",
            prompt_id="test-prompt",
        )

    async def execute(self, request: AgentRequest, context: ExecutionContext) -> AgentResult:
        del request, context
        self.execute_calls += 1
        if self._failure is not None:
            raise self._failure
        return AgentResult(
            message=Message(role=MessageRole.ASSISTANT, content=self._answer),
            agent_id="test-agent",
            model_id="test-model",
            provider_id="fake",
            usage=TokenUsage(prompt_tokens=1, completion_tokens=2),
        )

    async def stream(
        self, request: AgentRequest, context: ExecutionContext
    ) -> AsyncIterator[CompletionChunk]:
        del request, context
        self.stream_calls += 1
        if self._failure is not None:
            raise self._failure
        try:
            for chunk in self._chunks:
                yield CompletionChunk(delta=chunk)
        finally:
            self.closed = True


def a_request() -> AgentRequest:
    return AgentRequest(input="hello", model_id="test-model")


@pytest.fixture(params=ENGINES, ids=lambda factory: factory().engine_id)
def engine(request: pytest.FixtureRequest) -> WorkflowEngine:
    """Each test runs once per engine implementation."""
    factory: Callable[[], WorkflowEngine] = request.param
    return factory()


class TestContractConformance:
    def test_every_engine_satisfies_the_contract(self, engine: WorkflowEngine) -> None:
        assert isinstance(engine, WorkflowEngine)

    def test_every_engine_identifies_itself(self, engine: WorkflowEngine) -> None:
        """Named in spans, so a latency change after a swap is attributable."""
        assert engine.engine_id

    def test_engine_ids_are_distinct(self) -> None:
        assert DirectWorkflowEngine().engine_id != LangGraphWorkflowEngine().engine_id


class TestExecution:
    async def test_the_agent_runs(self, engine: WorkflowEngine) -> None:
        agent = RecordingAgent()

        await engine.execute(agent, a_request(), CONTEXT)

        assert agent.execute_calls == 1

    async def test_the_result_is_returned_unchanged(self, engine: WorkflowEngine) -> None:
        agent = RecordingAgent(answer="specific answer")

        result = await engine.execute(agent, a_request(), CONTEXT)

        assert result.message.content == "specific answer"
        assert result.usage.completion_tokens == 2

    async def test_an_agent_failure_propagates_unchanged(self, engine: WorkflowEngine) -> None:
        """A provider outage must not become an opaque orchestration failure."""
        agent = RecordingAgent(failure=ProviderError("upstream down"))

        with pytest.raises(ProviderError, match="upstream down"):
            await engine.execute(agent, a_request(), CONTEXT)

    async def test_a_non_platform_failure_is_not_swallowed(self, engine: WorkflowEngine) -> None:
        """A programming error must surface, not be reported as a clean result."""
        agent = RecordingAgent(failure=RuntimeError("bug"))

        with pytest.raises((RuntimeError, WorkflowError)):
            await engine.execute(agent, a_request(), CONTEXT)


class TestStreaming:
    async def test_chunks_reach_the_caller(self, engine: WorkflowEngine) -> None:
        agent = RecordingAgent(chunks=("Hello", " world"))

        deltas = [chunk.delta async for chunk in engine.stream(agent, a_request(), CONTEXT)]

        assert "".join(deltas) == "Hello world"

    async def test_the_agent_is_asked_to_stream(self, engine: WorkflowEngine) -> None:
        agent = RecordingAgent()

        _ = [chunk async for chunk in engine.stream(agent, a_request(), CONTEXT)]

        assert agent.stream_calls == 1
        assert agent.execute_calls == 0

    async def test_closing_the_stream_reaches_the_agent(self, engine: WorkflowEngine) -> None:
        """Cancelling must release the provider connection, not just stop reading."""
        agent = RecordingAgent(chunks=("one", " two", " three"))

        stream = engine.stream(agent, a_request(), CONTEXT)
        await anext(stream)
        await stream.aclose()  # type: ignore[attr-defined]  # both engines return generators

        assert agent.closed is True

    async def test_a_streaming_failure_propagates(self, engine: WorkflowEngine) -> None:
        agent = RecordingAgent(failure=ProviderError("down"))

        with pytest.raises(ProviderError):
            _ = [chunk async for chunk in engine.stream(agent, a_request(), CONTEXT)]


class TestEngineEquivalence:
    """The two implementations must be indistinguishable from the outside."""

    async def test_both_engines_produce_the_same_result(self) -> None:
        direct_result = await DirectWorkflowEngine().execute(RecordingAgent(), a_request(), CONTEXT)
        graph_result = await LangGraphWorkflowEngine().execute(
            RecordingAgent(), a_request(), CONTEXT
        )

        assert direct_result == graph_result

    async def test_both_engines_stream_the_same_content(self) -> None:
        direct = [
            chunk.delta
            async for chunk in DirectWorkflowEngine().stream(RecordingAgent(), a_request(), CONTEXT)
        ]
        graph = [
            chunk.delta
            async for chunk in LangGraphWorkflowEngine().stream(
                RecordingAgent(), a_request(), CONTEXT
            )
        ]

        assert direct == graph
