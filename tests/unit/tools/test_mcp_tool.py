"""MCP tools, presented as ordinary platform tools.

Driven through a fake :class:`MCPSession`. That is an honest double here and not
the usual trap: ``MCPSession`` is a three-method protocol the platform owns
precisely so it can be faked completely, and every test below asserts the fake
satisfies it. The module that talks to a real server is covered separately, by
:mod:`tests.integration.tools.test_mcp_streamable_http` — against an actual
server over actual HTTP, because SDK behaviour is the one thing a fake cannot
tell the truth about.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_platform.exceptions.base import ProviderError, ValidationError
from agent_platform.tools.mcp.discovery import discover_mcp_tools
from agent_platform.tools.mcp.mcp_tool import MCPTool, mcp_tool_id
from agent_platform.tools.mcp.session import MCPSession, MCPToolDefinition, MCPToolOutcome
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.dto.tool import ToolInvocation
from agent_platform_sdk.interfaces.tool_provider import ToolProvider
from agent_platform_sdk.types.enums import HealthStatus

pytestmark = pytest.mark.unit

CONTEXT = ExecutionContext()

WEATHER_SCHEMA = {
    "type": "object",
    "properties": {
        "city": {"type": "string"},
        "days": {"type": "integer", "minimum": 1, "maximum": 7},
    },
    "required": ["city"],
    "additionalProperties": False,
}


class FakeSession:
    """A complete stand-in for the three-method session protocol."""

    def __init__(
        self,
        server_id: str = "weather",
        definitions: tuple[MCPToolDefinition, ...] | None = None,
        outcome: MCPToolOutcome | None = None,
        failure: Exception | None = None,
    ) -> None:
        self._server_id = server_id
        self._definitions = definitions or (
            MCPToolDefinition(
                name="forecast",
                description="Return a weather forecast for a city.",
                input_schema=WEATHER_SCHEMA,
            ),
        )
        self._outcome = outcome or MCPToolOutcome(text="Sunny.")
        self._failure = failure
        self.calls: list[tuple[str, dict[str, Any]]] = []

    @property
    def server_id(self) -> str:
        return self._server_id

    async def list_tools(self) -> tuple[MCPToolDefinition, ...]:
        if self._failure is not None:
            raise self._failure
        return self._definitions

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> MCPToolOutcome:
        self.calls.append((name, arguments))
        if self._failure is not None:
            raise self._failure
        return self._outcome


def a_tool(session: FakeSession | None = None) -> MCPTool:
    resolved = session or FakeSession()
    return MCPTool(session=resolved, definition=resolved._definitions[0])  # noqa: SLF001


def an_invocation(**arguments: Any) -> ToolInvocation:  # noqa: ANN401
    return ToolInvocation(tool_id=a_tool().descriptor.tool_id, arguments=arguments)


class TestContractConformance:
    def test_the_fake_satisfies_the_session_protocol(self) -> None:
        """Guards the double: a narrower stand-in only tests the stand-in."""
        assert isinstance(FakeSession(), MCPSession)

    def test_an_mcp_tool_is_an_ordinary_tool_provider(self) -> None:
        """The whole point. Nothing downstream may need to know it is remote."""
        assert isinstance(a_tool(), ToolProvider)


class TestIdentity:
    def test_tool_ids_are_namespaced_by_server(self) -> None:
        """Two servers exposing `search` must not silently collide."""
        assert mcp_tool_id("github", "search") == "mcp.github.search"

    def test_two_servers_exposing_one_name_produce_distinct_ids(self) -> None:
        first = MCPTool(FakeSession("github"), MCPToolDefinition(name="search"))
        second = MCPTool(FakeSession("jira"), MCPToolDefinition(name="search"))

        assert first.descriptor.tool_id != second.descriptor.tool_id

    def test_the_id_uses_characters_models_accept(self) -> None:
        """Several providers reject tool names outside [A-Za-z0-9_.-]."""
        tool_id = mcp_tool_id("my-server", "do_thing")

        assert all(character.isalnum() or character in "_.-" for character in tool_id)


class TestDescriptor:
    def test_the_servers_description_is_used_verbatim(self) -> None:
        """Rewriting it would mean inventing claims about a tool we did not write."""
        tool = a_tool()

        assert tool.descriptor.description == "Return a weather forecast for a city."

    def test_the_servers_schema_reaches_the_model(self) -> None:
        assert a_tool().descriptor.input_schema == WEATHER_SCHEMA

    def test_it_does_not_retry_by_default(self) -> None:
        """A remote tool may have side effects and the protocol has no idempotency signal."""
        assert a_tool().descriptor.retry_policy.max_attempts == 1

    def test_the_owner_names_the_server(self) -> None:
        assert a_tool().descriptor.owner == "mcp:weather"


class TestValidation:
    async def test_valid_arguments_pass(self) -> None:
        await a_tool().validate(an_invocation(city="Oslo"))

    async def test_a_missing_required_argument_is_refused(self) -> None:
        """Locally, before a request reaches a tool that may have side effects."""
        with pytest.raises(ValidationError):
            await a_tool().validate(an_invocation(days=3))

    async def test_a_wrongly_typed_argument_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            await a_tool().validate(an_invocation(city="Oslo", days="three"))

    async def test_a_value_outside_the_schemas_range_is_refused(self) -> None:
        """The reason a real validator earns its dependency: nested constraints."""
        with pytest.raises(ValidationError):
            await a_tool().validate(an_invocation(city="Oslo", days=99))

    async def test_an_unexpected_argument_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            await a_tool().validate(an_invocation(city="Oslo", nonsense=True))

    async def test_the_error_does_not_echo_the_arguments(self) -> None:
        """They are user content, and the message reaches logs and sometimes a model."""
        with pytest.raises(ValidationError) as raised:
            await a_tool().validate(an_invocation(city="Oslo", note="hunter2"))

        assert "hunter2" not in str(raised.value)

    async def test_a_tool_with_no_schema_accepts_anything(self) -> None:
        """Nothing to check against. Refusing everything would disable the tool."""
        tool = MCPTool(FakeSession(), MCPToolDefinition(name="anything"))

        await tool.validate(an_invocation(whatever=1))

    async def test_a_malformed_schema_does_not_disable_the_tool(self) -> None:
        """The server's bug. It may still work perfectly well."""
        tool = MCPTool(
            FakeSession(),
            MCPToolDefinition(name="broken", input_schema={"type": "not-a-type"}),
        )

        await tool.validate(an_invocation(city="Oslo"))


class TestExecution:
    async def test_it_calls_the_remote_tool_by_its_server_side_name(self) -> None:
        """The server knows `forecast`, not `mcp.weather.forecast`."""
        session = FakeSession()
        tool = a_tool(session)

        await tool.execute(an_invocation(city="Oslo"), CONTEXT)

        assert session.calls == [("forecast", {"city": "Oslo"})]

    async def test_text_content_reaches_the_result(self) -> None:
        result = await a_tool().execute(an_invocation(city="Oslo"), CONTEXT)

        assert result.succeeded is True
        assert result.output == {"content": "Sunny."}

    async def test_structured_content_is_carried_alongside_the_text(self) -> None:
        """Not redundant: text is what a model reads, structure is for everything else."""
        session = FakeSession(
            outcome=MCPToolOutcome(text="Sunny.", structured_content={"temp_c": 21})
        )

        result = await a_tool(session).execute(an_invocation(city="Oslo"), CONTEXT)

        assert result.output == {"content": "Sunny.", "structured": {"temp_c": 21}}

    async def test_the_call_id_is_echoed_so_the_result_can_be_matched(self) -> None:
        tool = a_tool()
        invocation = ToolInvocation(
            tool_id=tool.descriptor.tool_id,
            arguments={"city": "Oslo"},
            call_id="call-1",
        )

        assert (await tool.execute(invocation, CONTEXT)).call_id == "call-1"


class TestFailure:
    async def test_an_unreachable_server_is_a_result_not_an_exception(self) -> None:
        """An agent that knows its tool is down can say so; an exception ends the turn."""
        session = FakeSession(failure=ProviderError("gone", provider_id="mcp:weather"))

        result = await a_tool(session).execute(an_invocation(city="Oslo"), CONTEXT)

        assert result.succeeded is False
        assert result.error_message

    async def test_a_tool_level_error_is_reported_to_the_agent(self) -> None:
        """The model can recover from this by trying different arguments."""
        session = FakeSession(
            outcome=MCPToolOutcome(text="No such city.", is_error=True),
        )

        result = await a_tool(session).execute(an_invocation(city="Atlantis"), CONTEXT)

        assert result.succeeded is False
        assert result.error_message == "No such city."


class TestHealth:
    async def test_a_reachable_server_is_healthy(self) -> None:
        assert (await a_tool().health_check()).status is HealthStatus.HEALTHY

    async def test_an_unreachable_server_is_degraded_not_unhealthy(self) -> None:
        """Unhealthy would fail readiness and remove a replica over an optional tool."""
        session = FakeSession(failure=ProviderError("gone", provider_id="mcp:weather"))

        assert (await a_tool(session).health_check()).status is HealthStatus.DEGRADED

    async def test_a_tool_that_vanished_from_the_server_is_degraded(self) -> None:
        """Discovery is at startup, so a removed tool fails calls until a restart."""
        session = FakeSession(definitions=(MCPToolDefinition(name="something-else"),))
        tool = MCPTool(session, MCPToolDefinition(name="forecast"))

        health = await tool.health_check()

        assert health.status is HealthStatus.DEGRADED
        assert "no longer advertises" in (health.detail or "")


class TestDiscovery:
    async def test_every_advertised_tool_becomes_a_platform_tool(self) -> None:
        session = FakeSession(
            definitions=(
                MCPToolDefinition(name="forecast"),
                MCPToolDefinition(name="historical"),
            )
        )

        discovered = await discover_mcp_tools((session,))

        assert [tool.descriptor.tool_id for tool in discovered] == [
            "mcp.weather.forecast",
            "mcp.weather.historical",
        ]

    async def test_an_unreachable_server_does_not_stop_the_others(self) -> None:
        """A third party must not hold an outage switch over the platform."""
        broken = FakeSession("broken", failure=ProviderError("gone", provider_id="mcp:broken"))
        working = FakeSession("working")

        discovered = await discover_mcp_tools((broken, working))

        assert [tool.descriptor.tool_id for tool in discovered] == ["mcp.working.forecast"]

    async def test_no_servers_produces_no_tools(self) -> None:
        assert await discover_mcp_tools(()) == ()
