"""Tool contract.

Tools are executed by the runtime, never by an agent (``architecture.md`` §33).
The same interface backs local implementations, REST APIs, Azure Functions and —
from a future adapter — MCP servers, so adding a backing technology means adding
an adapter, not changing the runtime.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.dto.tool import ToolDescriptor, ToolInvocation, ToolResult
from agent_platform_sdk.interfaces.provider import Provider

__all__ = ["ToolProvider"]


@runtime_checkable
class ToolProvider(Provider, Protocol):
    """A single executable capability exposed to agents."""

    @property
    def descriptor(self) -> ToolDescriptor:
        """Registry metadata for this tool, including its input/output schemas."""
        ...

    async def validate(self, invocation: ToolInvocation) -> None:
        """Check ``invocation`` against the descriptor's input schema.

        Separate from :meth:`execute` so the runtime can reject bad arguments
        before spending a timeout budget or causing a side effect.

        Raises:
            ValidationError: when the arguments do not satisfy the schema.
        """
        ...

    async def execute(
        self,
        invocation: ToolInvocation,
        context: ExecutionContext,
    ) -> ToolResult:
        """Run the tool and return a structured result.

        Expected failures — a 404 from an upstream API, a query with no matches
        — belong in the returned :class:`ToolResult` with ``succeeded=False``,
        because the agent should reason about them. Raising is reserved for
        conditions the agent cannot act on.
        """
        ...
