"""Runtime event publication contract.

``architecture.md`` §19 has the runtime publish an event at each lifecycle
boundary; the Event Bus section defers the bus itself. This interface is what
makes that deferral safe: the runtime publishes through it from Milestone 03, and
adding Service Bus, Event Grid or Kafka later is a new implementation rather than
re-instrumenting the runtime.

Publishing must never fail a request. An event is a description of work, not the
work — a runtime that returned an error because a bus was unreachable would have
made observability a source of outages. Implementations therefore swallow their
own failures and log them.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent_platform_sdk.events.runtime_events import RuntimeEvent

__all__ = ["EventPublisher"]


@runtime_checkable
class EventPublisher(Protocol):
    """Fan-out of runtime lifecycle events."""

    async def publish(self, event: RuntimeEvent) -> None:
        """Publish one event.

        Must not raise. A transport failure is logged by the implementation and
        the caller continues — see the module docstring.
        """
        ...
