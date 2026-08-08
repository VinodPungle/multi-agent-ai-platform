"""Agent contract.

An agent reasons within its assigned domain and does nothing else
(``CLAUDE.md``). Everything around that — memory, prompt resolution, model
selection, tool execution, retries, budgets, telemetry — belongs to the runtime.

What that rules out, concretely. An agent must not:

* import a provider, or name one
* read a prompt file, or hold a prompt string
* load or write conversation memory
* call another agent
* apply a retry or timeout policy of its own

Each of those, done inside an agent, is done once per agent — so the second agent
either copies it or quietly differs. That is what makes a "God Agent", and it
starts with one convenience.

The one dependency an agent legitimately has is
:class:`~agent_platform_sdk.interfaces.llm_gateway.LLMGateway`, because producing
text is its job. Even that is the gateway, never a provider.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.dto.agent import AgentDescriptor
from agent_platform_sdk.dto.completion import CompletionChunk
from agent_platform_sdk.dto.execution import AgentRequest, AgentResult

__all__ = ["Agent"]


@runtime_checkable
class Agent(Protocol):
    """One specialised reasoner."""

    @property
    def descriptor(self) -> AgentDescriptor:
        """Declarative definition of this agent.

        The descriptor is data, so what an agent *is* — its model, its prompt,
        its tools, its budget — is configuration the runtime reads, not a
        property of the class.
        """
        ...

    async def execute(self, request: AgentRequest, context: ExecutionContext) -> AgentResult:
        """Produce a complete response.

        Raises:
            ProviderError: the model call failed.
            ValidationError: the request cannot be served as written.
        """
        ...

    def stream(
        self,
        request: AgentRequest,
        context: ExecutionContext,
    ) -> AsyncIterator[CompletionChunk]:
        """Produce a response incrementally.

        Yields the same provider-neutral chunks a provider does, rather than an
        agent-specific event type. That keeps the streaming path uniform from
        provider to browser: one shape, translated once at the API boundary.

        Declared as a regular method returning an ``AsyncIterator``, so an
        implementation may be an async generator or an explicit iterator.
        """
        ...
