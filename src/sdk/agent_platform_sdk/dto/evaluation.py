"""Evaluation record contract.

``CLAUDE.md`` requires every model invocation to emit evaluation metadata. This
is the record that makes model benchmarking, cost dashboards and regression
detection possible later without re-instrumenting anything.

The initial implementation writes these to structured logs; future ones may
write to Application Insights, Cosmos DB or Azure Data Explorer. The record
shape does not change when the sink does.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from agent_platform_sdk.dto.completion import TokenUsage

__all__ = ["EvaluationRecord"]


class EvaluationRecord(BaseModel):
    """Telemetry captured for a single model invocation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # --- Attribution --------------------------------------------------------
    correlation_id: str
    request_id: str
    conversation_id: str | None = None
    session_id: str | None = None
    agent_id: str | None = None

    # --- Routing ------------------------------------------------------------
    provider_id: str
    model_id: str
    deployment_name: str | None = None
    prompt_version: str | None = None

    # --- Timing -------------------------------------------------------------
    occurred_at: datetime = Field(description="UTC instant the call completed.")
    latency_ms: float = Field(ge=0, description="Total call duration.")
    time_to_first_token_ms: float | None = Field(
        default=None,
        ge=0,
        description=(
            "Streaming only. Tracked separately from total latency because it is what "
            "users perceive as responsiveness."
        ),
    )

    # --- Consumption --------------------------------------------------------
    usage: TokenUsage = Field(default_factory=TokenUsage)
    estimated_cost: Decimal | None = Field(default=None, ge=0)

    # --- Outcome ------------------------------------------------------------
    succeeded: bool
    streaming: bool = False
    retry_count: int = Field(default=0, ge=0)
    tool_invocations: int = Field(default=0, ge=0)
    error_category: str | None = Field(
        default=None,
        description="ErrorCategory value when the call failed.",
    )
