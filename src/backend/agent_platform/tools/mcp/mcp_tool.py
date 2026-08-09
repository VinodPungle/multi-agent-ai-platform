"""One MCP tool, presented as an ordinary platform tool.

This class is the whole point of MCP support. Everything above it — the tool
executor, the tool loop, the workflow engine, the runtime, every agent — is
unchanged and cannot tell that this tool lives on another machine. It is
resolved through the registry, validated, timed, retried, logged, traced and
budgeted by exactly the same code path as the internet-search tool.

That is what ``CLAUDE.md`` asks for: *"Future additions should require only a new
adapter."* This is the adapter, and nothing else moved.

Two decisions worth stating outright:

**Tool ids are namespaced by server.** ``mcp.<server_id>.<tool_name>``. Two
servers exposing a tool called ``search`` is not unusual, and an id collision
would be resolved by whichever registered first — silently, and differently
depending on configuration order.

**Schemas are validated properly, not by hand.** A local tool has a schema its
author wrote and can be checked in a few lines. An MCP tool's schema arrives
from a server nobody here controls and can be arbitrarily deep. The
internet-search tool's docstring predicted exactly this trade reversing; this is
where it reverses, and `jsonschema` is the dependency it costs.
"""

from __future__ import annotations

from typing import Any

import jsonschema
from jsonschema.exceptions import SchemaError

from agent_platform.exceptions.base import PlatformError, ValidationError
from agent_platform.telemetry.logging import get_logger
from agent_platform.telemetry.tracing import get_tracer
from agent_platform.tools.mcp.session import MCPSession, MCPToolDefinition
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.contracts.health import ComponentHealth
from agent_platform_sdk.dto.tool import ToolDescriptor, ToolInvocation, ToolResult
from agent_platform_sdk.policies.retry import RetryPolicy
from agent_platform_sdk.types.enums import Capability, HealthStatus

__all__ = ["MCPTool", "mcp_tool_id"]

_logger = get_logger(__name__)
_tracer = get_tracer(__name__)


def mcp_tool_id(server_id: str, tool_name: str) -> str:
    """Return the platform-side id for a remote tool.

    Namespaced so two servers can each expose a ``search`` without one of them
    silently winning. Dots rather than colons because the id also travels as a
    tool name to models, and several providers reject names outside
    ``[A-Za-z0-9_.-]``.
    """
    return f"mcp.{server_id}.{tool_name}"


class MCPTool:
    """A tool hosted on an MCP server.

    Satisfies :class:`~agent_platform_sdk.interfaces.tool_provider.ToolProvider`
    structurally — it inherits nothing, per ADR-0004.
    """

    def __init__(
        self,
        session: MCPSession,
        definition: MCPToolDefinition,
        timeout_seconds: float = 30.0,
    ) -> None:
        """Create the adapter.

        Args:
            session: Connection to the server that hosts this tool.
            definition: What the server advertised at discovery.
            timeout_seconds: Declared on the descriptor and enforced by the
                runtime, not here — a tool policing its own timeout would be one
                of several implementations of the same policy.
        """
        self._session = session
        self._definition = definition
        self._timeout_seconds = timeout_seconds
        self._tool_id = mcp_tool_id(session.server_id, definition.name)

    # -- Provider ----------------------------------------------------------

    @property
    def provider_id(self) -> str:
        """Identifier this tool is registered under."""
        return self._tool_id

    @property
    def descriptor(self) -> ToolDescriptor:
        """Registry metadata, including the schema sent to models.

        The description comes from the server verbatim. Rewriting it would mean
        the platform inventing claims about a tool it did not implement, and a
        server that describes its tools badly is a problem to report rather than
        paper over.
        """
        return ToolDescriptor(
            tool_id=self._tool_id,
            description=self._definition.description,
            version="1.0",
            owner=f"mcp:{self._session.server_id}",
            input_schema=self._definition.input_schema,
            output_schema=self._definition.output_schema,
            timeout_seconds=self._timeout_seconds,
            # One retry only. A remote tool may have side effects the platform
            # cannot see — the protocol has no idempotency signal — so retrying
            # freely risks doing a thing twice. `CLAUDE.md`: never retry
            # non-idempotent operations automatically.
            retry_policy=RetryPolicy(max_attempts=1),
        )

    async def initialize(self) -> None:
        """Nothing to open. The session connects per call by design."""

    async def health_check(self) -> ComponentHealth:
        """Report whether the server still answers.

        Lists tools rather than calling one: listing is free and side-effect
        free, whereas a health check that invoked a tool would perform whatever
        that tool does, on a schedule, forever.
        """
        try:
            tools = await self._session.list_tools()
        except PlatformError as error:
            return ComponentHealth(
                name=self._tool_id,
                # DEGRADED, not UNHEALTHY: an unreachable optional tool must not
                # fail readiness and take the whole replica out of rotation. The
                # agent loses a capability and can say so.
                status=HealthStatus.DEGRADED,
                detail=f"MCP server unreachable: {error.message}",
            )

        if not any(tool.name == self._definition.name for tool in tools):
            return ComponentHealth(
                name=self._tool_id,
                status=HealthStatus.DEGRADED,
                detail=(
                    f"MCP server no longer advertises {self._definition.name!r}. "
                    "Calls will fail until the platform is restarted and rediscovers."
                ),
            )

        return ComponentHealth(
            name=self._tool_id,
            status=HealthStatus.HEALTHY,
            detail=f"MCP tool {self._definition.name!r} on {self._session.server_id!r}.",
        )

    def supports(self, capability: Capability) -> bool:
        """Declare nothing. A tool's capability is described by its schema."""
        del capability
        return False

    async def close(self) -> None:
        """Nothing to release. Sessions do not outlive a call."""

    # -- Tool --------------------------------------------------------------

    async def validate(self, invocation: ToolInvocation) -> None:
        """Check the arguments against the server's own schema.

        Locally, before a request is sent. A remote tool may have side effects,
        so arguments that cannot possibly be valid should not reach it — and the
        error a model gets back from a schema check is far more actionable than
        most servers' own.

        A malformed *schema* is treated as no schema. That is the server's bug,
        and refusing every call because of it would disable a tool that might
        work perfectly well.

        Raises:
            ValidationError: the arguments do not satisfy the declared schema.
        """
        schema = self._definition.input_schema
        if not schema:
            return

        try:
            jsonschema.validate(instance=invocation.arguments, schema=schema)
        except SchemaError:
            _logger.warning(
                "mcp.invalid_schema",
                tool_id=self._tool_id,
                detail="The server advertised an invalid JSON Schema; skipping validation.",
            )
        except jsonschema.ValidationError as error:
            # `error.message` describes the mismatch; the full exception
            # includes the whole instance, which is user content and would end
            # up in a log line.
            message = f"{self._tool_id} arguments are invalid: {error.message}"
            raise ValidationError(message, details={"tool_id": self._tool_id}) from error

    async def execute(
        self,
        invocation: ToolInvocation,
        context: ExecutionContext,
    ) -> ToolResult:
        """Call the remote tool and return a structured result."""
        with _tracer.start_as_current_span("tool.mcp") as span:
            span.set_attribute("tool.id", self._tool_id)
            span.set_attribute("mcp.server_id", self._session.server_id)
            span.set_attribute("mcp.tool_name", self._definition.name)
            # Arguments are not a span attribute: they are user content, and
            # spans are exported to systems with different retention and access
            # rules than the request itself.

            try:
                outcome = await self._session.call_tool(
                    self._definition.name,
                    invocation.arguments,
                )
            except PlatformError as error:
                # Returned rather than raised. An agent that knows a tool is
                # unavailable can say so and carry on; an exception would abort
                # a turn over one optional capability.
                _logger.warning(
                    "mcp.call_failed",
                    tool_id=self._tool_id,
                    error_type=type(error).__name__,
                    **context.to_log_fields(),
                )
                return ToolResult(
                    tool_id=self._tool_id,
                    call_id=invocation.call_id,
                    succeeded=False,
                    error_message=error.message,
                )

            span.set_attribute("mcp.is_error", outcome.is_error)

            if outcome.is_error:
                # The tool ran and reported a problem. Also a value rather than
                # an exception, and for a stronger reason: this is exactly the
                # kind of failure a model can recover from by trying different
                # arguments.
                return ToolResult(
                    tool_id=self._tool_id,
                    call_id=invocation.call_id,
                    succeeded=False,
                    error_message=outcome.text or "The MCP tool reported an error.",
                )

            return ToolResult(
                tool_id=self._tool_id,
                call_id=invocation.call_id,
                succeeded=True,
                output=self._to_output(outcome.text, outcome.structured_content),
            )

    @staticmethod
    def _to_output(text: str, structured: dict[str, Any] | None) -> dict[str, Any]:
        """Shape the outcome into the tool result payload.

        Both forms are carried when both exist. They are not redundant: the text
        is what a model reads, and the structured content is what anything
        programmatic downstream would use.
        """
        output: dict[str, Any] = {"content": text}
        if structured is not None:
            output["structured"] = structured
        return output

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"MCPTool(tool_id={self._tool_id!r})"
