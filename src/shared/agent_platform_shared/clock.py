"""Injectable time source.

Latency, time-to-first-token, budget windows and cache expiry all depend on the
current time. Calling :func:`datetime.datetime.now` directly makes those
behaviours untestable without patching global state, so the platform injects a
:class:`Clock` instead.

All timestamps are timezone-aware UTC. Naive datetimes are rejected by
convention because they silently compare incorrectly across environments.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

__all__ = ["Clock", "SystemClock"]


@runtime_checkable
class Clock(Protocol):
    """A source of the current time and of a monotonic duration counter."""

    def now(self) -> datetime:
        """Return the current instant as a timezone-aware UTC datetime."""
        ...

    def monotonic(self) -> float:
        """Return a monotonically increasing counter in seconds.

        Use this — never :meth:`now` — to measure elapsed time. Wall-clock time
        can jump backwards when NTP corrects the host, which produces negative
        or wildly inflated latency measurements.
        """
        ...


class SystemClock:
    """The real clock, backed by the operating system."""

    def now(self) -> datetime:
        """Return the current instant as a timezone-aware UTC datetime."""
        return datetime.now(UTC)

    def monotonic(self) -> float:
        """Return the value of a monotonic counter in fractional seconds."""
        return time.monotonic()
