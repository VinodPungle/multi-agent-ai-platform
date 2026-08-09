"""What the platform needs from an MCP server, and nothing more.

The MCP SDK's ``ClientSession`` exposes prompts, resources, subscriptions,
sampling, elicitation and completion. The platform uses two of those verbs. This
module names them, in platform-owned types, so that:

* the SDK is importable from exactly one module and nothing above it can
  accidentally depend on ``mcp.types`` (``CLAUDE.md``: provider SDKs belong
  inside infrastructure);
* the adapter is testable against a fake that is a few lines rather than a
  protocol implementation;
* an SDK upgrade that renames things — as 2.0 renamed ``streamablehttp_client``
  and ``inputSchema`` — breaks one file, loudly, instead of leaking.

The last point is not hypothetical. The rename above was found by introspecting
the installed package rather than trusting memory of the older API, which is the
only reliable way to write against a moving SDK.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["MCPSession", "MCPToolDefinition", "MCPToolOutcome"]


class MCPToolDefinition(BaseModel):
    """One tool as a server advertises it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(description="Tool name as the server knows it.")
    description: str = Field(
        default="",
        description=(
            "What the tool does. Becomes prompt material verbatim — it is what "
            "a model reads to decide whether to call it — so a server with a "
            "vague description produces an agent that calls it for everything."
        ),
    )
    input_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON Schema for the arguments, supplied by the server.",
    )
    output_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON Schema for the result, where the server declares one.",
    )


class MCPToolOutcome(BaseModel):
    """The result of calling a remote tool.

    ``is_error`` is the protocol's own notion of a *tool-level* failure — the
    tool ran and reported a problem the model should reason about. It is
    deliberately distinct from a transport failure, which raises, because the
    two need different handling: one is an answer, the other is an outage.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(
        default="",
        description="Text content, joined. What a model can actually read.",
    )
    structured_content: dict[str, Any] | None = Field(
        default=None,
        description="The server's structured result, where it returned one.",
    )
    is_error: bool = Field(
        default=False,
        description="The tool reported failure. Not a transport error.",
    )


@runtime_checkable
class MCPSession(Protocol):
    """A connection to one MCP server.

    Lifetime is the implementation's business. The HTTP implementation connects
    per call rather than holding a session open — see
    :mod:`agent_platform.tools.mcp.streamable_http_session` for why that trade
    was made and what it costs.
    """

    @property
    def server_id(self) -> str:
        """Identifier for the configured server, used in ids and log fields."""
        ...

    async def list_tools(self) -> tuple[MCPToolDefinition, ...]:
        """Return every tool the server advertises.

        Raises:
            ProviderError: the server is unreachable or answered unusably.
        """
        ...

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> MCPToolOutcome:
        """Invoke a tool and return its outcome.

        Raises:
            ProviderError: the call could not be made or completed. A tool that
                ran and *failed* is not this — it comes back with
                ``is_error=True``, because the agent should see it.
        """
        ...
