"""Model-routing ports.

Two protocols, because two things are being separated.

:class:`RoutingPolicy` is one rule — "drop what cannot do this", "prefer the
cheapest". :class:`ModelRouter` composes rules into a decision. Keeping them
apart is what makes a new rule a new small class rather than an edit to a
growing conditional, and it is what lets an environment run a different chain by
configuration.

Why a chain of narrowing steps rather than a scoring function
    A score is easy to write and hard to operate. When a scored router picks a
    model an operator did not expect, the answer to "why?" is a number, and the
    only way to change it is to guess at weights. A chain answers with the name
    of the step that removed the alternative, which is a thing someone can act
    on.

The rule that survives every implementation
    A router may never substitute a model to work around a failure. Silent
    failover changes which model answered a user with nothing in the request
    recording it, and makes evaluation data incomparable — the same prohibition
    :mod:`agent_platform_sdk.interfaces.llm_provider_resolver` states for
    providers, for the same reason.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.dto.model import ModelDescriptor
from agent_platform_sdk.dto.routing import RoutingDecision, RoutingRequest

__all__ = ["ModelRouter", "RoutingPolicy"]


@runtime_checkable
class RoutingPolicy(Protocol):
    """One rule in a routing chain.

    Implementations are pure functions over the candidate list. No I/O, no
    clock, no randomness: a routing decision that cannot be reproduced from its
    inputs cannot be explained afterwards, and explaining it afterwards is most
    of the point.
    """

    @property
    def policy_id(self) -> str:
        """Identifier recorded on the decision this policy contributed to."""
        ...

    def apply(
        self,
        candidates: tuple[ModelDescriptor, ...],
        request: RoutingRequest,
    ) -> tuple[ModelDescriptor, ...]:
        """Return the candidates that survive this rule, in preference order.

        A policy may filter, reorder, or both. It may return an empty tuple —
        that is how a constraint reports "nothing here can serve this turn", and
        the router names the policy that emptied the list rather than reporting
        a bare "no model found".

        Must not raise for an ordinary "nothing matches"; an exception here is
        for a genuine programming error.
        """
        ...


@runtime_checkable
class ModelRouter(Protocol):
    """Chooses the model for one turn."""

    async def route(
        self,
        request: RoutingRequest,
        context: ExecutionContext,
    ) -> RoutingDecision:
        """Return the model to use, and why.

        Asynchronous because a later implementation may consult live health,
        observed latency or a remote policy service. The current implementation
        returns immediately; declaring it async now avoids a breaking signature
        change when it stops being immediate — the same reasoning as
        :class:`~agent_platform_sdk.interfaces.llm_provider_resolver.LLMProviderResolver`.

        Raises:
            NotFoundError: no registered model can serve the turn. The message
                must name the constraint that excluded the last candidate,
                because "no model available" sends the reader nowhere.
        """
        ...
