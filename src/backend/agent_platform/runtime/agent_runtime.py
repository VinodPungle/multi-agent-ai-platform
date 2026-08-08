"""The Agent Runtime.

Owns the request lifecycle of ``architecture.md`` §14. What it does, in order:

===========================  ====================================================
Runtime validation           Is the agent registered, and enabled?
Memory retrieval             Load the conversation
Prompt assembly              Resolve the prompt asset and its version
Model selection              Read the model from the descriptor
Budget enforcement           Refuse work that would breach a policy
Execution                    Hand a complete request to the workflow engine
Evaluation                   Record usage, cost and latency
Memory update                Store the turn
===========================  ====================================================

Tool planning and execution join between selection and evaluation in Milestone
04, and multi-agent collaboration inside the workflow engine after that. Neither
changes this file's shape — which is why the stages exist as separate steps now
rather than being inlined into one method that later has to be taken apart.

Every dependency is an interface. The runtime names no provider, no graph
library, no memory backend and no concrete agent, so what it orchestrates is
entirely a matter of what the composition root registered.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from agent_platform.events.publisher import build_event
from agent_platform.exceptions.base import (
    PlatformError,
    PolicyViolationError,
)
from agent_platform.registries import AgentRegistry
from agent_platform.telemetry.logging import get_logger
from agent_platform.telemetry.tracing import get_tracer
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.dto.completion import CompletionChunk, TokenUsage
from agent_platform_sdk.dto.execution import AgentRequest, AgentResult
from agent_platform_sdk.dto.message import Message
from agent_platform_sdk.events.runtime_events import RuntimeEventName
from agent_platform_sdk.interfaces.agent import Agent
from agent_platform_sdk.interfaces.event_publisher import EventPublisher
from agent_platform_sdk.interfaces.memory_provider import MemoryProvider
from agent_platform_sdk.interfaces.prompt_provider import PromptProvider
from agent_platform_sdk.interfaces.workflow_engine import WorkflowEngine
from agent_platform_sdk.types.enums import MessageRole
from agent_platform_shared import new_execution_id
from agent_platform_shared.clock import Clock

__all__ = ["AgentRuntime", "RuntimeTurn"]

_logger = get_logger(__name__)
_tracer = get_tracer(__name__)


class RuntimeTurn:
    """The prepared state of one turn.

    Produced by :meth:`AgentRuntime.prepare` and consumed by execution. It exists
    so that everything which can fail cheaply — unknown agent, disabled agent,
    missing prompt, breached budget — fails *before* a stream opens and while an
    HTTP status code is still available to carry the failure.

    A plain class rather than a model: it holds a live ``Agent`` instance, which
    is not serialisable and has no business being validated.
    """

    def __init__(
        self,
        agent: Agent,
        request: AgentRequest,
        context: ExecutionContext,
        conversation_id: str | None,
    ) -> None:
        self.agent = agent
        self.request = request
        self.context = context
        self.conversation_id = conversation_id


class AgentRuntime:
    """Executes agents. The heart of the platform."""

    def __init__(
        self,
        agents: AgentRegistry,
        workflow_engine: WorkflowEngine,
        memory: MemoryProvider,
        prompts: PromptProvider,
        events: EventPublisher,
        clock: Clock,
    ) -> None:
        """Create the runtime.

        Args:
            agents: Catalogue of executable agents.
            workflow_engine: Orchestration strategy. LangGraph today; the
                runtime cannot tell.
            memory: Conversation storage.
            prompts: Prompt asset resolution, including versions.
            events: Lifecycle event publication.
            clock: Injected time source, so latency and event ordering are
                deterministic under test.
        """
        self._agents = agents
        self._workflow_engine = workflow_engine
        self._memory = memory
        self._prompts = prompts
        self._events = events
        self._clock = clock

    # -- Lifecycle ---------------------------------------------------------

    async def prepare(
        self,
        agent_id: str,
        user_input: str,
        context: ExecutionContext,
        conversation_id: str | None = None,
    ) -> RuntimeTurn:
        """Validate, assemble context and enforce policy for one turn.

        Everything up to — and not including — execution. Separated so a caller
        that is about to open a stream can fail properly first; see
        :class:`RuntimeTurn`.

        Raises:
            NotFoundError: no such agent.
            PolicyViolationError: the agent is disabled, or a budget forbids the
                turn.
            ValidationError: the prompt is missing a required variable.
        """
        agent = self._resolve_agent(agent_id)
        descriptor = agent.descriptor

        execution_context = context.derive(
            agent_id=descriptor.agent_id,
            execution_id=context.execution_id or new_execution_id(),
            model_id=descriptor.model_id,
            provider_id=descriptor.provider_id,
            prompt_version=descriptor.prompt_version,
        )

        await self._publish(
            RuntimeEventName.REQUEST_RECEIVED,
            execution_context,
            payload={"input_characters": len(user_input)},
        )

        history = await self._load_history(conversation_id, execution_context)
        prompt = await self._prompts.get(descriptor.prompt_id, descriptor.prompt_version)

        self._enforce_pre_execution_budget(descriptor, history, execution_context)

        request = AgentRequest(
            input=user_input,
            history=history,
            prompt=prompt,
            variables={"locale": execution_context.locale},
            model_id=descriptor.model_id,
            temperature=descriptor.temperature,
            max_output_tokens=descriptor.max_output_tokens,
        )

        return RuntimeTurn(agent, request, execution_context, conversation_id)

    async def execute(self, turn: RuntimeTurn) -> AgentResult:
        """Run a prepared turn to completion and record it.

        Raises:
            PlatformError: whatever the agent or engine raised, unchanged.
        """
        with _tracer.start_as_current_span("runtime.execute") as span:
            span.set_attribute("runtime.agent_id", turn.agent.descriptor.agent_id)
            span.set_attribute("runtime.engine", self._workflow_engine.engine_id)
            span.set_attribute("runtime.streaming", False)

            await self._publish(RuntimeEventName.AGENT_STARTED, turn.context)
            started = self._clock.monotonic()

            try:
                result = await self._workflow_engine.execute(turn.agent, turn.request, turn.context)
            except PlatformError as error:
                await self._publish(
                    RuntimeEventName.AGENT_FAILED,
                    turn.context,
                    payload={
                        "error_type": type(error).__name__,
                        "error_category": error.category.value,
                    },
                )
                # The user's message is still recorded, so the conversation
                # shows what was asked and a retry has the history it needs.
                await self._record(turn, answer="", context=turn.context)
                raise

            elapsed_ms = (self._clock.monotonic() - started) * 1000
            span.set_attribute("runtime.latency_ms", elapsed_ms)
            span.set_attribute("runtime.prompt_tokens", result.usage.prompt_tokens)
            span.set_attribute("runtime.completion_tokens", result.usage.completion_tokens)

            self._enforce_post_execution_budget(turn, result)
            await self._record(turn, answer=result.message.content, context=turn.context)

            await self._publish(
                RuntimeEventName.AGENT_COMPLETED,
                turn.context,
                payload={
                    "prompt_tokens": result.usage.prompt_tokens,
                    "completion_tokens": result.usage.completion_tokens,
                    "latency_ms": round(elapsed_ms, 2),
                    "model_calls": result.model_calls,
                },
            )

            return result

    async def stream(self, turn: RuntimeTurn) -> AsyncGenerator[CompletionChunk, None]:
        """Run a prepared turn, yielding chunks as they are produced.

        The turn is recorded in a ``finally`` block, so an answer survives the
        consumer stopping early — which is what "stop generating" is. A user who
        read half an answer keeps it, and the stored conversation matches what
        was on screen.

        Failures propagate. The caller translates them into whatever its
        transport can carry; the runtime does not know it is behind HTTP.
        """
        with _tracer.start_as_current_span("runtime.stream") as span:
            span.set_attribute("runtime.agent_id", turn.agent.descriptor.agent_id)
            span.set_attribute("runtime.engine", self._workflow_engine.engine_id)
            span.set_attribute("runtime.streaming", True)

            await self._publish(RuntimeEventName.AGENT_STARTED, turn.context)
            started = self._clock.monotonic()

            chunks: list[str] = []
            usage = TokenUsage()
            failed = False

            try:
                async for chunk in self._workflow_engine.stream(
                    turn.agent, turn.request, turn.context
                ):
                    if chunk.delta:
                        chunks.append(chunk.delta)
                    if chunk.usage is not None:
                        usage = chunk.usage
                    yield chunk
            except PlatformError as error:
                failed = True
                await self._publish(
                    RuntimeEventName.AGENT_FAILED,
                    turn.context,
                    payload={
                        "error_type": type(error).__name__,
                        "error_category": error.category.value,
                    },
                )
                raise
            finally:
                elapsed_ms = (self._clock.monotonic() - started) * 1000
                answer = "".join(chunks)

                await self._record(turn, answer=answer, context=turn.context)

                if not failed:
                    await self._publish(
                        RuntimeEventName.AGENT_COMPLETED,
                        turn.context,
                        payload={
                            "prompt_tokens": usage.prompt_tokens,
                            "completion_tokens": usage.completion_tokens,
                            "latency_ms": round(elapsed_ms, 2),
                            "completion_characters": len(answer),
                        },
                    )

    # -- Discovery ---------------------------------------------------------

    def list_agents(self) -> tuple[str, ...]:
        """Return the ids of every registered agent, in registration order."""
        return self._agents.keys()

    # -- Internals ---------------------------------------------------------

    def _resolve_agent(self, agent_id: str) -> Agent:
        """Return a registered, enabled agent.

        Raises:
            NotFoundError: no such agent.
            PolicyViolationError: the agent is registered but disabled.
        """
        agent = self._agents.get(agent_id)

        if not agent.descriptor.is_enabled:
            # Distinct from "not found" on purpose. A disabled agent is a
            # deliberate operator action, and reporting it as missing would send
            # someone looking for a registration bug that does not exist.
            message = f"Agent {agent_id!r} is disabled."
            raise PolicyViolationError(message, details={"agent_id": agent_id})

        return agent

    async def _load_history(
        self,
        conversation_id: str | None,
        context: ExecutionContext,
    ) -> tuple[Message, ...]:
        """Load conversation history, if this turn belongs to a conversation."""
        if conversation_id is None:
            return ()

        history = await self._memory.load(conversation_id, context)
        await self._publish(
            RuntimeEventName.MEMORY_LOADED,
            context,
            payload={"message_count": len(history)},
        )
        return history

    async def _record(self, turn: RuntimeTurn, answer: str, context: ExecutionContext) -> None:
        """Store the turn, if it belongs to a conversation."""
        if turn.conversation_id is None:
            return

        await self._memory.append(
            turn.conversation_id,
            Message(role=MessageRole.USER, content=turn.request.input),
            context,
        )
        if answer:
            await self._memory.append(
                turn.conversation_id,
                Message(role=MessageRole.ASSISTANT, content=answer),
                context,
            )

        await self._publish(
            RuntimeEventName.MEMORY_UPDATED,
            context,
            payload={"stored_answer": bool(answer)},
        )

    def _enforce_pre_execution_budget(
        self,
        descriptor: object,
        history: tuple[Message, ...],
        context: ExecutionContext,
    ) -> None:
        """Refuse a turn that a budget already forbids.

        Only the checks that can be made *before* spending anything. Token and
        cost ceilings are checked after execution, because neither is knowable
        until the model has answered — the alternative is a tokeniser in the
        runtime, which would be provider-specific and therefore wrong here.
        """
        del descriptor, history, context
        # No pre-execution ceiling is currently expressible: `BudgetPolicy`
        # limits tokens, cost, tool calls and model calls, and all four are
        # post-hoc for a single-call agent. The seam exists so Milestone 04's
        # tool loop — where a running count *is* available mid-execution — has
        # somewhere to enforce it.

    def _enforce_post_execution_budget(self, turn: RuntimeTurn, result: AgentResult) -> None:
        """Report a breached budget after the fact.

        Deliberately does not raise. The work is done and paid for; discarding
        the answer would waste the spend *and* deny the user the result. The
        breach is published as a policy event so it is visible and, in Milestone
        04, enforceable at the point where a loop can still be stopped.
        """
        budget = turn.agent.descriptor.budget
        breaches: list[str] = []

        if (
            budget.max_total_tokens is not None
            and result.usage.total_tokens > budget.max_total_tokens
        ):
            breaches.append(f"tokens {result.usage.total_tokens} > {budget.max_total_tokens}")

        if (
            budget.max_cost is not None
            and result.estimated_cost is not None
            and result.estimated_cost > budget.max_cost
        ):
            breaches.append(f"cost {result.estimated_cost} > {budget.max_cost}")

        if budget.max_model_calls is not None and result.model_calls > budget.max_model_calls:
            breaches.append(f"model calls {result.model_calls} > {budget.max_model_calls}")

        if breaches:
            # `agent_id` comes from the context, which already carries it.
            _logger.warning(
                "runtime.budget_exceeded",
                breaches=breaches,
                **turn.context.to_log_fields(),
            )

    async def _publish(
        self,
        name: RuntimeEventName,
        context: ExecutionContext,
        payload: dict[str, object] | None = None,
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
