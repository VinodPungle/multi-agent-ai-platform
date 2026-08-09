"""Model routing contracts.

``CLAUDE.md`` requires that model selection be policy-driven and support
per-agent, per-request, per-user and per-workflow choices — and that none of it
be hardcoded. These are the two values that flow through that decision: what was
asked for, and what was chosen.

The decision carries its own explanation
    :class:`RoutingDecision` records the policy that chose, the reason it gave,
    and every model it considered. That is not decoration. A platform that
    silently answers with a different model than the one an operator expects
    produces evaluation data nobody can compare and a bill nobody can attribute
    — and the question "why did this request use that model?" has to be
    answerable from a log line, months later, without re-running anything.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from agent_platform_sdk.types.enums import Capability, RoutingObjective

__all__ = ["RoutingDecision", "RoutingRequest"]


class RoutingRequest(BaseModel):
    """What the runtime knows before a model has been chosen."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_id: str = Field(description="Agent the turn belongs to.")

    preferred_model_id: str | None = Field(
        default=None,
        description=(
            "The agent's declared default. A preference, not an instruction: a "
            "policy may choose otherwise, and must say why when it does."
        ),
    )
    pinned_model_id: str | None = Field(
        default=None,
        description=(
            "An explicit instruction to use this model, overriding every "
            "ranking policy. Set from a request or by an operator. Still "
            "subject to the filters — a pinned model that cannot do what the "
            "turn requires must fail loudly rather than be quietly replaced."
        ),
    )

    required_capabilities: frozenset[Capability] = Field(
        default=frozenset(),
        description=(
            "Capabilities the turn cannot proceed without — tool calling when "
            "the agent has tools, vision when the input has an image. Matched "
            "against declared capabilities, never against a provider's name "
            "(``architecture.md`` §44)."
        ),
    )
    minimum_context_tokens: int = Field(
        default=0,
        ge=0,
        description=(
            "Context the turn is expected to need. Filters out models that "
            "would fail on length — a failure that otherwise arrives from the "
            "provider mid-request, after the tokens have been paid for."
        ),
    )

    objective: RoutingObjective = Field(
        default=RoutingObjective.BALANCED,
        description="What to optimise for among the models that remain viable.",
    )


class RoutingDecision(BaseModel):
    """The model chosen for one turn, and the reasoning that produced it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_id: str = Field(description="Chosen model.")
    provider_id: str = Field(
        description=(
            "Provider that serves it, taken from the model's registry entry. "
            "Carrying it here is what lets routing cross providers without the "
            "gateway guessing."
        ),
    )
    policy_id: str = Field(description="Policy that made the final choice.")
    reason: str = Field(description="Why, in terms an operator reading a log can act on.")
    considered_model_ids: tuple[str, ...] = Field(
        default=(),
        description=(
            "Every model that survived filtering, in the order the ranking "
            "policy left them. The runner-up is the single most useful thing to "
            "know when a choice looks wrong."
        ),
    )

    def to_log_fields(self) -> dict[str, str]:
        """Return the decision as flat fields for logs and span attributes."""
        return {
            "routed_model_id": self.model_id,
            "routed_provider_id": self.provider_id,
            "routing_policy_id": self.policy_id,
            "routing_reason": self.reason,
        }
