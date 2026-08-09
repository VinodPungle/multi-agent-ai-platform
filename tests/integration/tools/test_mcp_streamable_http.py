"""The MCP client, against a real server over real HTTP.

Everything else in the MCP package is tested through a fake session, which is
honest — that protocol is three methods the platform owns. This file exists
because the one module those tests cannot cover is the one that matters most:
:mod:`agent_platform.tools.mcp.streamable_http_session`, which is entirely SDK
behaviour.

Writing that module already turned up two things memory would have got wrong —
``streamablehttp_client`` was renamed ``streamable_http_client`` at 2.0, and
``inputSchema`` became ``input_schema``. Both were found by introspecting the
installed package. This test is the guard for the next such change: it starts an
actual MCP server, serves it with uvicorn on a real port, and drives it through
the platform's own session.

No network access leaves the machine — the server is in-process on a loopback
port — so this runs anywhere the rest of the suite does.
"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator

import pytest
import uvicorn
from mcp.server.mcpserver import MCPServer

from agent_platform.exceptions.base import ProviderError
from agent_platform.tools.mcp.mcp_tool import MCPTool
from agent_platform.tools.mcp.session import MCPSession
from agent_platform.tools.mcp.streamable_http_session import StreamableHTTPMCPSession
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.dto.tool import ToolInvocation
from agent_platform_sdk.interfaces.tool_provider import ToolProvider
from agent_platform_sdk.types.enums import HealthStatus

pytestmark = pytest.mark.integration

CONTEXT = ExecutionContext()


def _closed_port() -> int:
    """Return a loopback port with nothing listening on it.

    Only for the unreachable-server tests, which need a connection to be
    refused. Not used to place the server: see :func:`mcp_server_url`.
    """
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


def _build_server() -> MCPServer:
    server: MCPServer = MCPServer(name="test-weather-server")

    @server.tool()
    def forecast(city: str, days: int = 1) -> str:
        """Return a weather forecast for a city."""
        return f"{city}: sunny for {days} day(s)."

    @server.tool()
    def explode() -> str:
        """Always fails, so tool-level errors can be observed."""
        message = "the barometer is broken"
        raise RuntimeError(message)

    return server


@pytest.fixture
async def mcp_server_url() -> AsyncIterator[str]:
    """Serve a real MCP server on a loopback port for the duration of a test.

    **uvicorn binds port 0 and the port is read back afterwards**, rather than
    the test choosing a free port and handing it over. Choosing first leaves a
    window between "this port was free" and "uvicorn bound it", and anything
    else on the machine can take it in between. That window is invisible when
    this file runs alone and opens up under the full suite, where many other
    sockets are in play — which is exactly how it was found: these tests passed
    in isolation and failed intermittently in a complete run.
    """
    config = uvicorn.Config(
        _build_server().streamable_http_app(),
        host="127.0.0.1",
        port=0,
        log_level="error",
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())

    # Poll rather than sleep a fixed interval: a fixed wait is either flaky on a
    # loaded machine or slower than it needs to be on an idle one. An
    # `asyncio.Event` would be better and uvicorn does not offer one — `started`
    # is a plain flag, so there is nothing to await.
    while not server.started:  # noqa: ASYNC110 - uvicorn exposes a flag, not an event
        await asyncio.sleep(0.02)

    port: int = server.servers[0].sockets[0].getsockname()[1]

    try:
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        server.should_exit = True
        await task


@pytest.fixture
def session(mcp_server_url: str) -> StreamableHTTPMCPSession:
    return StreamableHTTPMCPSession(server_id="weather", url=mcp_server_url)


class TestContractConformance:
    def test_it_satisfies_the_session_protocol(
        self,
        session: StreamableHTTPMCPSession,
    ) -> None:
        assert isinstance(session, MCPSession)


class TestDiscovery:
    async def test_it_lists_the_servers_tools(
        self,
        session: StreamableHTTPMCPSession,
    ) -> None:
        names = {tool.name for tool in await session.list_tools()}

        assert names == {"forecast", "explode"}

    async def test_it_reads_the_description_the_server_advertises(
        self,
        session: StreamableHTTPMCPSession,
    ) -> None:
        """This text becomes prompt material, so getting the field wrong is silent."""
        tools = {tool.name: tool for tool in await session.list_tools()}

        assert tools["forecast"].description == "Return a weather forecast for a city."

    async def test_it_reads_the_input_schema(
        self,
        session: StreamableHTTPMCPSession,
    ) -> None:
        """`inputSchema` became `input_schema` at SDK 2.0.

        Reading the wrong attribute yields an empty schema — no error, no
        validation, and a model told the tool takes no arguments.
        """
        tools = {tool.name: tool for tool in await session.list_tools()}

        assert set(tools["forecast"].input_schema["properties"]) == {"city", "days"}


class TestInvocation:
    async def test_it_calls_a_tool_and_returns_its_text(
        self,
        session: StreamableHTTPMCPSession,
    ) -> None:
        outcome = await session.call_tool("forecast", {"city": "Oslo", "days": 3})

        assert outcome.text == "Oslo: sunny for 3 day(s)."
        assert outcome.is_error is False

    async def test_a_failing_tool_reports_an_error_rather_than_raising(
        self,
        session: StreamableHTTPMCPSession,
    ) -> None:
        """A tool that ran and failed is an answer the agent should reason about."""
        outcome = await session.call_tool("explode", {})

        assert outcome.is_error is True

    async def test_arguments_the_server_rejects_come_back_as_an_error(
        self,
        session: StreamableHTTPMCPSession,
    ) -> None:
        outcome = await session.call_tool("forecast", {})

        assert outcome.is_error is True

    async def test_successive_calls_work(
        self,
        session: StreamableHTTPMCPSession,
    ) -> None:
        """Each call opens its own session; the second must not inherit a closed one."""
        first = await session.call_tool("forecast", {"city": "Oslo"})
        second = await session.call_tool("forecast", {"city": "Bergen"})

        assert "Oslo" in first.text
        assert "Bergen" in second.text


class TestUnreachableServer:
    async def test_a_dead_server_raises_a_platform_error(self) -> None:
        """Transport failure is an outage, not an answer — unlike a tool-level error."""
        session = StreamableHTTPMCPSession(
            server_id="nowhere",
            url=f"http://127.0.0.1:{_closed_port()}/mcp",
            timeout_seconds=2.0,
        )

        with pytest.raises(ProviderError):
            await session.list_tools()

    async def test_the_error_does_not_disclose_the_url(self) -> None:
        """It can carry a token in a query string, and errors reach logs and models."""
        session = StreamableHTTPMCPSession(
            server_id="nowhere",
            url=f"http://127.0.0.1:{_closed_port()}/mcp?token=hunter2",
            timeout_seconds=2.0,
        )

        with pytest.raises(ProviderError) as raised:
            await session.list_tools()

        assert "hunter2" not in str(raised.value)


class TestIdempotentRetry:
    """Only `list_tools` is retried, and the asymmetry is the point."""

    async def test_listing_tools_survives_a_transient_failure(
        self,
        mcp_server_url: str,
    ) -> None:
        """Discovery runs once at startup; a blip there costs the whole lifetime.

        Driven by pointing the first attempt at nothing. A flaky server is hard
        to simulate honestly, so this asserts the retry happens at all — the
        real dropped-connection case is what motivated it, observed as an SSE
        stream ending without a response.
        """
        session = StreamableHTTPMCPSession(server_id="weather", url=mcp_server_url)
        attempts = 0
        working = session._list_tools  # noqa: SLF001 - exercising the retry seam

        async def fail_once_then_work() -> object:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                message = "transient"
                raise ProviderError(message, provider_id="mcp:weather")
            return await working()

        listed = await session._guarded_with_retry(  # noqa: SLF001
            "list_tools",
            fail_once_then_work,
        )

        assert attempts == 2
        assert {tool.name for tool in listed.tools} == {"forecast", "explode"}

    async def test_calling_a_tool_is_not_retried(
        self,
        mcp_server_url: str,
    ) -> None:
        """A remote tool may have side effects, and the protocol says nothing about them."""
        session = StreamableHTTPMCPSession(server_id="weather", url=mcp_server_url)
        calls = 0

        original = session._call_tool  # noqa: SLF001

        async def counting(name: str, arguments: dict[str, object]) -> object:
            nonlocal calls
            calls += 1
            return await original(name, arguments)

        session._call_tool = counting  # type: ignore[method-assign]  # noqa: SLF001

        await session.call_tool("forecast", {"city": "Oslo"})

        assert calls == 1


class TestCancellation:
    """The other half of the unreachable-server fix, and the riskier half.

    An unreachable server and a cancelling caller both surface as a bare
    ``CancelledError`` — measured, on both paths ``cancelling()`` is 1 and
    ``uncancel()`` returns 0. The session therefore runs each SDK operation in
    its own shielded task so the two can be told apart. These tests hold that
    apart: the previous test class proves an unreachable server becomes a
    ``ProviderError``, and this one proves a real cancellation still cancels.
    """

    async def test_cancelling_the_caller_still_cancels(
        self,
        session: StreamableHTTPMCPSession,
    ) -> None:
        """Swallowing this would leave a task that was told to stop still running."""
        started = asyncio.Event()

        async def call_forever() -> None:
            started.set()
            # A live server, so this is a genuine in-flight call rather than a
            # failure dressed up as one.
            while True:
                await session.call_tool("forecast", {"city": "Oslo"})

        task = asyncio.create_task(call_forever())
        await started.wait()
        await asyncio.sleep(0.05)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        assert task.cancelled()


class TestEndToEndThroughTheAdapter:
    """A real server reached the way an agent would reach it."""

    async def test_a_discovered_tool_executes(
        self,
        session: StreamableHTTPMCPSession,
    ) -> None:
        definitions = {tool.name: tool for tool in await session.list_tools()}
        tool = MCPTool(session=session, definition=definitions["forecast"])

        # Exactly what the tool executor does: an ordinary ToolProvider.
        assert isinstance(tool, ToolProvider)

        invocation = ToolInvocation(
            tool_id=tool.descriptor.tool_id,
            arguments={"city": "Tromsø", "days": 2},
            call_id="call-1",
        )
        await tool.validate(invocation)
        result = await tool.execute(invocation, CONTEXT)

        assert result.succeeded is True
        assert result.call_id == "call-1"

        # Text is what a model reads.
        assert result.output is not None
        assert result.output["content"] == "Tromsø: sunny for 2 day(s)."

        # And a real 2.0 server returns structured output *as well*, which the
        # unit tests' fake did not — the adapter carries both, and this is where
        # that was confirmed rather than assumed.
        assert result.output["structured"] == {"result": "Tromsø: sunny for 2 day(s)."}

    async def test_a_live_server_reports_healthy(
        self,
        session: StreamableHTTPMCPSession,
    ) -> None:
        definitions = {tool.name: tool for tool in await session.list_tools()}
        tool = MCPTool(session=session, definition=definitions["forecast"])

        assert (await tool.health_check()).status is HealthStatus.HEALTHY
