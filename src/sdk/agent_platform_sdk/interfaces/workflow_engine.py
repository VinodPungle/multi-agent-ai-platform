"""Workflow engine contract.

Separates *what* is executed from *how* execution is orchestrated
(``architecture.md`` §12). Today one agent answers one turn. Later, several agents
collaborate — planner, researcher, writer, reviewer — with branching, retries,
human approval steps and checkpointing between them.

That growth happens inside an engine implementation. The runtime's call site does
not change, and neither does any agent, because neither knows how many steps
there are.

Why the abstraction exists rather than calling LangGraph directly
    LangGraph is a good fit and is the initial implementation. It is also a young
    library with a moving API, and it brings `langchain-core` with it. Depending
    on it from the runtime would put a third-party graph model in the middle of
    the platform's core, where replacing it later would mean touching the runtime,
    every agent, and every test that exercises orchestration.

    The cost of the seam is one protocol and one adapter. See ADR-0009.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.dto.completion import CompletionChunk
from agent_platform_sdk.dto.execution import AgentRequest, AgentResult
from agent_platform_sdk.interfaces.agent import Agent

__all__ = ["WorkflowEngine"]


@runtime_checkable
class WorkflowEngine(Protocol):
    """Orchestrates the execution of one or more agents."""

    @property
    def engine_id(self) -> str:
        """Identifier of this engine, reported in telemetry.

        Named in spans and log records so that a latency change after an engine
        swap is attributable rather than mysterious.
        """
        ...

    async def execute(
        self,
        agent: Agent,
        request: AgentRequest,
        context: ExecutionContext,
    ) -> AgentResult:
        """Run ``agent`` to completion and return its result.

        Takes a single agent because that is the whole of Milestone 03. A
        multi-agent signature would be a shape invented before the requirement,
        and the requirement is what determines whether the unit of work is a
        list, a graph, or a named workflow resolved from a registry.

        Raises:
            WorkflowError: orchestration itself failed. A failure *inside* the
                agent propagates as the agent raised it, so a provider outage
                stays a ``ProviderError`` and does not become an opaque
                workflow failure.
        """
        ...

    def stream(
        self,
        agent: Agent,
        request: AgentRequest,
        context: ExecutionContext,
    ) -> AsyncIterator[CompletionChunk]:
        """Run ``agent``, yielding chunks as they are produced.

        An engine that cannot stream — a batch or approval-gated workflow — should
        raise rather than silently buffer and emit one chunk at the end. A caller
        that asked for a stream and received the whole answer at once has been
        given something that looks like streaming and is not.
        """
        ...
