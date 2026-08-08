"""Tool execution pipeline behaviour.

The executor's central promise is that **it never raises**. Every test here is
ultimately a variation on that: an unknown tool, a denied tool, bad arguments, a
timeout, a tool that throws — all of them have to come back as a ``ToolResult``
the agent can read, because an exception aborts a user's turn over something the
agent could have worked around.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from agent_platform.events.publisher import LoggingEventPublisher
from agent_platform.exceptions.base import ProviderError, ValidationError
from agent_platform.registries import KeyedRegistry
from agent_platform.tools.tool_executor import ToolExecutor
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.contracts.health import ComponentHealth
from agent_platform_sdk.dto.tool import ToolDescriptor, ToolInvocation, ToolResult
from agent_platform_sdk.interfaces.tool_provider import ToolProvider
from agent_platform_sdk.policies.retry import RetryPolicy
from agent_platform_sdk.types.enums import Capability, HealthStatus

pytestmark = pytest.mark.unit

CONTEXT = ExecutionContext()


class ScriptedTool:
    """A tool that behaves as instructed and counts its attempts."""

    def __init__(
        self,
        tool_id: str = "scripted",
        failures: tuple[Exception, ...] = (),
        hang_seconds: float = 0.0,
        timeout_seconds: float = 5.0,
        retry_policy: RetryPolicy | None = None,
        is_available: bool = True,
        validation_error: Exception | None = None,
    ) -> None:
        self._tool_id = tool_id
        self._failures = list(failures)
        self._hang_seconds = hang_seconds
        self._timeout_seconds = timeout_seconds
        self._retry_policy = retry_policy or RetryPolicy(max_attempts=1)
        self._is_available = is_available
        self._validation_error = validation_error
        self.attempts = 0

    @property
    def provider_id(self) -> str:
        return self._tool_id

    @property
    def descriptor(self) -> ToolDescriptor:
        return ToolDescriptor(
            tool_id=self._tool_id,
            description="A scripted tool.",
            timeout_seconds=self._timeout_seconds,
            retry_policy=self._retry_policy,
            is_available=self._is_available,
        )

    async def initialize(self) -> None: ...

    async def health_check(self) -> ComponentHealth:
        return ComponentHealth(name=self._tool_id, status=HealthStatus.HEALTHY)

    def supports(self, capability: Capability) -> bool:
        del capability
        return False

    async def close(self) -> None: ...

    async def validate(self, invocation: ToolInvocation) -> None:
        del invocation
        if self._validation_error is not None:
            raise self._validation_error

    async def execute(self, invocation: ToolInvocation, context: ExecutionContext) -> ToolResult:
        del context
        self.attempts += 1

        if self._hang_seconds:
            await asyncio.sleep(self._hang_seconds)

        if self._failures:
            raise self._failures.pop(0)

        return ToolResult(
            tool_id=self._tool_id,
            call_id=invocation.call_id,
            succeeded=True,
            output={"echo": invocation.arguments},
        )


def build_executor(*tools: ScriptedTool) -> ToolExecutor:
    """Assemble an executor over ``tools``."""
    registry: KeyedRegistry[ToolProvider] = KeyedRegistry("tool")
    for tool in tools:
        registry.register(tool.descriptor.tool_id, tool)

    class _Clock:
        """`now()` is used for event timestamps, `monotonic()` for latency."""

        def now(self) -> datetime:
            return datetime(2026, 1, 1, tzinfo=UTC)

        def monotonic(self) -> float:
            return 0.0

    return ToolExecutor(tools=registry, events=LoggingEventPublisher(), clock=_Clock())


def an_invocation(tool_id: str = "scripted", **arguments: object) -> ToolInvocation:
    return ToolInvocation(tool_id=tool_id, arguments=arguments, call_id="call-1")


class TestSuccess:
    async def test_a_tool_runs_and_returns_its_output(self) -> None:
        executor = build_executor(ScriptedTool())

        result = await executor.execute(an_invocation(query="x"), CONTEXT)

        assert result.succeeded is True
        assert result.output == {"echo": {"query": "x"}}

    async def test_the_call_id_is_echoed(self) -> None:
        """The model matches results to calls by id; losing it breaks the pairing."""
        executor = build_executor(ScriptedTool())

        result = await executor.execute(an_invocation(), CONTEXT)

        assert result.call_id == "call-1"

    async def test_latency_is_recorded(self) -> None:
        executor = build_executor(ScriptedTool())

        result = await executor.execute(an_invocation(), CONTEXT)

        assert result.latency_ms is not None


class TestFailuresBecomeResults:
    """None of these may raise."""

    async def test_an_unknown_tool_is_a_failed_result(self) -> None:
        executor = build_executor(ScriptedTool())

        result = await executor.execute(an_invocation("invented-by-the-model"), CONTEXT)

        assert result.succeeded is False
        assert "not available" in (result.error_message or "")

    async def test_a_tool_outside_the_agent_declaration_is_refused(self) -> None:
        """A model can emit any tool name; the agent's declaration is the authority."""
        executor = build_executor(ScriptedTool(), ScriptedTool("other"))

        result = await executor.execute(
            an_invocation("other"), CONTEXT, permitted_tool_ids=("scripted",)
        )

        assert result.succeeded is False
        assert "not available to this agent" in (result.error_message or "")

    async def test_a_withdrawn_tool_is_refused(self) -> None:
        executor = build_executor(ScriptedTool(is_available=False))

        result = await executor.execute(an_invocation(), CONTEXT)

        assert result.succeeded is False

    async def test_invalid_arguments_are_reported_back(self) -> None:
        """The model can correct itself only if it is told what was wrong."""
        executor = build_executor(
            ScriptedTool(validation_error=ValidationError("query must be a string"))
        )

        result = await executor.execute(an_invocation(), CONTEXT)

        assert result.succeeded is False
        assert result.error_message == "query must be a string"

    async def test_validation_runs_before_execution(self) -> None:
        tool = ScriptedTool(validation_error=ValidationError("bad"))
        executor = build_executor(tool)

        await executor.execute(an_invocation(), CONTEXT)

        assert tool.attempts == 0

    async def test_a_provider_failure_is_a_failed_result(self) -> None:
        executor = build_executor(ScriptedTool(failures=(ProviderError("upstream down"),)))

        result = await executor.execute(an_invocation(), CONTEXT)

        assert result.succeeded is False
        assert result.error_message == "upstream down"

    async def test_an_unmapped_exception_is_contained(self) -> None:
        """A tool that breaks its contract must not break the turn."""
        executor = build_executor(ScriptedTool(failures=(RuntimeError("boom"),)))

        result = await executor.execute(an_invocation(), CONTEXT)

        assert result.succeeded is False
        assert "boom" not in (result.error_message or "")

    async def test_a_timeout_is_a_failed_result(self) -> None:
        executor = build_executor(ScriptedTool(hang_seconds=5, timeout_seconds=0.01))

        result = await executor.execute(an_invocation(), CONTEXT)

        assert result.succeeded is False
        assert "exceeded" in (result.error_message or "")


class TestRetryPolicy:
    async def test_a_transient_failure_is_retried(self) -> None:
        tool = ScriptedTool(
            failures=(ProviderError("flaky"),),
            retry_policy=RetryPolicy(max_attempts=3, initial_backoff_seconds=0.001, jitter=False),
        )
        executor = build_executor(tool)

        result = await executor.execute(an_invocation(), CONTEXT)

        assert tool.attempts == 2
        assert result.succeeded is True

    async def test_retries_stop_at_the_configured_limit(self) -> None:
        tool = ScriptedTool(
            failures=tuple(ProviderError("always") for _ in range(5)),
            retry_policy=RetryPolicy(max_attempts=2, initial_backoff_seconds=0.001, jitter=False),
        )
        executor = build_executor(tool)

        result = await executor.execute(an_invocation(), CONTEXT)

        assert tool.attempts == 2
        assert result.succeeded is False

    async def test_a_deterministic_failure_is_not_retried(self) -> None:
        tool = ScriptedTool(
            failures=(ValidationError("wrong shape"),),
            retry_policy=RetryPolicy(max_attempts=3, initial_backoff_seconds=0.001),
        )
        executor = build_executor(tool)

        await executor.execute(an_invocation(), CONTEXT)

        assert tool.attempts == 1

    async def test_an_unmapped_exception_is_not_retried(self) -> None:
        """The platform has no basis for calling a contract violation transient."""
        tool = ScriptedTool(
            failures=(RuntimeError("bug"), RuntimeError("bug")),
            retry_policy=RetryPolicy(max_attempts=3, initial_backoff_seconds=0.001),
        )
        executor = build_executor(tool)

        await executor.execute(an_invocation(), CONTEXT)

        assert tool.attempts == 1


class TestAvailability:
    def test_declared_tools_are_resolved(self) -> None:
        executor = build_executor(ScriptedTool("a"), ScriptedTool("b"))

        assert len(executor.available_tools(("a", "b"))) == 2

    def test_an_unregistered_tool_is_skipped_not_fatal(self) -> None:
        """One descriptor must work across environments that register different tools."""
        executor = build_executor(ScriptedTool("a"))

        assert len(executor.available_tools(("a", "not-here"))) == 1

    def test_a_withdrawn_tool_is_skipped(self) -> None:
        executor = build_executor(ScriptedTool("a"), ScriptedTool("b", is_available=False))

        assert [tool.descriptor.tool_id for tool in executor.available_tools(("a", "b"))] == ["a"]
