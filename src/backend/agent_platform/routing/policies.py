"""The routing rules.

Each class is one rule over a candidate list, and each is deliberately small
enough to hold in your head while reading a log line that names it.

They divide into two kinds, and the distinction matters more than it looks:

**Constraints** remove models that *cannot* serve the turn — unavailable,
lacking a required capability, too small a context window. An empty result from
a constraint is a real failure, and the router reports which one emptied it.

**Rankings** reorder models that could all serve the turn. A ranking never
removes anything. That is what makes the objective a preference rather than a
second, invisible constraint: asking for the cheapest model should never produce
"no model available".

Ordering within the chain is not arbitrary. Constraints run first so that
rankings only ever sort viable options, and so the diagnostic names the real
reason rather than the last step to touch an already-empty list.
"""

from __future__ import annotations

from decimal import Decimal

from agent_platform_sdk.dto.model import ModelDescriptor
from agent_platform_sdk.dto.routing import RoutingRequest
from agent_platform_sdk.types.enums import RoutingObjective

__all__ = [
    "AvailabilityPolicy",
    "CapabilityPolicy",
    "ContextWindowPolicy",
    "ObjectivePolicy",
    "PinnedModelPolicy",
]


class PinnedModelPolicy:
    """Narrows to an explicitly pinned model, when one was requested.

    First in the chain but *not* last-word: the constraints still run after it.
    Pinning a model that cannot do what the turn requires produces a clear
    failure naming the capability, which is the honest outcome — quietly routing
    elsewhere would answer with a model the caller did not ask for and did not
    hear about.
    """

    @property
    def policy_id(self) -> str:
        return "pinned-model"

    def apply(
        self,
        candidates: tuple[ModelDescriptor, ...],
        request: RoutingRequest,
    ) -> tuple[ModelDescriptor, ...]:
        if request.pinned_model_id is None:
            return candidates
        return tuple(model for model in candidates if model.model_id == request.pinned_model_id)


class AvailabilityPolicy:
    """Removes models withdrawn from routing.

    ``is_available`` exists so a model can be taken out of service by
    configuration without deleting its entry — which would also delete the
    pricing history that past requests are attributed against.
    """

    @property
    def policy_id(self) -> str:
        return "availability"

    def apply(
        self,
        candidates: tuple[ModelDescriptor, ...],
        request: RoutingRequest,
    ) -> tuple[ModelDescriptor, ...]:
        del request
        return tuple(model for model in candidates if model.is_available)


class CapabilityPolicy:
    """Removes models that lack a capability the turn requires.

    Capability, never provider identity (``architecture.md`` §44). "Does this
    support tool calling?" keeps working when a provider is added; "is this
    Azure?" does not.
    """

    @property
    def policy_id(self) -> str:
        return "capability"

    def apply(
        self,
        candidates: tuple[ModelDescriptor, ...],
        request: RoutingRequest,
    ) -> tuple[ModelDescriptor, ...]:
        required = request.required_capabilities
        if not required:
            return candidates
        return tuple(model for model in candidates if required <= model.capabilities)


class ContextWindowPolicy:
    """Removes models too small for the turn.

    Filtering here rather than letting the provider reject the request is worth
    the little it costs: a context-length failure otherwise arrives mid-request,
    after the prompt has been sent and — depending on the provider — after it has
    been billed.
    """

    @property
    def policy_id(self) -> str:
        return "context-window"

    def apply(
        self,
        candidates: tuple[ModelDescriptor, ...],
        request: RoutingRequest,
    ) -> tuple[ModelDescriptor, ...]:
        if request.minimum_context_tokens <= 0:
            return candidates
        return tuple(
            model
            for model in candidates
            if model.max_context_tokens >= request.minimum_context_tokens
        )


class ObjectivePolicy:
    """Orders viable models according to the request's objective.

    A ranking, so it never removes anything: asking for the cheapest model must
    not be able to produce "no model available".

    ``BALANCED`` — the default — puts the agent's declared model first when it
    is still viable. An agent's configured model is an explicit decision by
    whoever wrote it, and overriding that silently is worse than a marginally
    higher bill. The other objectives are opt-in, and the decision they produce
    records that they were asked for.
    """

    @property
    def policy_id(self) -> str:
        return "objective"

    def apply(
        self,
        candidates: tuple[ModelDescriptor, ...],
        request: RoutingRequest,
    ) -> tuple[ModelDescriptor, ...]:
        match request.objective:
            case RoutingObjective.LOWEST_COST:
                # Sorted by model_id as a tie-break so two equally priced models
                # order the same way on every process — otherwise the choice
                # depends on registration order, which depends on startup, and a
                # routing decision that varies between replicas is not one
                # anybody can reason about.
                return tuple(sorted(candidates, key=lambda m: (_blended_cost(m), m.model_id)))

            case RoutingObjective.LARGEST_CONTEXT:
                return tuple(sorted(candidates, key=lambda m: (-m.max_context_tokens, m.model_id)))

            case RoutingObjective.HIGHEST_CAPABILITY:
                # Breadth of declared capabilities, and named as the
                # approximation it is: the platform has no quality score, and
                # deriving one from price would encode "expensive means good".
                return tuple(sorted(candidates, key=lambda m: (-len(m.capabilities), m.model_id)))

            case RoutingObjective.BALANCED:
                preferred = request.preferred_model_id
                if preferred is None:
                    return candidates
                # Stable partition rather than a sort: everything else keeps the
                # order the constraints left it in.
                return tuple(sorted(candidates, key=lambda m: 0 if m.model_id == preferred else 1))

        # No fallback branch: the match is exhaustive, and `mypy --strict`
        # proves it. Adding an objective without handling it here fails type
        # checking, which is a better guard than a silent "no reordering"
        # default that would ship a new objective doing nothing.


def _blended_cost(model: ModelDescriptor) -> Decimal:
    """Return a single comparable price for a model.

    Input and output are priced separately and output is typically the dearer,
    so neither alone ranks honestly. This weights them 1:3, which approximates a
    chat turn — a prompt carrying history against a shorter answer — without
    pretending to be a forecast.

    A per-request estimate using the actual prompt size would be more accurate.
    It would also make the ranking depend on the turn, so the same agent could
    route to different models between messages for reasons no operator could
    see. Predictability is worth more here than the last few percent.
    """
    return (
        model.pricing.input_cost_per_million_tokens
        + model.pricing.output_cost_per_million_tokens * 3
    )
