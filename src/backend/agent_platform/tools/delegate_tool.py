"""Delegating work to another agent.

    Agent A → Agent Runtime → Agent B

``architecture.md`` §31 is explicit: agents must never call one another
directly. The runtime mediates, because it is the only place that can apply
authentication, tracing, retries, timeouts, budgets and evaluation to the hop.

Why a tool rather than a new mechanism
    A tool *is* the runtime mediating. The tool pipeline already resolves
    through a registry, checks the calling agent is permitted, validates
    arguments, applies a timeout and retry policy, records telemetry and
    publishes lifecycle events. Delegation needs every one of those, and
    inventing a parallel path would mean implementing them a second time and
    getting one of them subtly wrong.

    So a coordinating agent sees `delegate-to-agent` in its tool list and calls
    it like any other tool. It does not hold a reference to another agent, and
    it cannot reach one this way that it was not permitted.

The interesting problem is cycles
    Agent A delegates to B, which delegates back to A. Nothing in the model
    prevents it, and nothing in the tool pipeline notices — each individual call
    looks reasonable. Unbounded, it exhausts the budget of every agent involved
    and costs real money doing it.

    `ExecutionContext.delegation_depth` carries the count through every hop, and
    this tool refuses beyond a configured maximum. Depth on the context rather
    than a counter here is deliberate: a counter on the tool instance is shared
    across concurrent requests, and one scoped per call resets at exactly the
    moment a cycle would be caught.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from agent_platform.telemetry.logging import get_logger
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.contracts.health import ComponentHealth
from agent_platform_sdk.dto.tool import ToolDescriptor, ToolInvocation, ToolResult
from agent_platform_sdk.types.enums import Capability, HealthStatus

if TYPE_CHECKING:  # pragma: no cover - import cycle at runtime, not at type time
    from agent_platform.runtime.agent_runtime import AgentRuntime

__all__ = ["DELEGATE_TOOL_ID", "DelegateToAgentTool"]

_logger = get_logger(__name__)

DELEGATE_TOOL_ID = "delegate-to-agent"

#: How many agents deep a single user request may go.
#:
#: Two is enough for the collaboration this platform describes — a coordinator
#: consulting a specialist — and small enough that a cycle costs three model
#: calls rather than a budget. Raising it multiplies the worst-case cost of one
#: request by the number of agents reachable at each level.
DEFAULT_MAX_DELEGATION_DEPTH = 2


class DelegateToAgentTool:
    """Runs another agent on the calling agent's behalf, through the runtime.

    Satisfies :class:`~agent_platform_sdk.interfaces.tool_provider.ToolProvider`
    structurally.
    """

    def __init__(
        self,
        runtime_provider: Callable[[], AgentRuntime],
        delegatable_agent_ids: tuple[str, ...] = (),
        max_delegation_depth: int = DEFAULT_MAX_DELEGATION_DEPTH,
    ) -> None:
        """Create the tool.

        Args:
            runtime_provider: Returns the runtime that owns agent execution.
                A callable rather than the runtime itself, because the tool
                registry is constructed *before* the runtime and the runtime
                needs the registry. Resolving lazily breaks that cycle without
                mutating an already-constructed object, which would leave a
                window where the tool exists and cannot work.
            delegatable_agent_ids: Agents that may be reached *through this
                tool*. Not every registered agent: a coordinator being able to
                invoke anything that happens to be registered is how one agent's
                permissions quietly become everyone's.
            max_delegation_depth: How many agents deep one request may go.
        """
        self._runtime_provider = runtime_provider
        self._delegatable = delegatable_agent_ids
        self._max_depth = max_delegation_depth

    @property
    def provider_id(self) -> str:
        """Identifier this tool registers under."""
        return DELEGATE_TOOL_ID

    @property
    def descriptor(self) -> ToolDescriptor:
        """Registry metadata.

        The description names the available agents and what each is for, because
        that text is the entire basis on which a model decides whether to
        delegate and to whom. A vague description produces either no delegation
        or delegation to the wrong specialist.
        """
        available = ", ".join(self._delegatable) if self._delegatable else "none"
        return ToolDescriptor(
            tool_id=DELEGATE_TOOL_ID,
            description=(
                "Ask a specialist agent to handle part of a request and return "
                "its answer. Use this when another agent is better suited than "
                f"you are. Available agents: {available}. Delegate once, with a "
                "self-contained task — the specialist cannot see this "
                "conversation."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Which agent to ask.",
                        "enum": list(self._delegatable),
                    },
                    "task": {
                        "type": "string",
                        "description": (
                            "The complete task for that agent. It has no access "
                            "to this conversation, so include every detail it "
                            "needs."
                        ),
                        "minLength": 1,
                        "maxLength": 8000,
                    },
                },
                "required": ["agent_id", "task"],
                "additionalProperties": False,
            },
            # Generous: the budget being spent is another agent's whole turn,
            # including its own model call and possibly its own tools.
            timeout_seconds=180.0,
        )

    async def initialize(self) -> None:
        """Nothing to open."""

    async def close(self) -> None:
        """Nothing to release."""

    def supports(self, capability: Capability) -> bool:
        """Declare nothing. Delegation is not a model capability."""
        del capability
        return False

    async def health_check(self) -> ComponentHealth:
        """Report which agents are reachable through this tool."""
        if not self._delegatable:
            return ComponentHealth(
                name=DELEGATE_TOOL_ID,
                status=HealthStatus.DEGRADED,
                detail=(
                    "No delegatable agents configured. The tool is registered "
                    "but every call will be refused."
                ),
            )

        return ComponentHealth(
            name=DELEGATE_TOOL_ID,
            status=HealthStatus.HEALTHY,
            detail=f"Can delegate to: {', '.join(self._delegatable)}.",
        )

    async def validate(self, invocation: ToolInvocation) -> None:
        """Check the arguments before anything is spent.

        Deliberately permissive about *which* agent: an unknown id is reported
        through :meth:`execute` as a failed result the model can reason about
        and correct, rather than raised. A model that guessed a name should be
        told the real ones, not have its turn aborted.
        """
        task = invocation.arguments.get("task")
        if not isinstance(task, str) or not task.strip():
            message = "Delegation requires a non-empty 'task'."
            raise ValueError(message)

    async def execute(self, invocation: ToolInvocation, context: ExecutionContext) -> ToolResult:
        """Run the requested agent and return its answer.

        Failures are returned, not raised. A specialist that could not help is
        something the calling agent should reason about — it may know enough to
        answer anyway — and raising would discard a turn the user is waiting on.
        """
        agent_id = str(invocation.arguments.get("agent_id") or "").strip()
        task = str(invocation.arguments.get("task") or "").strip()

        if context.delegation_depth >= self._max_depth:
            # The cycle guard. Reported to the model rather than raised, so it
            # answers with what it has instead of failing the user's request.
            _logger.warning(
                "delegation.depth_exceeded",
                requested_agent=agent_id,
                depth=context.delegation_depth,
                limit=self._max_depth,
                **context.to_log_fields(),
            )
            return ToolResult(
                tool_id=DELEGATE_TOOL_ID,
                call_id=invocation.call_id,
                succeeded=False,
                error_message=(
                    "Maximum delegation depth reached. Answer with what you "
                    "already have rather than asking another agent."
                ),
            )

        if agent_id not in self._delegatable:
            return ToolResult(
                tool_id=DELEGATE_TOOL_ID,
                call_id=invocation.call_id,
                succeeded=False,
                error_message=(
                    f"Agent {agent_id!r} is not available. Choose one of: "
                    f"{', '.join(self._delegatable) or 'none'}."
                ),
            )

        # Depth incremented *before* the call, on the context the delegate
        # receives. That context reaches the delegate's own tools, which is what
        # makes the guard hold across a chain rather than only one hop.
        delegate_context = context.derive(
            delegation_depth=context.delegation_depth + 1,
            # A fresh execution id: this is a distinct execution, and reusing
            # the caller's would merge two agents' telemetry into one record.
            execution_id=None,
        )

        _logger.info(
            "delegation.started",
            delegate_agent_id=agent_id,
            depth=delegate_context.delegation_depth,
            **context.to_log_fields(),
        )

        try:
            # No conversation id. The delegate answers one self-contained task
            # and must not read or write the user's conversation — its working
            # notes are not part of what the user said.
            runtime = self._runtime_provider()
            turn = await runtime.prepare(agent_id, task, delegate_context)
            result = await runtime.execute(turn)
        # A broad catch, deliberately. A tool must never raise: whatever the
        # delegate did wrong, the caller is mid-turn with a user waiting, and it
        # can often still answer. The type is reported; the message is not,
        # because a nested agent's internals are not the caller's business.
        except Exception as error:  # noqa: BLE001
            _logger.warning(
                "delegation.failed",
                delegate_agent_id=agent_id,
                error_type=type(error).__name__,
                **context.to_log_fields(),
            )
            return ToolResult(
                tool_id=DELEGATE_TOOL_ID,
                call_id=invocation.call_id,
                succeeded=False,
                error_message=(
                    f"Agent {agent_id!r} could not complete the task "
                    f"({type(error).__name__}). Answer with what you have."
                ),
            )

        _logger.info(
            "delegation.completed",
            delegate_agent_id=agent_id,
            prompt_tokens=result.usage.prompt_tokens,
            completion_tokens=result.usage.completion_tokens,
            model_calls=result.model_calls,
            **context.to_log_fields(),
        )

        return ToolResult(
            tool_id=DELEGATE_TOOL_ID,
            call_id=invocation.call_id,
            succeeded=True,
            output={
                "agent_id": agent_id,
                "answer": result.message.content,
                # Returned so the caller's turn can attribute what the
                # delegation cost. Without it, a multi-agent request reports
                # only the coordinator's tokens and understates the bill.
                "prompt_tokens": result.usage.prompt_tokens,
                "completion_tokens": result.usage.completion_tokens,
            },
        )

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"DelegateToAgentTool(agents={self._delegatable!r}, max_depth={self._max_depth})"
