"""Retry policy.

``architecture.md`` §23 sets the rules the runtime follows: retry transient
provider failures, never retry validation failures, and use exponential backoff
with jitter.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from agent_platform_sdk.types.enums import ErrorCategory

__all__ = ["RetryPolicy"]

#: Categories that are safe to retry. Validation and policy failures are
#: deterministic — retrying them wastes budget and delays the error the caller
#: needs to see.
_DEFAULT_RETRYABLE: frozenset[ErrorCategory] = frozenset(
    {
        ErrorCategory.NETWORK,
        ErrorCategory.PROVIDER,
        ErrorCategory.TIMEOUT,
    }
)


class RetryPolicy(BaseModel):
    """Exponential backoff configuration for calls to external systems."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_attempts: int = Field(
        default=3,
        ge=1,
        description="Total attempts including the first. 1 disables retrying.",
    )
    initial_backoff_seconds: float = Field(default=0.5, gt=0)
    backoff_multiplier: float = Field(
        default=2.0,
        ge=1.0,
        description="Factor applied to the delay after each failed attempt.",
    )
    max_backoff_seconds: float = Field(
        default=30.0,
        gt=0,
        description="Ceiling on a single delay, so backoff cannot exceed the request deadline.",
    )
    jitter: bool = Field(
        default=True,
        description=(
            "Randomises delays. Without it, replicas that fail together retry together "
            "and re-create the load spike that caused the failure."
        ),
    )
    retryable_categories: frozenset[ErrorCategory] = Field(default=_DEFAULT_RETRYABLE)

    def is_retryable(self, category: ErrorCategory) -> bool:
        """Return whether a failure of ``category`` may be retried."""
        return category in self.retryable_categories
