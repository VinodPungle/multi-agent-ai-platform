"""Runtime event definitions.

``architecture.md`` §19 has the runtime publish events at each lifecycle
boundary. Defining them as contracts now — before any bus exists — is what keeps
the future event bus (Service Bus, Event Grid, Kafka) an additive change: a
publisher implementation, not a re-instrumentation of the runtime.

Milestone 01 declares the vocabulary. Publication arrives with the runtime in
Milestone 03.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["RuntimeEvent", "RuntimeEventName"]


class RuntimeEventName(StrEnum):
    """The lifecycle boundaries the runtime reports."""

    REQUEST_RECEIVED = "request.received"
    WORKFLOW_STARTED = "workflow.started"
    WORKFLOW_COMPLETED = "workflow.completed"
    WORKFLOW_FAILED = "workflow.failed"
    AGENT_STARTED = "agent.started"
    AGENT_COMPLETED = "agent.completed"
    AGENT_FAILED = "agent.failed"
    MODEL_INVOKED = "model.invoked"
    MODEL_COMPLETED = "model.completed"
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    MEMORY_LOADED = "memory.loaded"
    MEMORY_UPDATED = "memory.updated"
    POLICY_VIOLATED = "policy.violated"


class RuntimeEvent(BaseModel):
    """A single runtime occurrence.

    One event type with a name field, rather than a class per event. A bus
    consumer can then subscribe, route and store every event uniformly, and
    adding an event name does not require every consumer to learn a new type.

    ``payload`` is intentionally loose: it carries event-specific detail whose
    shape differs per event and which consumers treat as diagnostic data.
    Anything a consumer must be able to rely on belongs in a typed field above.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: RuntimeEventName = Field(description="Which lifecycle boundary this reports.")
    occurred_at: datetime = Field(description="UTC instant the event was raised.")

    correlation_id: str = Field(description="Joins this event to the rest of the operation.")
    request_id: str | None = None
    workflow_id: str | None = None
    execution_id: str | None = None
    agent_id: str | None = None

    payload: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Event-specific detail. Must never contain secrets or user content — "
            "events may be persisted and fanned out to systems with different "
            "retention and access rules than the request itself."
        ),
    )
