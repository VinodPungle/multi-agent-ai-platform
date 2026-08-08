"""Runtime event publication, backed by structured logs.

The first :class:`~agent_platform_sdk.interfaces.event_publisher.EventPublisher`.
Events go to the logging pipeline, which already carries correlation ids, trace
context and structured fields — so they are queryable from day one without
provisioning a bus nobody is consuming yet.

The bus (Service Bus, Event Grid, Kafka) is a second implementation, not a
rewrite. That is the whole reason the runtime publishes through an interface
rather than logging directly: the call sites are already correct.

Publishing never fails a request. An event describes work; it is not the work. A
runtime that returned an error because a sink was unavailable would have turned
observability into a source of outages.
"""

from __future__ import annotations

from agent_platform.telemetry.logging import get_logger
from agent_platform_sdk.events.runtime_events import RuntimeEvent, RuntimeEventName
from agent_platform_shared.clock import Clock

__all__ = ["LoggingEventPublisher", "build_event"]

_logger = get_logger(__name__)


def build_event(
    name: RuntimeEventName,
    clock: Clock,
    correlation_id: str,
    *,
    request_id: str | None = None,
    workflow_id: str | None = None,
    execution_id: str | None = None,
    agent_id: str | None = None,
    payload: dict[str, object] | None = None,
) -> RuntimeEvent:
    """Construct an event with its timestamp taken from an injected clock.

    A helper rather than a constructor call at each site, because every event
    needs the same timestamp treatment and `datetime.now()` scattered through the
    runtime would make event ordering untestable.
    """
    return RuntimeEvent(
        name=name,
        occurred_at=clock.now(),
        correlation_id=correlation_id,
        request_id=request_id,
        workflow_id=workflow_id,
        execution_id=execution_id,
        agent_id=agent_id,
        payload=dict(payload or {}),
    )


class LoggingEventPublisher:
    """Writes runtime events to the structured logging pipeline.

    Satisfies :class:`EventPublisher` structurally.
    """

    async def publish(self, event: RuntimeEvent) -> None:
        """Record one event. Never raises."""
        try:
            _logger.info(
                f"event.{event.name.value}",
                event_name=event.name.value,
                occurred_at=event.occurred_at.isoformat(),
                correlation_id=event.correlation_id,
                request_id=event.request_id,
                workflow_id=event.workflow_id,
                execution_id=event.execution_id,
                agent_id=event.agent_id,
                **event.payload,
            )
        except Exception:  # noqa: BLE001 - see the module docstring
            # Deliberately blind and deliberately silent about the cause: this is
            # the failure path *of* the logging pipeline, so re-logging the error
            # is the one thing guaranteed not to work.
            return
