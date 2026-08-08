"""Tool calling on the streaming path.

This is the path the browser uses, and the only one it uses. Until
`stream_tool_loop` existed the engines handed the agent's chunks straight
through, so the chat UI could never invoke a tool while the non-streaming
endpoint could. The platform had internet search and the user interface could
not reach it.

Both engines are parametrised, because identical streaming behaviour across
implementations is the claim the abstraction makes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime

import pytest

from agent_platform.events.publisher import LoggingEventPublisher
from agent_platform.registries import KeyedRegistry
from agent_platform.tools.tool_executor import ToolExecutor
from agent_platform.workflow.direct_engine import DirectWorkflowEngine
from agent_platform.workflow.langgraph_engine import LangGraphWorkflowEngine
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.contracts.health import ComponentHealth
from agent_platform_sdk.dto.agent import AgentDescriptor
from agent_platform_sdk.dto.completion import CompletionChunk, TokenUsage
from agent_platform_sdk.dto.execution import AgentRequest, AgentResult
from agent_platform_sdk.dto.message import Message, ToolCall
from agent_platform_sdk.dto.tool import ToolDescriptor, ToolInvocation, ToolResult
from agent_platform_sdk.interfaces.tool_provider import ToolProvider
from agent_platform_sdk.interfaces.workflow_engine import WorkflowEngine
from agent_platform_sdk.policies.budget import BudgetPolicy
from agent_platform_sdk.types.enums import Capability, HealthStatus, MessageRole

pytestmark = pytest.mark.unit

CONTEXT = ExecutionContext()
TOOL_ID = "test-tool"

ENGINES: list[Callable[[ToolExecutor], WorkflowEngine]] = [
    DirectWorkflowEngine,
    LangGraphWorkflowEngine,
]


class RecordingTool:
    """A tool that reports what it was asked and answers as instructed."""

    def __init__(self, answer: str = "Paris is the capital.") -> None:
        self._answer = answer
        self.invocations: list[dict[str, object]] = []

    @property
    def descriptor(self) -> ToolDescriptor:
        return ToolDescriptor(
            tool_id=TOOL_ID,
            description="Returns a fixed answer.",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        )

    async def initialize(self) -> None:
        return None

    async def close(self) -> None:
        return None

    def supports(self, capability: Capability) -> bool:
        del capability
        return False

    async def health_check(self) -> ComponentHealth:
        return ComponentHealth(name=TOOL_ID, status=HealthStatus.HEALTHY)

    @property
    def provider_id(self) -> str:
        return TOOL_ID

    async def validate(self, invocation: ToolInvocation) -> None:
        del invocation

    async def execute(self, invocation: ToolInvocation, context: ExecutionContext) -> ToolResult:
        del context
        self.invocations.append(dict(invocation.arguments))
        return ToolResult(
            tool_id=TOOL_ID,
            call_id=invocation.call_id,
            succeeded=True,
            output={"answer": self._answer},
        )


class ToolStreamingAgent:
    """Streams tool calls first, then prose — what a real tool turn looks like.

    ``tool_turns`` controls how many consecutive streams request a tool before
    the agent settles down and answers, which is how the iteration ceiling and
    the tool budget are driven.
    """

    def __init__(
        self,
        tool_turns: int = 1,
        answer: str = "Grounded answer.",
        tool_ids: tuple[str, ...] = (TOOL_ID,),
        budget: BudgetPolicy | None = None,
    ) -> None:
        self._remaining = tool_turns
        self._answer = answer
        self._descriptor = AgentDescriptor(
            agent_id="test-agent",
            name="Test",
            description="Test agent.",
            provider_id="fake",
            model_id="test-model",
            prompt_id="test-prompt",
            tool_ids=tool_ids,
            budget=budget or BudgetPolicy(),
        )
        self.stream_calls = 0
        self.exchanges: list[tuple[Message, ...]] = []
        self.closed = 0

    @property
    def descriptor(self) -> AgentDescriptor:
        return self._descriptor

    async def execute(self, request: AgentRequest, context: ExecutionContext) -> AgentResult:
        del request, context
        return AgentResult(
            message=Message(role=MessageRole.ASSISTANT, content=self._answer),
            agent_id="test-agent",
            model_id="test-model",
            provider_id="fake",
        )

    async def stream(
        self, request: AgentRequest, context: ExecutionContext
    ) -> AsyncIterator[CompletionChunk]:
        del context
        self.stream_calls += 1
        self.exchanges.append(request.tool_exchange)

        try:
            if self._remaining > 0:
                self._remaining -= 1
                yield CompletionChunk(
                    delta="",
                    tool_calls=(
                        ToolCall(call_id="c1", tool_id=TOOL_ID, arguments='{"query": "capital"}'),
                    ),
                    finish_reason="tool_calls",
                    usage=TokenUsage(prompt_tokens=10, completion_tokens=5),
                )
                return

            for word in self._answer.split(" "):
                yield CompletionChunk(delta=f"{word} ")
            yield CompletionChunk(
                delta="",
                finish_reason="stop",
                usage=TokenUsage(prompt_tokens=20, completion_tokens=7),
            )
        finally:
            self.closed += 1


def a_request() -> AgentRequest:
    return AgentRequest(input="what is the capital of France", model_id="test-model")


def build_executor(tool: RecordingTool) -> ToolExecutor:
    """Assemble an executor over one tool, with a fixed clock."""
    registry: KeyedRegistry[ToolProvider] = KeyedRegistry("tool")
    registry.register(tool.descriptor.tool_id, tool)

    class _Clock:
        def now(self) -> datetime:
            return datetime(2026, 1, 1, tzinfo=UTC)

        def monotonic(self) -> float:
            return 0.0

    return ToolExecutor(tools=registry, events=LoggingEventPublisher(), clock=_Clock())


@pytest.fixture(params=ENGINES, ids=["direct", "langgraph"])
def engine_factory(request: pytest.FixtureRequest) -> Callable[[ToolExecutor], WorkflowEngine]:
    factory: Callable[[ToolExecutor], WorkflowEngine] = request.param
    return factory


async def collect(stream: AsyncIterator[CompletionChunk]) -> list[CompletionChunk]:
    return [chunk async for chunk in stream]


class TestToolCallingWhileStreaming:
    async def test_a_streamed_tool_call_actually_runs_the_tool(
        self, engine_factory: Callable[[ToolExecutor], WorkflowEngine]
    ) -> None:
        """The defect this module exists for: the UI could not reach search."""
        tool = RecordingTool()
        agent = ToolStreamingAgent()
        engine = engine_factory(build_executor(tool))

        await collect(engine.stream(agent, a_request(), CONTEXT))

        assert tool.invocations == [{"query": "capital"}]

    async def test_the_answer_streams_after_the_tool_ran(
        self, engine_factory: Callable[[ToolExecutor], WorkflowEngine]
    ) -> None:
        tool = RecordingTool()
        agent = ToolStreamingAgent()
        engine = engine_factory(build_executor(tool))

        chunks = await collect(engine.stream(agent, a_request(), CONTEXT))

        assert "".join(chunk.delta for chunk in chunks).strip() == "Grounded answer."

    async def test_the_consumer_sees_one_completion_not_two(
        self, engine_factory: Callable[[ToolExecutor], WorkflowEngine]
    ) -> None:
        """A terminal chunk per model call would end the answer at the tool call.

        The tool-requesting stream's terminal chunk must be swallowed: forwarded,
        it tells the browser the turn finished before any prose was produced.
        """
        tool = RecordingTool()
        agent = ToolStreamingAgent()
        engine = engine_factory(build_executor(tool))

        chunks = await collect(engine.stream(agent, a_request(), CONTEXT))

        terminal = [chunk for chunk in chunks if chunk.finish_reason is not None]
        assert len(terminal) == 1
        assert terminal[0].finish_reason == "stop"

    async def test_the_tool_result_reaches_the_second_model_call(
        self, engine_factory: Callable[[ToolExecutor], WorkflowEngine]
    ) -> None:
        """Without the exchange the model answers from nothing and the tool was wasted."""
        tool = RecordingTool()
        agent = ToolStreamingAgent()
        engine = engine_factory(build_executor(tool))

        await collect(engine.stream(agent, a_request(), CONTEXT))

        second = agent.exchanges[1]
        assert [message.role for message in second] == [
            MessageRole.ASSISTANT,
            MessageRole.TOOL,
        ]
        assert "Paris is the capital." in second[1].content

    async def test_the_assistants_request_is_replayed_before_the_result(
        self, engine_factory: Callable[[ToolExecutor], WorkflowEngine]
    ) -> None:
        """A tool result answers a question the transcript has to contain."""
        tool = RecordingTool()
        agent = ToolStreamingAgent()
        engine = engine_factory(build_executor(tool))

        await collect(engine.stream(agent, a_request(), CONTEXT))

        assistant = agent.exchanges[1][0]
        assert [call.tool_id for call in assistant.tool_calls] == [TOOL_ID]

    async def test_usage_accumulates_across_both_model_calls(
        self, engine_factory: Callable[[ToolExecutor], WorkflowEngine]
    ) -> None:
        """Reporting only the last call under-reports what a tool turn cost."""
        tool = RecordingTool()
        agent = ToolStreamingAgent()
        engine = engine_factory(build_executor(tool))

        chunks = await collect(engine.stream(agent, a_request(), CONTEXT))

        usage = chunks[-1].usage
        assert usage is not None
        assert usage.prompt_tokens == 30  # 10 + 20
        assert usage.completion_tokens == 12  # 5 + 7


class TestWithoutTools:
    async def test_an_agent_declaring_no_tools_streams_unchanged(
        self, engine_factory: Callable[[ToolExecutor], WorkflowEngine]
    ) -> None:
        """One model call, no loop — the Milestone 03 path must not regress."""
        tool = RecordingTool()
        agent = ToolStreamingAgent(tool_turns=0, tool_ids=())
        engine = engine_factory(build_executor(tool))

        chunks = await collect(engine.stream(agent, a_request(), CONTEXT))

        assert agent.stream_calls == 1
        assert tool.invocations == []
        assert "".join(chunk.delta for chunk in chunks).strip() == "Grounded answer."


class TestBudget:
    async def test_the_iteration_ceiling_stops_a_model_that_never_settles(
        self, engine_factory: Callable[[ToolExecutor], WorkflowEngine]
    ) -> None:
        """An unbounded loop turns one request into an open-ended bill."""
        tool = RecordingTool()
        agent = ToolStreamingAgent(tool_turns=99)
        engine = engine_factory(build_executor(tool))

        chunks = await collect(engine.stream(agent, a_request(), CONTEXT))

        assert chunks[-1].finish_reason == "tool_limit"
        assert "unable to finish" in "".join(chunk.delta for chunk in chunks)


class TestCancellation:
    async def test_closing_the_stream_closes_the_agents(
        self, engine_factory: Callable[[ToolExecutor], WorkflowEngine]
    ) -> None:
        """ "Stop generating" must release the provider connection.

        Delegating with `async for` alone does not propagate `aclose()` — the
        agent's generator stays suspended holding an open connection until the
        garbage collector reaches it.
        """
        tool = RecordingTool()
        agent = ToolStreamingAgent(tool_turns=0)
        engine = engine_factory(build_executor(tool))

        stream = engine.stream(agent, a_request(), CONTEXT)
        await anext(stream)
        await stream.aclose()  # type: ignore[attr-defined]  # engines return generators

        assert agent.closed == 1


class TestBudgetPolicyIsHonoured:
    async def test_a_tool_invocation_cap_stops_further_calls(
        self, engine_factory: Callable[[ToolExecutor], WorkflowEngine]
    ) -> None:
        tool = RecordingTool()
        agent = ToolStreamingAgent(
            tool_turns=99,
            budget=BudgetPolicy(max_tool_invocations=1, max_model_calls=3),
        )
        engine = engine_factory(build_executor(tool))

        await collect(engine.stream(agent, a_request(), CONTEXT))

        assert len(tool.invocations) == 1
