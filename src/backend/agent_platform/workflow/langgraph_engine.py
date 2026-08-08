"""LangGraph workflow engine.

The only module in the platform that imports LangGraph. Everything else depends
on :class:`~agent_platform_sdk.interfaces.workflow_engine.WorkflowEngine`, which
is what makes the library replaceable — the same containment rule the provider
packages follow for vendor SDKs (ADR-0006), applied to orchestration.

What the graph looks like today
    One node. A single agent answering a single turn does not need a graph, and
    pretending otherwise would produce ceremony without benefit.

Why build it anyway
    Because the *shape* is what Milestone 04 and beyond need, and retrofitting it
    later means rewriting the runtime's execution path rather than adding nodes.
    The nodes that follow — tool planning, tool execution, evaluation, a reviewer
    agent, a human approval gate — attach to this graph. The runtime's call site
    does not change when they do.

    ::

        M03 (now)          prepare ─▶ agent ─▶ END
        M04                prepare ─▶ agent ─▶ tools ─┐
                                       ▲──────────────┘
        later              ... ─▶ evaluate ─▶ approve ─▶ END

State is a ``TypedDict`` rather than a Pydantic model because that is what
LangGraph's reducers expect, and it never leaves this module: the adapter
converts platform contracts in and out at its boundary, so no LangGraph type
reaches an agent or the runtime.

Streaming does not go through the graph. LangGraph streams *state updates*
between nodes, not tokens from within one — so routing tokens through it would
mean buffering the whole answer in a node and emitting it as one update, which is
the thing streaming exists to avoid. The adapter therefore delegates streaming to
the agent directly and is explicit about it, rather than appearing to stream.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from agent_platform.exceptions.base import PlatformError, WorkflowError
from agent_platform.telemetry.logging import get_logger
from agent_platform.telemetry.tracing import get_tracer
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.dto.completion import CompletionChunk
from agent_platform_sdk.dto.execution import AgentRequest, AgentResult
from agent_platform_sdk.interfaces.agent import Agent

__all__ = ["LangGraphWorkflowEngine"]

_logger = get_logger(__name__)
_tracer = get_tracer(__name__)


class _WorkflowState(TypedDict, total=False):
    """State passed between graph nodes.

    Confined to this module. ``result`` is the node's output; ``failure`` carries
    an exception the node caught, so a failure travels as state rather than
    unwinding the graph — which is what lets a future error-handling node see it.
    """

    request: AgentRequest
    context: ExecutionContext
    result: AgentResult | None
    failure: PlatformError | None


class LangGraphWorkflowEngine:
    """Orchestrates agent execution as a LangGraph state graph.

    Satisfies :class:`WorkflowEngine` structurally.

    A graph is compiled per execution rather than cached. Compilation is cheap
    for a graph this size, and caching would mean keying on agent identity and
    invalidating when a descriptor changes — complexity bought for a saving that
    has not been measured. Revisit when the graph is large enough to matter.
    """

    @property
    def engine_id(self) -> str:
        """Identifier reported in telemetry."""
        return "langgraph"

    async def execute(
        self,
        agent: Agent,
        request: AgentRequest,
        context: ExecutionContext,
    ) -> AgentResult:
        """Run ``agent`` as a compiled graph and return its result.

        Raises:
            WorkflowError: the graph itself failed, or completed without
                producing a result.
            PlatformError: whatever the agent raised, re-raised unchanged — a
                provider outage must stay a ``ProviderError`` rather than
                becoming an opaque orchestration failure.
        """
        with _tracer.start_as_current_span("workflow.execute") as span:
            span.set_attribute("workflow.engine", self.engine_id)
            span.set_attribute("workflow.agent_id", agent.descriptor.agent_id)
            span.set_attribute("workflow.node_count", 1)

            graph = self._compile(agent)

            try:
                final_state: dict[str, Any] = await graph.ainvoke(
                    _WorkflowState(request=request, context=context, result=None, failure=None)
                )
            except Exception as error:
                # A failure escaping `ainvoke` is LangGraph's own — the agent
                # node catches everything it can. Anything here is orchestration.
                message = f"Workflow execution failed: {type(error).__name__}."
                raise WorkflowError(
                    message,
                    details={"engine": self.engine_id, "agent_id": agent.descriptor.agent_id},
                ) from error

            # Annotated because `ainvoke` returns `dict[str, Any]`: LangGraph
            # cannot express the state type through compilation, so this is
            # where the graph's untyped boundary is converted back.
            failure: PlatformError | None = final_state.get("failure")
            if failure is not None:
                raise failure

            result: AgentResult | None = final_state.get("result")
            if result is None:
                message = (
                    "Workflow completed without producing a result. "
                    "A node returned no output, which is a graph definition error."
                )
                raise WorkflowError(message, details={"engine": self.engine_id})

            return result

    def stream(
        self,
        agent: Agent,
        request: AgentRequest,
        context: ExecutionContext,
    ) -> AsyncIterator[CompletionChunk]:
        """Stream the agent's output.

        Bypasses the graph deliberately — see the module docstring. Returns the
        agent's iterator rather than wrapping it, so ``aclose()`` still reaches
        the agent and cancelling a stream releases the provider connection.
        """
        _logger.debug(
            "workflow.stream_direct",
            engine=self.engine_id,
            agent_id=agent.descriptor.agent_id,
            detail="Token streaming bypasses the graph; LangGraph streams state, not tokens.",
        )
        return agent.stream(request, context)

    @staticmethod
    def _compile(agent: Agent) -> Any:  # noqa: ANN401 - LangGraph's compiled type is not exported
        """Build and compile the graph for ``agent``.

        One node today. Adding a node is a `add_node` plus an edge here, and
        nothing outside this method changes.
        """

        async def run_agent(state: _WorkflowState) -> _WorkflowState:
            """Execute the agent, capturing a platform failure as state."""
            try:
                result = await agent.execute(state["request"], state["context"])
            except PlatformError as error:
                # Carried as state rather than raised, so the graph completes and
                # a future error-handling node can inspect it. `execute` re-raises
                # it unchanged, so callers see no difference today.
                return {"failure": error}
            return {"result": result}

        builder: StateGraph[_WorkflowState, None, _WorkflowState, _WorkflowState] = StateGraph(
            _WorkflowState
        )
        builder.add_node("agent", run_agent)
        builder.add_edge(START, "agent")
        builder.add_edge("agent", END)

        return builder.compile()
