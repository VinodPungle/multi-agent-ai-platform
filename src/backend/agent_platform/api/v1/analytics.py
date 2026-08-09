"""Cost and usage analytics.

Answers the question an operator asks first and most often: *what is this
costing, and which model is responsible?*

Scope, stated plainly rather than buried
    Totals are counted **in this process**. They reset on restart and each
    replica sees only its own traffic, which the response says in a field rather
    than in documentation nobody reads. It is a live gauge, not a ledger — the
    ledger is the evaluation records in the structured log, which survive
    restarts and aggregate across replicas.

    Reporting a per-replica figure as though it were the whole platform's spend
    is the single easiest way to make a cost dashboard actively misleading, so
    the response is explicit about what it counted.

No authorisation, and why that is a real caveat
    Spend by model and by agent is commercially sensitive, and this endpoint is
    as open as the rest of the API. `CLAUDE.md` defers authorisation, so this
    follows suit — but it is exactly the kind of endpoint that needs it first,
    and the deployment note in the runbook says so.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from agent_platform.dependencies.providers import CostAnalyticsDep
from agent_platform_sdk.dto.analytics import CostSummary

__all__ = ["CostSummaryResponse", "router"]

router = APIRouter(tags=["analytics"])


class CostSummaryResponse(BaseModel):
    """Running totals, with the scope they were measured over."""

    model_config = ConfigDict(frozen=True)

    summary: CostSummary = Field(description="Totals overall and by model, provider and agent.")
    scope: str = Field(
        description=(
            "What these numbers cover. Present so a reader cannot mistake a "
            "single replica's counters for the platform's total spend."
        ),
    )


@router.get(
    "/costs",
    response_model=CostSummaryResponse,
    summary="Cost and usage totals",
    description=(
        "Token usage, estimated cost, failure counts and mean latency, grouped by model, "
        "provider and agent. Counted in this process only: totals reset on restart and "
        "are not shared between replicas. Costs are estimates computed from configured "
        "prices, not from an invoice."
    ),
)
async def costs(analytics: CostAnalyticsDep) -> CostSummaryResponse:
    """Return what this replica has spent since it started."""
    return CostSummaryResponse(
        summary=await analytics.summary(),
        scope=(
            "This process since startup. Totals reset on restart and are not "
            "aggregated across replicas; costs are estimates from configured "
            "prices, not billed amounts."
        ),
    )
