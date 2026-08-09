"""Delegating work to another agent.

The interesting behaviour is not that delegation works — it is what happens when
it should not: a cycle, an agent that was never permitted, a specialist that
fails. Each of those either costs money or ends a user's turn, and each is
tested here.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_platform.tools.delegate_tool import DELEGATE_TOOL_ID, DelegateToAgentTool
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.dto.execution import AgentResult
from agent_platform_sdk.dto.message import Message
from agent_platform_sdk.dto.tool import ToolInvocation
from agent_platform_sdk.interfaces.tool_provider import ToolProvider
from agent_platform_sdk.types.enums import HealthStatus, MessageRole

pytestmark = pytest.mark.unit

CONTEXT = ExecutionContext()


class RecordingRuntime:
    """Stands in for the runtime, recording what it was asked to run."""

    def __init__(
        self,
        answer: str = "The specialist's answer.",
        failure: Exception | None = None,
    ) -> None:
        self._answer = answer
        self._failure = failure
        self.prepared: list[tuple[str, str, ExecutionContext]] = []

    async def prepare(
        self,
        agent_id: str,
        user_input: str,
        context: ExecutionContext,
        conversation_id: str | None = None,
    ) -> tuple[str, ExecutionContext]:
        if self._failure is not None:
            raise self._failure
        self.prepared.append((agent_id, user_input, context))
        assert conversation_id is None, "a delegate must not join the user's conversation"
        return (agent_id, context)

    async def execute(self, turn: tuple[str, ExecutionContext]) -> AgentResult:
        agent_id, _ = turn
        return AgentResult(
            message=Message(role=MessageRole.ASSISTANT, content=self._answer),
            agent_id=agent_id,
            model_id="test-model",
            provider_id="fake",
        )


def build_tool(runtime: RecordingRuntime, **overrides: Any) -> DelegateToAgentTool:  # noqa: ANN401
    fields: dict[str, Any] = {
        "runtime_provider": lambda: runtime,
        "delegatable_agent_ids": ("research-agent",),
    }
    fields.update(overrides)
    return DelegateToAgentTool(**fields)


def an_invocation(**arguments: Any) -> ToolInvocation:  # noqa: ANN401
    return ToolInvocation(
        tool_id=DELEGATE_TOOL_ID,
        arguments=arguments or {"agent_id": "research-agent", "task": "find X"},
        call_id="call-1",
    )


class TestContractConformance:
    def test_it_satisfies_the_tool_contract(self) -> None:
        assert isinstance(build_tool(RecordingRuntime()), ToolProvider)

    def test_the_description_names_the_available_agents(self) -> None:
        """That text is the only basis a model has for choosing a specialist."""
        tool = build_tool(RecordingRuntime())

        assert "research-agent" in tool.descriptor.description


class TestDelegation:
    async def test_it_runs_the_requested_agent(self) -> None:
        runtime = RecordingRuntime()
        tool = build_tool(runtime)

        result = await tool.execute(an_invocation(), CONTEXT)

        assert result.succeeded is True
        assert runtime.prepared[0][0] == "research-agent"

    async def test_the_task_reaches_the_specialist_verbatim(self) -> None:
        runtime = RecordingRuntime()
        tool = build_tool(runtime)

        await tool.execute(
            an_invocation(agent_id="research-agent", task="what changed in Python 3.14"),
            CONTEXT,
        )

        assert runtime.prepared[0][1] == "what changed in Python 3.14"

    async def test_the_answer_comes_back(self) -> None:
        tool = build_tool(RecordingRuntime(answer="Paris."))

        result = await tool.execute(an_invocation(), CONTEXT)

        assert result.output is not None
        assert result.output["answer"] == "Paris."

    async def test_usage_is_reported_so_the_turn_can_be_costed(self) -> None:
        """Without it a multi-agent request reports only the coordinator's tokens."""
        tool = build_tool(RecordingRuntime())

        result = await tool.execute(an_invocation(), CONTEXT)

        assert result.output is not None
        assert "prompt_tokens" in result.output
        assert "completion_tokens" in result.output


class TestCycleProtection:
    async def test_depth_increases_for_the_delegate(self) -> None:
        runtime = RecordingRuntime()
        tool = build_tool(runtime)

        await tool.execute(an_invocation(), CONTEXT)

        assert runtime.prepared[0][2].delegation_depth == 1

    async def test_delegation_is_refused_at_the_limit(self) -> None:
        """A → B → A costs a budget before anything stops it, unless this does."""
        runtime = RecordingRuntime()
        tool = build_tool(runtime, max_delegation_depth=2)

        result = await tool.execute(an_invocation(), CONTEXT.derive(delegation_depth=2))

        assert result.succeeded is False
        assert "depth" in (result.error_message or "").lower()
        assert runtime.prepared == []

    async def test_the_refusal_is_reported_not_raised(self) -> None:
        """The caller can still answer with what it has; raising discards the turn."""
        tool = build_tool(RecordingRuntime(), max_delegation_depth=1)

        result = await tool.execute(an_invocation(), CONTEXT.derive(delegation_depth=1))

        assert result.succeeded is False
        assert result.error_message

    async def test_a_chain_is_bounded_not_just_one_hop(self) -> None:
        """Depth travels on the context, so it survives every hop it takes."""
        runtime = RecordingRuntime()
        tool = build_tool(runtime, max_delegation_depth=3)

        first = await tool.execute(an_invocation(), CONTEXT)
        depth_after_first = runtime.prepared[0][2]

        second = await tool.execute(an_invocation(), depth_after_first)
        third = await tool.execute(an_invocation(), runtime.prepared[1][2])
        fourth = await tool.execute(an_invocation(), runtime.prepared[2][2])

        assert first.succeeded is True
        assert second.succeeded is True
        assert third.succeeded is True
        assert fourth.succeeded is False


class TestAuthorisation:
    async def test_an_unlisted_agent_is_refused(self) -> None:
        """Reaching anything registered is how one agent's permissions spread."""
        runtime = RecordingRuntime()
        tool = build_tool(runtime, delegatable_agent_ids=("research-agent",))

        result = await tool.execute(an_invocation(agent_id="coding-agent", task="x"), CONTEXT)

        assert result.succeeded is False
        assert "not available" in (result.error_message or "")
        assert runtime.prepared == []

    async def test_the_refusal_names_the_real_options(self) -> None:
        """A model that guessed a name should be told the right ones."""
        tool = build_tool(RecordingRuntime())

        result = await tool.execute(an_invocation(agent_id="nope", task="x"), CONTEXT)

        assert "research-agent" in (result.error_message or "")


class TestFailureHandling:
    async def test_a_failing_specialist_does_not_end_the_turn(self) -> None:
        tool = build_tool(RecordingRuntime(failure=RuntimeError("model down")))

        result = await tool.execute(an_invocation(), CONTEXT)

        assert result.succeeded is False
        assert "could not complete" in (result.error_message or "")

    async def test_the_specialists_internals_do_not_leak(self) -> None:
        """A nested agent's error text is not the caller's business."""
        tool = build_tool(
            RecordingRuntime(failure=RuntimeError("connection to https://internal/secret failed"))
        )

        result = await tool.execute(an_invocation(), CONTEXT)

        assert "internal" not in (result.error_message or "")


class TestValidation:
    async def test_an_empty_task_is_rejected_before_anything_is_spent(self) -> None:
        tool = build_tool(RecordingRuntime())

        with pytest.raises(ValueError, match="non-empty"):
            await tool.validate(an_invocation(agent_id="research-agent", task="   "))


class TestHealth:
    async def test_it_reports_which_agents_are_reachable(self) -> None:
        health = await build_tool(RecordingRuntime()).health_check()

        assert health.status is HealthStatus.HEALTHY
        assert "research-agent" in (health.detail or "")

    async def test_no_delegatable_agents_is_degraded_not_healthy(self) -> None:
        """The tool is registered and every call will be refused. That is not healthy."""
        tool = build_tool(RecordingRuntime(), delegatable_agent_ids=())

        health = await tool.health_check()

        assert health.status is HealthStatus.DEGRADED
