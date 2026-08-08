"""Evaluation provider contract.

Captures the execution telemetry described in ``architecture.md`` §40. The
initial implementation writes structured logs; later ones may write to
Application Insights, Cosmos DB or Azure Data Explorer.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.dto.evaluation import EvaluationRecord
from agent_platform_sdk.interfaces.provider import Provider

__all__ = ["EvaluationProvider"]


@runtime_checkable
class EvaluationProvider(Provider, Protocol):
    """Recording of model invocation telemetry."""

    async def record(self, record: EvaluationRecord, context: ExecutionContext) -> None:
        """Persist a single evaluation record.

        Must never raise and must never block the response path: telemetry is
        observability, and losing a record is always preferable to failing a
        user's request. Implementations that write over a network should buffer
        and drop rather than propagate failures.
        """
        ...
