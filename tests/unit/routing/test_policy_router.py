"""Policy-driven model routing.

The tests worth having here are not "does it return a model". They are:

* does a **constraint** actually refuse, rather than quietly picking something
  that cannot do the job — the failure mode that produces a wrong answer instead
  of an error;
* does a **ranking** never refuse, so that asking for the cheapest model cannot
  turn into "no model available";
* can the decision **explain itself** months later, from a log line.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from agent_platform.exceptions.base import NotFoundError
from agent_platform.registries import KeyedRegistry, ModelRegistry
from agent_platform.routing.policies import (
    AvailabilityPolicy,
    CapabilityPolicy,
    ContextWindowPolicy,
    ObjectivePolicy,
    PinnedModelPolicy,
)
from agent_platform.routing.policy_router import PolicyModelRouter
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.dto.model import ModelDescriptor, ModelPricing
from agent_platform_sdk.dto.routing import RoutingRequest
from agent_platform_sdk.interfaces.model_router import ModelRouter, RoutingPolicy
from agent_platform_sdk.types.enums import Capability, RoutingObjective

pytestmark = pytest.mark.unit

CONTEXT = ExecutionContext()

DEFAULT_POLICIES: tuple[RoutingPolicy, ...] = (
    PinnedModelPolicy(),
    AvailabilityPolicy(),
    CapabilityPolicy(),
    ContextWindowPolicy(),
    ObjectivePolicy(),
)


def a_model(model_id: str, **overrides: Any) -> ModelDescriptor:  # noqa: ANN401
    fields: dict[str, Any] = {
        "model_id": model_id,
        "provider_id": "provider-a",
        "display_name": model_id,
        "capabilities": frozenset({Capability.STREAMING}),
        "max_context_tokens": 128_000,
        "max_output_tokens": 4_096,
    }
    fields.update(overrides)
    return ModelDescriptor(**fields)


def priced(
    model_id: str,
    input_cost: str,
    output_cost: str,
    **overrides: Any,  # noqa: ANN401 - keyword forwarding to a_model
) -> ModelDescriptor:
    return a_model(
        model_id,
        pricing=ModelPricing(
            input_cost_per_million_tokens=Decimal(input_cost),
            output_cost_per_million_tokens=Decimal(output_cost),
        ),
        **overrides,
    )


def a_router(
    *models: ModelDescriptor,
    policies: tuple[RoutingPolicy, ...] = DEFAULT_POLICIES,
    default_objective: RoutingObjective = RoutingObjective.BALANCED,
) -> PolicyModelRouter:
    registry: ModelRegistry = KeyedRegistry("model")
    for model in models:
        registry.register(model.model_id, model)
    return PolicyModelRouter(
        models=registry,
        policies=policies,
        default_objective=default_objective,
    )


def a_request(**overrides: Any) -> RoutingRequest:  # noqa: ANN401
    fields: dict[str, Any] = {"agent_id": "chat-agent"}
    fields.update(overrides)
    return RoutingRequest(**fields)


class TestContractConformance:
    def test_the_router_satisfies_its_contract(self) -> None:
        assert isinstance(a_router(a_model("m1")), ModelRouter)

    @pytest.mark.parametrize("policy", DEFAULT_POLICIES, ids=lambda p: p.policy_id)
    def test_every_policy_satisfies_the_contract(self, policy: RoutingPolicy) -> None:
        assert isinstance(policy, RoutingPolicy)


class TestDefaultBehaviour:
    async def test_the_agents_configured_model_is_used(self) -> None:
        """The default must not surprise anyone: configuration wins."""
        router = a_router(a_model("cheap"), a_model("configured"))

        decision = await router.route(a_request(preferred_model_id="configured"), CONTEXT)

        assert decision.model_id == "configured"

    async def test_the_provider_comes_from_the_model(self) -> None:
        """What makes routing across providers work rather than being decorative."""
        router = a_router(a_model("m1", provider_id="provider-b"))

        decision = await router.route(a_request(preferred_model_id="m1"), CONTEXT)

        assert decision.provider_id == "provider-b"

    async def test_a_single_model_is_chosen_without_a_preference(self) -> None:
        router = a_router(a_model("only"))

        assert (await router.route(a_request(), CONTEXT)).model_id == "only"


class TestConstraints:
    async def test_an_unavailable_model_is_not_used(self) -> None:
        """`is_available` withdraws a model without deleting its pricing history."""
        router = a_router(a_model("retired", is_available=False), a_model("live"))

        decision = await router.route(a_request(preferred_model_id="retired"), CONTEXT)

        assert decision.model_id == "live"

    async def test_a_model_that_cannot_call_tools_is_not_used_for_a_tool_turn(self) -> None:
        """The wrong-answer failure: an agent that silently stops searching."""
        router = a_router(
            a_model("no-tools"),
            a_model("tools", capabilities=frozenset({Capability.TOOL_CALLING})),
        )

        decision = await router.route(
            a_request(
                preferred_model_id="no-tools",
                required_capabilities=frozenset({Capability.TOOL_CALLING}),
            ),
            CONTEXT,
        )

        assert decision.model_id == "tools"

    async def test_a_model_too_small_for_the_turn_is_not_used(self) -> None:
        """A context-length failure otherwise arrives after the prompt is billed."""
        router = a_router(
            a_model("small", max_context_tokens=8_000),
            a_model("large", max_context_tokens=200_000),
        )

        decision = await router.route(
            a_request(preferred_model_id="small", minimum_context_tokens=50_000),
            CONTEXT,
        )

        assert decision.model_id == "large"

    async def test_no_viable_model_is_a_refusal_not_a_guess(self) -> None:
        """Substituting something that cannot do the job is the worse failure."""
        router = a_router(a_model("no-tools"))

        with pytest.raises(NotFoundError):
            await router.route(
                a_request(required_capabilities=frozenset({Capability.VISION})),
                CONTEXT,
            )

    async def test_the_refusal_names_the_policy_that_caused_it(self) -> None:
        """ "No model available" sends the reader nowhere."""
        router = a_router(a_model("no-tools"))

        with pytest.raises(NotFoundError) as raised:
            await router.route(
                a_request(required_capabilities=frozenset({Capability.VISION})),
                CONTEXT,
            )

        assert raised.value.details["policy_id"] == "capability"
        assert "no-tools" in raised.value.details["considered"]

    async def test_an_empty_catalogue_says_what_is_actually_wrong(self) -> None:
        router = a_router()

        with pytest.raises(NotFoundError, match="catalogue is empty"):
            await router.route(a_request(), CONTEXT)


class TestPinning:
    async def test_a_pinned_model_overrides_the_agents_preference(self) -> None:
        router = a_router(a_model("configured"), a_model("pinned"))

        decision = await router.route(
            a_request(preferred_model_id="configured", pinned_model_id="pinned"),
            CONTEXT,
        )

        assert decision.model_id == "pinned"

    async def test_a_pinned_model_that_cannot_do_the_job_fails_loudly(self) -> None:
        """Quietly routing elsewhere answers with a model the caller never heard about."""
        router = a_router(
            a_model("pinned"),
            a_model("capable", capabilities=frozenset({Capability.VISION})),
        )

        with pytest.raises(NotFoundError) as raised:
            await router.route(
                a_request(
                    pinned_model_id="pinned",
                    required_capabilities=frozenset({Capability.VISION}),
                ),
                CONTEXT,
            )

        assert raised.value.details["policy_id"] == "capability"

    async def test_pinning_an_unregistered_model_fails(self) -> None:
        router = a_router(a_model("real"))

        with pytest.raises(NotFoundError) as raised:
            await router.route(a_request(pinned_model_id="imaginary"), CONTEXT)

        assert raised.value.details["policy_id"] == "pinned-model"


class TestObjectives:
    async def test_lowest_cost_prefers_the_cheaper_model(self) -> None:
        router = a_router(
            priced("expensive", "10", "30"),
            priced("cheap", "0.5", "1.5"),
        )

        decision = await router.route(
            a_request(preferred_model_id="expensive", objective=RoutingObjective.LOWEST_COST),
            CONTEXT,
        )

        assert decision.model_id == "cheap"

    async def test_lowest_cost_weighs_output_price_too(self) -> None:
        """Output is usually the dearer token; ranking on input alone misleads."""
        router = a_router(
            priced("cheap-in-dear-out", "1", "100"),
            priced("even", "5", "5"),
        )

        decision = await router.route(
            a_request(objective=RoutingObjective.LOWEST_COST),
            CONTEXT,
        )

        assert decision.model_id == "even"

    async def test_largest_context_prefers_the_roomier_model(self) -> None:
        router = a_router(
            a_model("small", max_context_tokens=8_000),
            a_model("huge", max_context_tokens=1_000_000),
        )

        decision = await router.route(
            a_request(preferred_model_id="small", objective=RoutingObjective.LARGEST_CONTEXT),
            CONTEXT,
        )

        assert decision.model_id == "huge"

    async def test_highest_capability_prefers_the_broader_model(self) -> None:
        router = a_router(
            a_model("narrow"),
            a_model(
                "broad",
                capabilities=frozenset(
                    {Capability.STREAMING, Capability.TOOL_CALLING, Capability.VISION}
                ),
            ),
        )

        decision = await router.route(
            a_request(objective=RoutingObjective.HIGHEST_CAPABILITY),
            CONTEXT,
        )

        assert decision.model_id == "broad"

    async def test_a_ranking_never_empties_the_candidates(self) -> None:
        """A preference must not become a second, invisible constraint."""
        router = a_router(priced("only", "999", "999"))

        decision = await router.route(
            a_request(objective=RoutingObjective.LOWEST_COST),
            CONTEXT,
        )

        assert decision.model_id == "only"

    async def test_the_configured_default_objective_applies(self) -> None:
        """An operator sets it once; every turn inherits it."""
        router = a_router(
            priced("expensive", "10", "30"),
            priced("cheap", "0.5", "1.5"),
            default_objective=RoutingObjective.LOWEST_COST,
        )

        decision = await router.route(a_request(preferred_model_id="expensive"), CONTEXT)

        assert decision.model_id == "cheap"

    async def test_an_explicit_objective_beats_the_configured_default(self) -> None:
        router = a_router(
            a_model("small", max_context_tokens=8_000),
            a_model("huge", max_context_tokens=900_000),
            default_objective=RoutingObjective.LOWEST_COST,
        )

        decision = await router.route(
            a_request(objective=RoutingObjective.LARGEST_CONTEXT),
            CONTEXT,
        )

        assert decision.model_id == "huge"


class TestDeterminism:
    async def test_equally_ranked_models_order_the_same_way_every_time(self) -> None:
        """A decision that varies between replicas is not one anybody can reason about."""
        first = a_router(priced("beta", "1", "1"), priced("alpha", "1", "1"))
        second = a_router(priced("alpha", "1", "1"), priced("beta", "1", "1"))

        request = a_request(objective=RoutingObjective.LOWEST_COST)

        assert (await first.route(request, CONTEXT)).model_id == (
            await second.route(request, CONTEXT)
        ).model_id


class TestExplainability:
    async def test_the_decision_names_the_policy_that_chose(self) -> None:
        router = a_router(a_model("m1"))

        decision = await router.route(a_request(preferred_model_id="m1"), CONTEXT)

        assert decision.policy_id == "objective"

    async def test_the_reason_says_why_a_cheaper_model_was_chosen(self) -> None:
        router = a_router(priced("expensive", "10", "30"), priced("cheap", "1", "1"))

        decision = await router.route(
            a_request(preferred_model_id="expensive", objective=RoutingObjective.LOWEST_COST),
            CONTEXT,
        )

        assert "heapest" in decision.reason

    async def test_the_reason_says_when_the_configured_model_was_not_viable(self) -> None:
        """The question an operator actually asks: why not the one I configured?"""
        router = a_router(a_model("configured", is_available=False), a_model("fallback"))

        decision = await router.route(a_request(preferred_model_id="configured"), CONTEXT)

        assert "not viable" in decision.reason
        assert "configured" in decision.reason

    async def test_the_runner_up_is_recorded(self) -> None:
        """The single most useful thing to know when a choice looks wrong."""
        router = a_router(priced("cheap", "1", "1"), priced("dear", "50", "50"))

        decision = await router.route(
            a_request(objective=RoutingObjective.LOWEST_COST),
            CONTEXT,
        )

        assert decision.considered_model_ids == ("cheap", "dear")

    async def test_the_decision_is_loggable_as_flat_fields(self) -> None:
        router = a_router(a_model("m1"))

        fields = (await router.route(a_request(preferred_model_id="m1"), CONTEXT)).to_log_fields()

        assert fields["routed_model_id"] == "m1"
        assert fields["routing_policy_id"] == "objective"
        assert all(isinstance(value, str) for value in fields.values())
