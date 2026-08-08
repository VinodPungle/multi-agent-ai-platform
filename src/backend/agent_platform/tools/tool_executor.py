"""Centralised tool execution.

``architecture.md`` §33 puts every tool call through one pipeline:

    Agent → Runtime → Tool Registry → Tool → Runtime → Agent

This module is the middle of that. It resolves the tool, checks the agent is
permitted to use it, validates arguments, applies a timeout and a retry policy,
records telemetry, and converts every possible outcome into a ``ToolResult``.

Why it is here and not in each tool
    The same reasoning as the LLM Gateway (ADR-0006), one layer across. Timeout,
    retry, authorisation and auditing are identical for every tool; implemented
    per tool they would be written once per integration and drift immediately,
    and the tenth tool would be the one that forgot to log.

The strongest guarantee: **this never raises.** Every failure — unknown tool,
denied permission, bad arguments, timeout, a tool that threw — becomes a
``ToolResult`` with ``succeeded=False``. A failing tool is something an agent
should reason about and recover from, not something that aborts a user's turn.
"""

from __future__ import annotations

import asyncio
from secrets import SystemRandom

from agent_platform.events.publisher import build_event
from agent_platform.exceptions.base import PlatformError
from agent_platform.registries import KeyedRegistry
from agent_platform.telemetry.logging import get_logger
from agent_platform.telemetry.tracing import get_tracer
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.dto.tool import ToolInvocation, ToolResult
from agent_platform_sdk.events.runtime_events import RuntimeEventName
from agent_platform_sdk.interfaces.event_publisher import EventPublisher
from agent_platform_sdk.interfaces.tool_provider import ToolProvider
from agent_platform_sdk.types.enums import ErrorCategory
from agent_platform_shared.clock import Clock

__all__ = ["ToolExecutor"]

_logger = get_logger(__name__)
_tracer = get_tracer(__name__)

_random = SystemRandom()


class ToolExecutor:
    """Runs tools under policy, and never lets one break a request."""

    def __init__(
        self,
        tools: KeyedRegistry[ToolProvider],
        events: EventPublisher,
        clock: Clock,
    ) -> None:
        """Create the executor.

        Args:
            tools: The executable tool catalogue.
            events: Lifecycle event publication.
            clock: Injected time source, so latency is deterministic under test.
        """
        self._tools = tools
        self._events = events
        self._clock = clock

    def available_tools(self, tool_ids: tuple[str, ...]) -> tuple[ToolProvider, ...]:
        """Return the registered, available tools among ``tool_ids``.

        Silently skips ids that are unknown or withdrawn, rather than raising:
        an agent declaring a tool this deployment does not have should run
        without it, not fail. A missing tool is logged so the mismatch is
        visible without being fatal.
        """
        resolved: list[ToolProvider] = []

        for tool_id in tool_ids:
            tool = self._tools.try_get(tool_id)
            if tool is None:
                _logger.warning(
                    "tool.not_registered",
                    tool_id=tool_id,
                    detail="An agent declares this tool but it is not registered.",
                )
                continue
            if not tool.descriptor.is_available:
                continue
            resolved.append(tool)

        return tuple(resolved)

    async def execute(
        self,
        invocation: ToolInvocation,
        context: ExecutionContext,
        permitted_tool_ids: tuple[str, ...] = (),
    ) -> ToolResult:
        """Run one tool invocation under policy.

        Args:
            invocation: What to run, as requested by a model.
            context: Execution context, for attribution.
            permitted_tool_ids: Tools the calling agent declared. A call to
                anything else is refused — a model can emit any tool name,
                including one it inferred from the conversation, and the agent's
                declaration is the authority on what it may reach.

        Returns:
            A result. Never raises, whatever happened.
        """
        started = self._clock.monotonic()

        with _tracer.start_as_current_span("tool.execute") as span:
            span.set_attribute("tool.id", invocation.tool_id)

            await self._publish(
                RuntimeEventName.TOOL_STARTED,
                context,
                {"tool_id": invocation.tool_id},
            )

            result = await self._run(invocation, context, permitted_tool_ids)
            elapsed_ms = (self._clock.monotonic() - started) * 1000

            span.set_attribute("tool.succeeded", result.succeeded)
            span.set_attribute("tool.latency_ms", elapsed_ms)

            await self._publish(
                RuntimeEventName.TOOL_COMPLETED,
                context,
                {
                    "tool_id": invocation.tool_id,
                    "succeeded": result.succeeded,
                    "latency_ms": round(elapsed_ms, 2),
                },
            )

            _logger.info(
                "tool.executed",
                tool_id=invocation.tool_id,
                succeeded=result.succeeded,
                latency_ms=round(elapsed_ms, 2),
                **context.to_log_fields(),
            )

            return result.model_copy(update={"latency_ms": result.latency_ms or elapsed_ms})

    async def _run(
        self,
        invocation: ToolInvocation,
        context: ExecutionContext,
        permitted_tool_ids: tuple[str, ...],
    ) -> ToolResult:
        """Resolve, authorise, validate and execute. Converts everything to a result."""
        if permitted_tool_ids and invocation.tool_id not in permitted_tool_ids:
            return self._failure(
                invocation,
                f"Tool {invocation.tool_id!r} is not available to this agent.",
            )

        tool = self._tools.try_get(invocation.tool_id)
        if tool is None:
            # The model invented a tool name, or one was withdrawn mid-flight.
            # Telling the agent is more useful than failing the turn: it can
            # answer without the tool.
            return self._failure(invocation, f"Tool {invocation.tool_id!r} is not available.")

        if not tool.descriptor.is_available:
            return self._failure(invocation, f"Tool {invocation.tool_id!r} is currently withdrawn.")

        try:
            await tool.validate(invocation)
        except PlatformError as error:
            # A model produced arguments that do not fit the schema. Reported
            # back so it can correct them on the next turn.
            return self._failure(invocation, error.message)

        return await self._execute_with_policy(tool, invocation, context)

    async def _execute_with_policy(
        self,
        tool: ToolProvider,
        invocation: ToolInvocation,
        context: ExecutionContext,
    ) -> ToolResult:
        """Execute under the descriptor's timeout and retry policy."""
        descriptor = tool.descriptor
        policy = descriptor.retry_policy
        attempt = 0

        while True:
            attempt += 1
            try:
                async with asyncio.timeout(descriptor.timeout_seconds):
                    return await tool.execute(invocation, context)

            except TimeoutError:
                failure_message = (
                    f"Tool {invocation.tool_id!r} exceeded {descriptor.timeout_seconds}s."
                )
                category = ErrorCategory.TIMEOUT

            except PlatformError as error:
                failure_message = error.message
                category = error.category

            except Exception as error:
                # A tool that raises something unmapped has broken its contract.
                # Never retried: the platform has no basis for calling it
                # transient, and the message may carry internal detail, so only
                # the type is reported.
                _logger.error(
                    "tool.unhandled_exception",
                    tool_id=invocation.tool_id,
                    error_type=type(error).__name__,
                    exc_info=True,
                    **context.to_log_fields(),
                )
                return self._failure(
                    invocation,
                    f"Tool {invocation.tool_id!r} failed unexpectedly.",
                )

            if not policy.is_retryable(category) or attempt >= policy.max_attempts:
                return self._failure(invocation, failure_message)

            delay = self._backoff_delay(policy.initial_backoff_seconds, attempt, policy)
            _logger.warning(
                "tool.retry",
                tool_id=invocation.tool_id,
                attempt=attempt,
                max_attempts=policy.max_attempts,
                delay_seconds=round(delay, 3),
                **context.to_log_fields(),
            )
            await asyncio.sleep(delay)

    @staticmethod
    def _backoff_delay(initial: float, attempt: int, policy: object) -> float:
        """Exponential backoff with full jitter, capped by the policy."""
        multiplier = getattr(policy, "backoff_multiplier", 2.0)
        maximum = getattr(policy, "max_backoff_seconds", 30.0)
        jitter = getattr(policy, "jitter", True)

        delay = min(initial * (multiplier ** (attempt - 1)), maximum)
        return _random.uniform(0.0, delay) if jitter else delay

    @staticmethod
    def _failure(invocation: ToolInvocation, message: str) -> ToolResult:
        """Build a failed result carrying a model-safe message."""
        return ToolResult(
            tool_id=invocation.tool_id,
            call_id=invocation.call_id,
            succeeded=False,
            error_message=message,
        )

    async def _publish(
        self,
        name: RuntimeEventName,
        context: ExecutionContext,
        payload: dict[str, object],
    ) -> None:
        """Publish one lifecycle event."""
        await self._events.publish(
            build_event(
                name,
                self._clock,
                correlation_id=context.correlation_id,
                request_id=context.request_id,
                execution_id=context.execution_id,
                agent_id=context.agent_id,
                payload=payload,
            )
        )
