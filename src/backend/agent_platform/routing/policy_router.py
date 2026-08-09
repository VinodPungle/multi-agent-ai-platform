"""The routing chain.

Runs the configured policies in order over the model catalogue and reports what
survived. The whole class is about forty lines of logic and roughly as much
again explaining a failure, which is the correct ratio: choosing a model is
easy, and being able to say afterwards why *that* one was chosen is the part
that has to work at three in the morning.

Where the decision goes
    :meth:`AgentRuntime.prepare` calls this before assembling the request, so
    the chosen model is on the ExecutionContext for the whole turn — telemetry,
    cost attribution and the evaluation record all join on it. Nothing
    downstream re-decides.
"""

from __future__ import annotations

from agent_platform.exceptions.base import NotFoundError
from agent_platform.telemetry.logging import get_logger
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.dto.model import ModelDescriptor
from agent_platform_sdk.dto.routing import RoutingDecision, RoutingRequest
from agent_platform_sdk.interfaces.model_router import RoutingPolicy
from agent_platform_sdk.interfaces.registry import Registry
from agent_platform_sdk.types.enums import RoutingObjective

__all__ = ["PolicyModelRouter"]

_logger = get_logger(__name__)


class PolicyModelRouter:
    """Chooses a model by running a chain of policies over the catalogue.

    Satisfies :class:`~agent_platform_sdk.interfaces.model_router.ModelRouter`
    structurally — it inherits nothing, per ADR-0004.
    """

    def __init__(
        self,
        models: Registry[ModelDescriptor],
        policies: tuple[RoutingPolicy, ...],
        default_objective: RoutingObjective = RoutingObjective.BALANCED,
    ) -> None:
        """Create the router.

        Args:
            models: The catalogue, populated at startup from each provider's
                ``list_models()``. Read on every turn rather than snapshotted,
                so a model withdrawn by configuration stops being routed to
                without a restart.
            policies: Rules in the order they apply. Constraints before
                rankings — see :mod:`agent_platform.routing.policies`.
            default_objective: Applied when a request does not state one.
        """
        self._models = models
        self._policies = policies
        self._default_objective = default_objective

    async def route(
        self,
        request: RoutingRequest,
        context: ExecutionContext,
    ) -> RoutingDecision:
        """Return the model to use, and why.

        Raises:
            NotFoundError: the catalogue is empty, or a policy excluded every
                candidate. The message names the policy responsible and lists
                what it was given, because "no model available" sends the reader
                nowhere.
        """
        effective = (
            request
            if request.objective is not RoutingObjective.BALANCED
            else request.model_copy(update={"objective": self._default_objective})
        )

        candidates = tuple(model for _, model in self._models.items())
        if not candidates:
            message = (
                "The model catalogue is empty, so no model can be routed to. "
                "It is populated at startup from each provider's list_models(); "
                "an empty catalogue means no LLM provider is registered."
            )
            raise NotFoundError(message, details={"agent_id": request.agent_id})

        for policy in self._policies:
            remaining = policy.apply(candidates, effective)
            if not remaining:
                raise self._nothing_survived(policy, candidates, effective)
            candidates = remaining

        chosen = candidates[0]
        decision = RoutingDecision(
            model_id=chosen.model_id,
            provider_id=chosen.provider_id,
            # The final policy in the chain is the one that put this model
            # first, so it is the one an operator should look at when the choice
            # looks wrong.
            policy_id=self._policies[-1].policy_id if self._policies else "none",
            reason=self._reason(chosen, effective),
            considered_model_ids=tuple(model.model_id for model in candidates),
        )

        # Debug rather than info: this fires on every turn, and the decision is
        # already on the ExecutionContext and the span, where anything
        # investigating a specific request will find it.
        _logger.debug(
            "routing.decided",
            **decision.to_log_fields(),
            objective=effective.objective.value,
            considered=len(candidates),
            **context.to_log_fields(),
        )
        return decision

    # -- Internals ---------------------------------------------------------

    @staticmethod
    def _reason(chosen: ModelDescriptor, request: RoutingRequest) -> str:
        """Explain the choice in terms someone reading a log can act on."""
        if request.pinned_model_id is not None:
            return f"Pinned to {chosen.model_id!r} by the request."

        match request.objective:
            case RoutingObjective.LOWEST_COST:
                return f"Cheapest model able to serve the turn ({chosen.model_id})."
            case RoutingObjective.LARGEST_CONTEXT:
                return (
                    f"Largest context window among viable models "
                    f"({chosen.max_context_tokens:,} tokens)."
                )
            case RoutingObjective.HIGHEST_CAPABILITY:
                return (
                    f"Widest declared capability set among viable models "
                    f"({len(chosen.capabilities)} capabilities)."
                )
            case RoutingObjective.BALANCED:
                if chosen.model_id == request.preferred_model_id:
                    return f"The agent's configured model ({chosen.model_id}) is viable."
                return (
                    f"The agent's configured model "
                    f"({request.preferred_model_id or 'none'}) is not viable; "
                    f"routed to {chosen.model_id}."
                )

        # Exhaustive, and `mypy --strict` proves it — a new objective without a
        # reason here fails type checking rather than shipping a decision that
        # cannot explain itself.

    def _nothing_survived(
        self,
        policy: RoutingPolicy,
        candidates: tuple[ModelDescriptor, ...],
        request: RoutingRequest,
    ) -> NotFoundError:
        """Build the error for an exhausted candidate list.

        Names the policy that emptied it and lists what it was given. The two
        together are usually enough to see the cause without reproducing
        anything — a pinned model that is not registered, or a tool-using agent
        pointed at a model that cannot call tools.
        """
        offered = ", ".join(model.model_id for model in candidates)
        message = (
            f"No model can serve agent {request.agent_id!r}: the "
            f"{policy.policy_id!r} policy excluded every candidate. "
            f"Considered: {offered}."
        )
        return NotFoundError(
            message,
            details={
                "agent_id": request.agent_id,
                "policy_id": policy.policy_id,
                "considered": offered,
                "objective": request.objective.value,
                "pinned_model_id": request.pinned_model_id or "",
                "required_capabilities": ",".join(
                    sorted(capability.value for capability in request.required_capabilities)
                ),
                "minimum_context_tokens": str(request.minimum_context_tokens),
            },
        )
