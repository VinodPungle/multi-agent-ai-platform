"""The engine that does nothing.

Executes one agent by calling it. No graph, no state machine, no dependency
beyond the SDK.

It exists for three reasons, and the first is the important one:

**It proves the abstraction is not LangGraph-shaped.** An interface with exactly
one implementation is indistinguishable from that implementation's API. A second
implementation, written against the same protocol and sharing no code with the
first, is what demonstrates the seam is real — and it is why the LangGraph
adapter could be replaced without the runtime noticing.

**It is the reference for what an engine must do.** Twenty lines, no framework:
anyone adding a third engine can read this and know the contract.

**It is a working fallback.** ``PLATFORM_WORKFLOW__ENGINE=direct`` runs the
platform with no graph library involved, which is a diagnosis tool when
orchestration itself is suspected.

It will not grow. Multi-agent workflows, branching and checkpointing belong in an
engine built for them; this one stays trivial so it stays a reference.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.dto.completion import CompletionChunk
from agent_platform_sdk.dto.execution import AgentRequest, AgentResult
from agent_platform_sdk.interfaces.agent import Agent

__all__ = ["DirectWorkflowEngine"]


class DirectWorkflowEngine:
    """Runs a single agent with no orchestration layer.

    Satisfies :class:`~agent_platform_sdk.interfaces.workflow_engine.WorkflowEngine`
    structurally.
    """

    @property
    def engine_id(self) -> str:
        """Identifier reported in telemetry."""
        return "direct"

    async def execute(
        self,
        agent: Agent,
        request: AgentRequest,
        context: ExecutionContext,
    ) -> AgentResult:
        """Call the agent and return what it produced.

        Failures propagate unchanged. There is no orchestration here that could
        fail, so wrapping an agent's error in a ``WorkflowError`` would only
        hide which layer actually broke.
        """
        return await agent.execute(request, context)

    def stream(
        self,
        agent: Agent,
        request: AgentRequest,
        context: ExecutionContext,
    ) -> AsyncIterator[CompletionChunk]:
        """Return the agent's chunk stream directly.

        Not an async generator wrapping the agent's — returning the iterator
        itself keeps ``aclose()`` reaching the agent, so cancelling a stream
        still releases the provider connection.
        """
        return agent.stream(request, context)
