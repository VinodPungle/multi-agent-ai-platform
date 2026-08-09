"""Discovering the tools a server offers, at startup.

Discovery happens once, during startup, and produces ordinary
:class:`~agent_platform.tools.mcp.mcp_tool.MCPTool` instances that go into the
tool registry alongside every local tool.

Why at startup rather than per request
    The catalogue is prompt material: a tool's description is sent to the model
    so it can decide whether to call it. Discovering per request would make the
    prompt vary with a third party's deployment schedule, so two identical
    questions could get different answers for reasons nobody could see in the
    request. It would also put a network round trip in front of every turn.

    The cost is that a tool added to a server mid-run is not seen until the
    platform restarts. That is the right trade for a prompt input, and the
    health check reports the opposite case — a tool that has *disappeared* —
    because that one produces failures rather than a missing capability.

Why a failure here does not stop the platform
    An MCP server is a third party. Refusing to start because someone else's
    service is down would hand them an outage switch for a platform whose core
    function does not depend on them. The failure is logged loudly and the
    platform starts without those tools.

    Configuration mistakes are different and are *not* forgiven — see
    ``MCPServerSettings``, which rejects a server with no URL at startup.
"""

from __future__ import annotations

from agent_platform.configuration.settings import MCPServerSettings
from agent_platform.exceptions.base import PlatformError
from agent_platform.telemetry.logging import get_logger
from agent_platform.tools.mcp.mcp_tool import MCPTool
from agent_platform.tools.mcp.session import MCPSession
from agent_platform.tools.mcp.streamable_http_session import StreamableHTTPMCPSession
from agent_platform_sdk.interfaces.tool_provider import ToolProvider

__all__ = ["build_mcp_session", "discover_mcp_tools"]

_logger = get_logger(__name__)


def build_mcp_session(server: MCPServerSettings) -> MCPSession:
    """Return a session for a configured server.

    Separate from discovery so a test can substitute a session without touching
    the network, and so a second transport becomes a branch here rather than a
    change to everything downstream.
    """
    return StreamableHTTPMCPSession(
        server_id=server.server_id,
        url=str(server.url),
        # Unwrapped at the single point of use. It travels as a `SecretStr`
        # everywhere else so it cannot reach a log by accident.
        headers=(
            {server.auth_header_name: server.auth_header_value.get_secret_value()}
            if server.auth_header_value.get_secret_value()
            else {}
        ),
        timeout_seconds=server.timeout_seconds,
    )


async def discover_mcp_tools(sessions: tuple[MCPSession, ...]) -> tuple[ToolProvider, ...]:
    """Return one tool per capability advertised by each server.

    A server that cannot be reached contributes nothing and does not prevent the
    others — or the platform — from starting.
    """
    discovered: list[ToolProvider] = []

    for session in sessions:
        try:
            definitions = await session.list_tools()
        except PlatformError as error:
            _logger.warning(
                "mcp.discovery_failed",
                server_id=session.server_id,
                error_type=type(error).__name__,
                detail=(
                    "The platform started without this server's tools. Agents "
                    "configured to use them will report the tool as unavailable."
                ),
            )
            continue

        for definition in definitions:
            discovered.append(MCPTool(session=session, definition=definition))

        _logger.info(
            "mcp.tools_discovered",
            server_id=session.server_id,
            tool_count=len(definitions),
            tools=[definition.name for definition in definitions],
        )

    return tuple(discovered)
