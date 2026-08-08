"""Budget policy.

Cost is treated as an architectural concern, not an operational afterthought
(``CLAUDE.md``). Limits are declared per agent and enforced by the runtime, so a
misbehaving agent cannot spend without bound.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["BudgetPolicy"]


class BudgetPolicy(BaseModel):
    """Ceilings the runtime enforces for a single request.

    Every limit is optional: ``None`` means unlimited. Defaults are unlimited so
    that Milestone 01 introduces no behaviour, and each later milestone opts in
    explicitly rather than inheriting a silent cap it did not choose.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_total_tokens: int | None = Field(
        default=None,
        gt=0,
        description="Combined prompt + completion tokens across the whole request.",
    )
    max_cost: Decimal | None = Field(
        default=None,
        gt=0,
        description="Maximum estimated spend for the request, in the model's currency.",
    )
    max_tool_invocations: int | None = Field(
        default=None,
        gt=0,
        description="Guards against tool-call loops, the usual cause of runaway cost.",
    )
    max_model_calls: int | None = Field(
        default=None,
        gt=0,
        description="Guards against reasoning loops that never reach a final answer.",
    )
