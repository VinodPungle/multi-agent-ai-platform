"""The Agent Runtime.

Owns the request lifecycle of ``architecture.md`` §14. What it does, in order:

===========================  ====================================================
Runtime validation           Is the agent registered, and enabled?
Memory retrieval             Load the conversation
Prompt assembly              Resolve the prompt asset and its version
Model selection              Ask the router, which applies policy
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
from decimal import Decimal

from agent_platform.events.publisher import build_event
from agent_platform.exceptions.base import (
    PlatformError,
    PolicyViolationError,
)
from agent_platform.registries import AgentRegistry
from agent_platform.telemetry.logging import get_logger
from agent_platform.telemetry.tracing import get_tracer
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.dto.agent import AgentDescriptor
from agent_platform_sdk.dto.completion import CompletionChunk, TokenUsage
from agent_platform_sdk.dto.evaluation import EvaluationRecord
from agent_platform_sdk.dto.execution import AgentRequest, AgentResult
from agent_platform_sdk.dto.message import Message
from agent_platform_sdk.dto.routing import RoutingDecision, RoutingRequest
from agent_platform_sdk.events.runtime_events import RuntimeEventName
from agent_platform_sdk.interfaces.agent import Agent
from agent_platform_sdk.interfaces.evaluation_provider import EvaluationProvider
from agent_platform_sdk.interfaces.event_publisher import EventPublisher
from agent_platform_sdk.interfaces.memory_provider import MemoryProvider
from agent_platform_sdk.interfaces.model_router import ModelRouter
from agent_platform_sdk.interfaces.prompt_provider import PromptProvider
from agent_platform_sdk.interfaces.workflow_engine import WorkflowEngine
from agent_platform_sdk.types.enums import Capability, MessageRole, RoutingObjective
from agent_platform_shared import new_execution_id
from agent_platform_shared.clock import Clock

__all__ = ["AgentRuntime", "RuntimeTurn"]

_logger = get_logger(__name__)
_tracer = get_tracer(__name__)

#: Characters per token, for estimating how much context a turn needs.
#:
#: A rule of thumb, and used only as a lower bound. The platform has no
#: tokenizer, and a wrong estimate in this direction keeps a marginal model
#: rather than excluding a workable one — the first failure is reported by the
#: provider, the second would be invisible.
_CHARACTERS_PER_TOKEN = 4


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
        routing: RoutingDecision,
    ) -> None:
        self.agent = agent
        self.request = request
        self.context = context
        self.conversation_id = conversation_id
        # Carried through rather than recomputed. The reason a model was chosen
        # belongs on the evaluation record for the turn it applied to, and
        # re-deciding later could produce a different answer than the one that
        # actually ran.
        self.routing = routing


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
        model_router: ModelRouter,
        evaluation: EvaluationProvider,
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
            model_router: Decides which model answers the turn. The runtime
                asks rather than reading the descriptor directly, so a routing
                policy can be changed by configuration without this file
                knowing that policies exist.
            evaluation: Where per-turn measurements go. One port, however many
                sinks the composition root fans it out to — the runtime records
                once and does not know whether anything is listening.
        """
        self._agents = agents
        self._workflow_engine = workflow_engine
        self._memory = memory
        self._prompts = prompts
        self._events = events
        self._clock = clock
        self._model_router = model_router
        self._evaluation = evaluation

    # -- Lifecycle ---------------------------------------------------------

    async def prepare(
        self,
        agent_id: str,
        user_input: str,
        context: ExecutionContext,
        conversation_id: str | None = None,
        pinned_model_id: str | None = None,
        objective: RoutingObjective = RoutingObjective.BALANCED,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> RuntimeTurn:
        """Validate, assemble context and enforce policy for one turn.

        Everything up to — and not including — execution. Separated so a caller
        that is about to open a stream can fail properly first; see
        :class:`RuntimeTurn`.

        Args:
            agent_id: Agent to run.
            user_input: The user's message.
            context: Request-scoped context, narrowed to the turn here.
            conversation_id: Conversation to load history from and record into.
            pinned_model_id: Overrides routing for this turn. Deliberately a
                runtime parameter and **not** exposed on the public HTTP API:
                choosing a model is choosing a bill, and there is no
                authorisation layer yet to decide who may. Workflows and
                operator tooling can use it; anonymous callers cannot.
            objective: What routing should optimise for among viable models.
            temperature: Overrides the agent's configured sampling temperature
                for this turn. ``None`` keeps the agent's own value — which is
                the distinction that matters, because zero is a meaningful
                temperature and must not be read as "unset".
            max_output_tokens: Overrides the agent's configured output cap.
                Still bounded by the budget policy, which the runtime enforces
                afterwards regardless of what a caller asked for.

        Raises:
            NotFoundError: no such agent, or no model can serve the turn.
            PolicyViolationError: the agent is disabled, or a budget forbids the
                turn.
            ValidationError: the prompt is missing a required variable.
        """
        agent = self._resolve_agent(agent_id)
        descriptor = agent.descriptor

        history = await self._load_history(conversation_id, context)
        decision = await self._route(
            descriptor,
            user_input,
            history,
            context,
            pinned_model_id,
            objective,
        )

        execution_context = context.derive(
            agent_id=descriptor.agent_id,
            execution_id=context.execution_id or new_execution_id(),
            # From the decision, not the descriptor. The descriptor holds a
            # preference; this is what was actually chosen, and everything
            # downstream — telemetry, cost attribution, the evaluation record —
            # joins on it.
            model_id=decision.model_id,
            provider_id=decision.provider_id,
            prompt_version=descriptor.prompt_version,
        )

        await self._publish(
            RuntimeEventName.REQUEST_RECEIVED,
            execution_context,
            payload={"input_characters": len(user_input)},
        )

        prompt = await self._prompts.get(descriptor.prompt_id, descriptor.prompt_version)

        self._enforce_pre_execution_budget(descriptor, history, execution_context)

        request = AgentRequest(
            input=user_input,
            history=history,
            prompt=prompt,
            variables={"locale": execution_context.locale},
            model_id=decision.model_id,
            # `is not None` rather than `or`: a temperature of 0.0 is a
            # deliberate request for determinism, and `or` would silently
            # discard it for the agent's default.
            temperature=(temperature if temperature is not None else descriptor.temperature),
            max_output_tokens=(
                max_output_tokens if max_output_tokens is not None else descriptor.max_output_tokens
            ),
        )

        return RuntimeTurn(agent, request, execution_context, conversation_id, decision)

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
                # A failed turn is measured too. Cost and latency data that
                # counts only successes flatters the platform exactly when it is
                # misbehaving, and a failure that consumed tokens still cost
                # money.
                await self._evaluate(
                    turn,
                    usage=TokenUsage(),
                    latency_ms=(self._clock.monotonic() - started) * 1000,
                    succeeded=False,
                    streaming=False,
                )
                raise

            elapsed_ms = (self._clock.monotonic() - started) * 1000
            span.set_attribute("runtime.latency_ms", elapsed_ms)
            span.set_attribute("runtime.prompt_tokens", result.usage.prompt_tokens)
            span.set_attribute("runtime.completion_tokens", result.usage.completion_tokens)

            self._enforce_post_execution_budget(turn, result)
            await self._record(turn, answer=result.message.content, context=turn.context)
            await self._evaluate(
                turn,
                usage=result.usage,
                latency_ms=elapsed_ms,
                succeeded=True,
                streaming=False,
                estimated_cost=result.estimated_cost,
            )

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
                # In the `finally`, so a turn the consumer abandoned is still
                # measured — those tokens were generated and billed whether or
                # not anyone read them.
                #
                # Worth being precise about *when*: breaking out of an
                # `async for` does not run this block. It runs when the
                # generator is closed, which the SSE layer does when the
                # response ends and `async with` does at scope exit. Measured:
                # the count is unchanged immediately after a `break` and
                # increments on `aclose()`. A caller that abandons a stream and
                # never closes it leaves the turn uncounted until garbage
                # collection.
                await self._evaluate(
                    turn,
                    usage=usage,
                    latency_ms=elapsed_ms,
                    succeeded=not failed,
                    streaming=True,
                )

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

    async def _evaluate(
        self,
        turn: RuntimeTurn,
        usage: TokenUsage,
        latency_ms: float,
        succeeded: bool,
        streaming: bool,
        estimated_cost: Decimal | None = None,
    ) -> None:
        """Record what this turn consumed.

        Every model invocation emits one of these (``CLAUDE.md``), including the
        ones that failed and the ones a user abandoned — data that counts only
        successes flatters the platform exactly when it is misbehaving, and
        tokens spent on a turn nobody read were still spent.

        Deliberately carries no prompt, no completion and no user input. The
        record is counts, identifiers and money; it is exported to systems with
        different retention and access rules than the conversation, and the
        moment it carries content it becomes a second copy of user data that
        nobody is governing.
        """
        await self._evaluation.record(
            EvaluationRecord(
                correlation_id=turn.context.correlation_id,
                request_id=turn.context.request_id,
                conversation_id=turn.conversation_id,
                session_id=turn.context.session_id,
                agent_id=turn.context.agent_id,
                # From the routing decision, so cost is attributed to the model
                # that actually answered rather than the one configured.
                provider_id=turn.routing.provider_id,
                model_id=turn.routing.model_id,
                prompt_version=turn.context.prompt_version,
                occurred_at=self._clock.now(),
                latency_ms=latency_ms,
                usage=usage,
                estimated_cost=estimated_cost,
                succeeded=succeeded,
                streaming=streaming,
            ),
            turn.context,
        )

    async def _route(
        self,
        descriptor: AgentDescriptor,
        user_input: str,
        history: tuple[Message, ...],
        context: ExecutionContext,
        pinned_model_id: str | None,
        objective: RoutingObjective,
    ) -> RoutingDecision:
        """Ask the router which model should answer this turn.

        Two constraints are derived here because only the runtime knows them:

        **Tool calling** is required when the agent declares tools. Routing to a
        model that cannot call them would produce an agent that silently stops
        searching — a wrong answer rather than an error, which is the worse
        failure.

        **Context size** is estimated from the characters about to be sent. It
        is a floor, not a forecast: the platform has no tokenizer, and four
        characters per token errs towards *under*-estimating, which risks
        keeping a model that is marginally too small rather than excluding one
        that would have worked. Of the two errors, the first is reported by the
        provider and the second is invisible.
        """
        required: set[Capability] = set()
        if descriptor.tool_ids:
            required.add(Capability.TOOL_CALLING)

        characters = len(user_input) + sum(len(message.content) for message in history)

        return await self._model_router.route(
            RoutingRequest(
                agent_id=descriptor.agent_id,
                preferred_model_id=descriptor.model_id,
                pinned_model_id=pinned_model_id,
                required_capabilities=frozenset(required),
                minimum_context_tokens=characters // _CHARACTERS_PER_TOKEN,
                objective=objective,
            ),
            context,
        )

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
