"""The execution context that accompanies every platform operation.

``architecture.md`` §20 requires a single context object to flow through every
component of a request. Without it each layer would grow its own ad-hoc bundle
of ids, and cross-layer telemetry would have nothing to join on.

The context is **immutable**. Deriving a child with :meth:`ExecutionContext.derive`
rather than mutating in place means a value captured by a background task cannot
be changed underneath it by the code that spawned it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field

from agent_platform_shared import new_correlation_id, new_request_id

__all__ = ["ExecutionContext"]


class ExecutionContext(BaseModel):
    """Identity, routing and policy metadata for one unit of platform work.

    Fields marked *future* are declared now because adding an identifier to a
    context that already flows everywhere is cheap, whereas retrofitting one
    later means touching every layer at once.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # --- Identity -----------------------------------------------------------
    correlation_id: str = Field(
        default_factory=new_correlation_id,
        description="Spans the whole logical operation, across services and agent hand-offs.",
    )
    request_id: str = Field(
        default_factory=new_request_id,
        description="Identifies a single inbound request within a correlation.",
    )
    conversation_id: str | None = Field(
        default=None,
        description="Conversation this work belongs to. Set from Milestone 02.",
    )
    session_id: str | None = Field(
        default=None,
        description="Client session. Set from Milestone 02.",
    )
    workflow_id: str | None = Field(
        default=None,
        description="Workflow execution. Set from Milestone 03.",
    )
    execution_id: str | None = Field(
        default=None,
        description="Single agent execution within a workflow. Set from Milestone 03.",
    )
    agent_id: str | None = Field(
        default=None,
        description="Agent performing the work. Set from Milestone 03.",
    )

    # --- Tenancy (future) ---------------------------------------------------
    user_id: str | None = Field(default=None, description="Authenticated user. Future.")
    tenant_id: str | None = Field(default=None, description="Owning tenant. Future.")

    # --- Routing ------------------------------------------------------------
    provider_id: str | None = Field(
        default=None,
        description="Resolved provider. Set by the runtime, never by an agent.",
    )
    model_id: str | None = Field(
        default=None,
        description="Resolved model. Set by the runtime from the model registry.",
    )
    prompt_version: str | None = Field(
        default=None,
        description="Version of the prompt asset used, for evaluation and rollback.",
    )

    # --- Environment --------------------------------------------------------
    delegation_depth: int = Field(
        default=0,
        ge=0,
        description=(
            "How many agents deep this execution is. Zero for a user's request, "
            "one for an agent the runtime invoked on its behalf, and so on. "
            "Carried on the context rather than tracked by the runtime because "
            "it must survive every hop the context takes — through a tool, into "
            "another agent, and back. A counter held anywhere else is a counter "
            "that resets at exactly the moment a cycle would be caught."
        ),
    )

    locale: str = Field(default="en-US", description="BCP 47 locale for responses.")
    feature_flags: dict[str, bool] = Field(
        default_factory=dict,
        description="Effective flags for this operation, resolved once at entry.",
    )

    # --- Timing -------------------------------------------------------------
    started_at: datetime | None = Field(
        default=None,
        description="UTC instant the operation began, supplied by an injected Clock.",
    )
    deadline_seconds: float | None = Field(
        default=None,
        gt=0,
        description="Wall-clock budget for the whole operation.",
    )

    def derive(self, **overrides: Any) -> Self:  # noqa: ANN401 - forwards to model_copy
        """Return a copy of this context with ``overrides`` applied.

        Used when the runtime narrows a request-scoped context into an
        agent-scoped or tool-scoped one. The correlation id is carried through
        unchanged so the whole tree remains joinable in telemetry.
        """
        return self.model_copy(update=overrides)

    def to_log_fields(self) -> dict[str, str]:
        """Return the populated identifiers as flat string fields.

        Emitted as log attributes and span attributes. ``None`` values are
        dropped so records stay compact and queries do not have to filter nulls.
        """
        candidates: dict[str, str | None] = {
            "correlation_id": self.correlation_id,
            "request_id": self.request_id,
            "conversation_id": self.conversation_id,
            "session_id": self.session_id,
            "workflow_id": self.workflow_id,
            "execution_id": self.execution_id,
            "agent_id": self.agent_id,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "prompt_version": self.prompt_version,
        }
        return {key: value for key, value in candidates.items() if value is not None}
