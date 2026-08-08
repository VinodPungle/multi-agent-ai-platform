"""Timeout policy.

Separate budgets per hop. A single overall timeout is not enough: it cannot tell
a slow model apart from a hung tool, and it lets one slow dependency consume the
whole request budget before the others are even attempted.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["TimeoutPolicy"]


class TimeoutPolicy(BaseModel):
    """Wall-clock limits applied by the runtime at each boundary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_seconds: float = Field(
        default=120.0,
        gt=0,
        description="End-to-end budget for the whole request.",
    )
    model_call_seconds: float = Field(
        default=60.0,
        gt=0,
        description="Budget for a single provider call.",
    )
    tool_call_seconds: float = Field(
        default=30.0,
        gt=0,
        description="Budget for a single tool invocation.",
    )
    first_token_seconds: float = Field(
        default=30.0,
        gt=0,
        description=(
            "Budget for time-to-first-token when streaming. Detects a provider that "
            "accepted the connection but never began generating — a failure mode a "
            "total-duration timeout only catches much later."
        ),
    )
