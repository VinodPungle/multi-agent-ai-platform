"""Evaluation records, written to the structured log.

The first `EvaluationProvider`, and the one ADR-0005 named: a structured log
line per model invocation. Log analytics can already aggregate it, Application
Insights already ingests it, and it needs no new resource.

The constraint that shapes every line here
    A telemetry write must never fail a user's request. `record` therefore
    catches everything and swallows it. That is a rule this codebase otherwise
    treats with suspicion, and it is correct exactly here: losing one
    measurement is invisible to the user, and losing their answer because a log
    sink hiccupped is not.

What is deliberately absent
    No prompt text, no completion text, no user input. An evaluation record is
    counts, identifiers and money; it is exported to systems with different
    retention and access rules than the conversation itself, and the moment it
    carries content it becomes a second copy of user data nobody is governing
    (``CLAUDE.md``: never log sensitive user data).
"""

from __future__ import annotations

from agent_platform.telemetry.logging import get_logger
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.contracts.health import ComponentHealth
from agent_platform_sdk.dto.evaluation import EvaluationRecord
from agent_platform_sdk.types.enums import Capability, HealthStatus

__all__ = ["LoggingEvaluationProvider"]

_logger = get_logger(__name__)


class LoggingEvaluationProvider:
    """Writes each evaluation record as one structured log event.

    Satisfies
    :class:`~agent_platform_sdk.interfaces.evaluation_provider.EvaluationProvider`
    structurally — it inherits nothing, per ADR-0004.
    """

    def __init__(self, provider_id: str = "logging-evaluation") -> None:
        self._provider_id = provider_id
        self._written = 0
        self._dropped = 0

    @property
    def provider_id(self) -> str:
        """Identifier this provider is registered under."""
        return self._provider_id

    # -- Lifecycle ---------------------------------------------------------

    async def initialize(self) -> None:
        """Nothing to open. The logger already exists."""

    async def close(self) -> None:
        """Nothing to release."""

    def supports(self, capability: Capability) -> bool:
        """Declare nothing. Recording is not a model capability."""
        del capability
        return False

    async def health_check(self) -> ComponentHealth:
        """Always healthy: writing to a logger cannot be unavailable."""
        return ComponentHealth(
            name=self._provider_id,
            status=HealthStatus.HEALTHY,
            detail=(
                f"{self._written} evaluation record(s) written to the structured log"
                + (f", {self._dropped} dropped." if self._dropped else ".")
            ),
        )

    # -- Evaluation --------------------------------------------------------

    async def record(self, record: EvaluationRecord, context: ExecutionContext) -> None:
        """Write one record. Never raises."""
        del context
        try:
            _logger.info(
                "evaluation.recorded",
                # Flat fields rather than a nested object: a log analytics query
                # can filter and aggregate on a column, and has to unpack a blob.
                correlation_id=record.correlation_id,
                request_id=record.request_id,
                conversation_id=record.conversation_id,
                agent_id=record.agent_id,
                provider_id=record.provider_id,
                model_id=record.model_id,
                prompt_version=record.prompt_version,
                latency_ms=round(record.latency_ms, 2),
                time_to_first_token_ms=(
                    round(record.time_to_first_token_ms, 2)
                    if record.time_to_first_token_ms is not None
                    else None
                ),
                prompt_tokens=record.usage.prompt_tokens,
                completion_tokens=record.usage.completion_tokens,
                total_tokens=record.usage.total_tokens,
                # A string, not a float. `Decimal` is used throughout precisely
                # so fractions of a cent do not drift, and rendering it as a
                # float here would reintroduce the error at the last step.
                estimated_cost=(
                    str(record.estimated_cost) if record.estimated_cost is not None else None
                ),
                succeeded=record.succeeded,
                streaming=record.streaming,
            )
            self._written += 1
        except Exception:  # noqa: BLE001 - telemetry must never fail a request
            # Deliberately not re-logged: the logger is the thing that just
            # failed, so logging about it is the least likely action to work —
            # and a recursive failure here would be far worse than a lost
            # measurement.
            self._dropped += 1

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"LoggingEvaluationProvider(written={self._written})"
