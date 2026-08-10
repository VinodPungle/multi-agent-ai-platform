"""Cost and usage reporting contracts.

What a dashboard, an endpoint or an operator asks the platform for. Separate
from :mod:`agent_platform_sdk.dto.evaluation`, which is one record about one
call — these are aggregates over many.

Every figure here is derived from `EvaluationRecord`s and nothing else, so the
same shape can be produced by an in-process counter today and by a query against
a time-series store later without the consumer changing.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["CostBreakdown", "CostSummary", "UsageTotals"]


class UsageTotals(BaseModel):
    """Aggregate consumption for one grouping."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    invocations: int = Field(default=0, ge=0, description="Model calls counted.")
    failures: int = Field(
        default=0,
        ge=0,
        description=(
            "Calls that did not succeed. Counted alongside the total rather "
            "than as a rate: a percentage hides whether it is two failures or "
            "two thousand."
        ),
    )
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    estimated_cost: Decimal = Field(
        default=Decimal(0),
        ge=0,
        description=(
            "Sum of per-call estimates, in the model's currency. `Decimal` "
            "throughout: fractions of a cent summed over many requests are "
            "exactly where binary floating point drifts. **Estimated** — it is "
            "computed from configured prices, not from an invoice, and a model "
            "with no pricing configured contributes zero rather than a guess."
        ),
    )
    average_latency_ms: float = Field(
        default=0.0,
        ge=0,
        description=(
            "Mean call duration. A mean, and named as one — it says nothing "
            "about the tail, which is what users notice. Percentiles need the "
            "individual records, which the logs keep."
        ),
    )

    @property
    def total_tokens(self) -> int:
        """Prompt plus completion."""
        return self.prompt_tokens + self.completion_tokens


class CostBreakdown(BaseModel):
    """Totals for one model, provider or agent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str = Field(description="Model id, provider id or agent id.")
    usage: UsageTotals


class CostSummary(BaseModel):
    """Everything the platform knows about what it has spent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    currency: str = Field(
        default="USD",
        description=(
            "ISO 4217 code every figure here is denominated in. Reported rather "
            "than assumed, because the platform converts between currencies "
            "nowhere and a total rendered with the wrong symbol is worse than "
            "no total at all."
        ),
    )
    overall: UsageTotals = Field(default_factory=UsageTotals)
    by_model: tuple[CostBreakdown, ...] = Field(default=())
    by_provider: tuple[CostBreakdown, ...] = Field(default=())
    by_agent: tuple[CostBreakdown, ...] = Field(default=())
