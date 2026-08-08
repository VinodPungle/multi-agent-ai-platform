"""Circuit breaker policy.

``architecture.md`` §23 lists a circuit breaker as future work alongside the
retry policy. This is that work.

Why retry alone is not enough
    Retry assumes a failure is transient and that trying again is cheap. When a
    provider is genuinely down, both assumptions invert: every request pays the
    full timeout before failing, three times, and the retries themselves become
    load on a service that is already struggling.

    A user waits 3 x 60 seconds to be told what the first attempt already knew.
    Worse, the platform keeps that pressure on an upstream that might otherwise
    recover — the pattern that turns one provider's incident into a longer one.

    The breaker converts that into a fast, cheap failure: after enough
    consecutive failures it stops calling, fails immediately, and periodically
    lets one request through to test whether the upstream has come back.

The three states
    CLOSED    Normal. Calls pass through; consecutive failures are counted.
    OPEN      Failing fast. No call is attempted until the reset timeout expires.
    HALF_OPEN One trial call is allowed. Success closes the breaker; failure
              opens it again for another full timeout.

Per provider, never global
    A breaker shared across providers would let one provider's outage stop calls
    to a healthy one, which is the opposite of what it is for.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from agent_platform_sdk.types.enums import ErrorCategory

__all__ = ["CircuitBreakerPolicy"]

#: Failures that indicate the *provider* is unwell, and so should count towards
#: opening the breaker.
#:
#: Validation and policy failures are excluded deliberately: they are caused by
#: the request, not the provider, and a stream of malformed requests must never
#: cut off a healthy upstream for everyone else.
_DEFAULT_COUNTED: frozenset[ErrorCategory] = frozenset(
    {
        ErrorCategory.NETWORK,
        ErrorCategory.PROVIDER,
        ErrorCategory.TIMEOUT,
    }
)


class CircuitBreakerPolicy(BaseModel):
    """When to stop calling a provider that keeps failing."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = Field(
        default=True,
        description=(
            "Whether the breaker is active. A deployment with a single provider "
            "and no fallback may prefer to keep trying: an open breaker there "
            "means certain failure rather than unlikely success."
        ),
    )

    failure_threshold: int = Field(
        default=5,
        ge=1,
        description=(
            "Consecutive counted failures that open the breaker. Consecutive, "
            "not a rate: a rate needs a window and a minimum sample size to "
            "avoid opening on the first two requests after a quiet period, and "
            "this platform's traffic is too bursty for that to behave well."
        ),
    )

    reset_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        description=(
            "How long the breaker stays open before allowing a trial call. "
            "Long enough that probing does not become load of its own; short "
            "enough that recovery is noticed without a restart."
        ),
    )

    half_open_successes: int = Field(
        default=1,
        ge=1,
        description=(
            "Consecutive successes in HALF_OPEN needed to close the breaker. "
            "One is right for a stateless inference call — the trial request is "
            "a real user's request, and making them wait for several probes to "
            "pass helps nobody."
        ),
    )

    counted_categories: frozenset[ErrorCategory] = Field(
        default=_DEFAULT_COUNTED,
        description=(
            "Error categories that count towards opening. Validation and policy "
            "failures are excluded: they are the caller's fault, and a stream of "
            "malformed requests must not cut off a healthy provider."
        ),
    )

    def counts_towards_opening(self, category: ErrorCategory) -> bool:
        """Whether a failure of ``category`` should count against the provider."""
        return category in self.counted_categories
