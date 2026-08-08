"""Circuit breaker state, one per provider.

The mechanism behind :class:`~agent_platform_sdk.policies.circuit_breaker.CircuitBreakerPolicy`.
It holds the state a breaker needs and nothing else: no I/O, no logging of its
own, no knowledge of what is being called. The gateway owns the calling.

Concurrency
    Guarded by an `asyncio.Lock`. Without it, ten concurrent requests observing
    the fourth failure of a five-failure threshold each increment to five and
    the breaker opens on a burst that contained one round of failures. The
    critical sections are microseconds of arithmetic, so the lock costs nothing
    a model call would notice.

Time
    Injected as a `Clock`, never `time.monotonic()` directly. A breaker's
    entire behaviour is "what happens after N seconds", and a test that has to
    sleep for that is a test nobody runs.
"""

from __future__ import annotations

import asyncio
from enum import StrEnum

from agent_platform_sdk.policies.circuit_breaker import CircuitBreakerPolicy
from agent_platform_shared.clock import Clock

__all__ = ["CircuitBreaker", "CircuitState"]


class CircuitState(StrEnum):
    """Where a breaker currently is.

    Reported in telemetry and on the provider's health, so an operator can see
    that a provider is being skipped rather than inferring it from a gap in the
    request log.
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Tracks one provider's recent health and decides whether to call it."""

    def __init__(self, provider_id: str, policy: CircuitBreakerPolicy, clock: Clock) -> None:
        """Create a breaker.

        Args:
            provider_id: Provider this breaker guards. Reported, never used to
                decide anything — the breaker is deliberately ignorant of who it
                is protecting.
            policy: Thresholds and timeouts.
            clock: Injected time source, so tests advance time instead of
                sleeping through it.
        """
        self._provider_id = provider_id
        self._policy = policy
        self._clock = clock

        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._consecutive_successes = 0
        self._opened_at: float | None = None
        self._lock = asyncio.Lock()

    @property
    def provider_id(self) -> str:
        """Provider this breaker guards."""
        return self._provider_id

    @property
    def state(self) -> CircuitState:
        """Current state, for telemetry and health reporting.

        Read without the lock and therefore possibly a moment out of date. That
        is correct for an observation: taking the lock to report a value that
        can change immediately afterwards buys nothing and adds contention to
        the path that matters.
        """
        return self._state

    async def allows_request(self) -> bool:
        """Whether a call may be attempted now.

        Also performs the OPEN → HALF_OPEN transition, because that transition
        is caused by time passing and there is no other moment to notice it —
        nothing is running while the breaker is open.
        """
        if not self._policy.enabled:
            return True

        async with self._lock:
            if self._state is CircuitState.CLOSED:
                return True

            if self._state is CircuitState.HALF_OPEN:
                # One trial at a time. Letting a burst through would send the
                # full load at an upstream that has not yet proven it recovered.
                return False

            if self._opened_at is None:  # pragma: no cover - set whenever OPEN
                return True

            elapsed = self._clock.monotonic() - self._opened_at
            if elapsed < self._policy.reset_timeout_seconds:
                return False

            self._state = CircuitState.HALF_OPEN
            self._consecutive_successes = 0
            return True

    async def record_success(self) -> None:
        """Record a successful call."""
        if not self._policy.enabled:
            return

        async with self._lock:
            if self._state is CircuitState.HALF_OPEN:
                self._consecutive_successes += 1
                if self._consecutive_successes >= self._policy.half_open_successes:
                    self._close()
                return

            # A success in CLOSED clears the count. The threshold is
            # *consecutive* failures, so one success means the provider is
            # answering and the earlier failures are no longer evidence.
            self._consecutive_failures = 0

    async def record_failure(self) -> None:
        """Record a failure that counts against the provider.

        The caller decides whether a failure counts — the breaker cannot see the
        error, and a validation failure must never open it.
        """
        if not self._policy.enabled:
            return

        async with self._lock:
            if self._state is CircuitState.HALF_OPEN:
                # The trial failed. Straight back to OPEN for a full timeout
                # rather than allowing another trial immediately, which would
                # turn HALF_OPEN into a retry loop against a dead upstream.
                self._open()
                return

            self._consecutive_failures += 1
            if self._consecutive_failures >= self._policy.failure_threshold:
                self._open()

    async def snapshot(self) -> tuple[CircuitState, int]:
        """Return the state and consecutive failure count, consistently.

        Reading the two properties separately can straddle a transition and
        report a combination that never existed — "closed, with 7 failures"
        above a threshold of 5. Health output that impossible costs an operator
        more time than no output at all.
        """
        async with self._lock:
            return self._state, self._consecutive_failures

    # -- Internals ---------------------------------------------------------
    # Both assume the lock is held.

    def _open(self) -> None:
        self._state = CircuitState.OPEN
        self._opened_at = self._clock.monotonic()
        self._consecutive_successes = 0

    def _close(self) -> None:
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._consecutive_successes = 0
        self._opened_at = None
