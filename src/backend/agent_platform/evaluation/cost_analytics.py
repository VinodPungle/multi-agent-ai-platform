"""Running totals of what the platform has spent.

`CLAUDE.md` asks the architecture to support dashboards showing cost by
provider, by model, by agent and over time. This is the smallest thing that
makes those answerable *now*: an `EvaluationProvider` that, instead of writing a
record somewhere, adds it to in-process counters an endpoint can read.

Why in-process, and what that honestly costs
    Totals reset on restart and each replica counts only its own traffic. That
    is not a dashboard and is not claimed to be one — the durable answer is
    querying the logs the sibling provider already writes, or a time-series
    store.

    What it *is* good for is the question people actually ask first, in the
    moment they ask it: "what is this costing right now, and which model is
    responsible?" Answering that needed no new resource, so it exists.

Why it is a provider rather than a special case
    Because then the runtime records once, to one port, and the composition root
    decides how many things listen — see :class:`CompositeEvaluationProvider`.
    Adding an Application Insights or Cosmos DB sink later changes a list in the
    container and nothing else.

Cost is `Decimal` all the way through
    Fractions of a cent, summed over a lot of requests, are exactly where binary
    floating point drifts. The platform prices in `Decimal` and this keeps it.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from decimal import Decimal

from agent_platform.telemetry.logging import get_logger
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.contracts.health import ComponentHealth
from agent_platform_sdk.dto.analytics import CostBreakdown, CostSummary, UsageTotals
from agent_platform_sdk.dto.evaluation import EvaluationRecord
from agent_platform_sdk.interfaces.evaluation_provider import EvaluationProvider
from agent_platform_sdk.types.enums import Capability, HealthStatus

__all__ = ["CompositeEvaluationProvider", "InMemoryCostAnalytics"]

_logger = get_logger(__name__)


class _Totals:
    """Mutable accumulator for one grouping key."""

    __slots__ = (
        "completion_tokens",
        "cost",
        "failures",
        "invocations",
        "latency_ms_total",
        "prompt_tokens",
    )

    def __init__(self) -> None:
        self.invocations = 0
        self.failures = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.cost = Decimal(0)
        self.latency_ms_total = 0.0

    def add(self, record: EvaluationRecord) -> None:
        self.invocations += 1
        if not record.succeeded:
            self.failures += 1
        self.prompt_tokens += record.usage.prompt_tokens
        self.completion_tokens += record.usage.completion_tokens
        self.cost += record.estimated_cost or Decimal(0)
        self.latency_ms_total += record.latency_ms

    def to_usage(self) -> UsageTotals:
        return UsageTotals(
            invocations=self.invocations,
            failures=self.failures,
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            estimated_cost=self.cost,
            average_latency_ms=(
                self.latency_ms_total / self.invocations if self.invocations else 0.0
            ),
        )


class InMemoryCostAnalytics:
    """Aggregates evaluation records into totals an endpoint can read.

    Satisfies
    :class:`~agent_platform_sdk.interfaces.evaluation_provider.EvaluationProvider`
    structurally — it inherits nothing, per ADR-0004.
    """

    def __init__(self, provider_id: str = "cost-analytics") -> None:
        self._provider_id = provider_id
        self._overall = _Totals()
        self._by_model: dict[str, _Totals] = defaultdict(_Totals)
        self._by_provider: dict[str, _Totals] = defaultdict(_Totals)
        self._by_agent: dict[str, _Totals] = defaultdict(_Totals)
        # Records arrive from request handlers running concurrently. The
        # increments are not atomic, and without this two simultaneous turns can
        # lose one — a cost figure that quietly undercounts is worse than none.
        self._lock = asyncio.Lock()

    @property
    def provider_id(self) -> str:
        """Identifier this provider is registered under."""
        return self._provider_id

    # -- Lifecycle ---------------------------------------------------------

    async def initialize(self) -> None:
        """Nothing to open."""

    async def close(self) -> None:
        """Nothing to release. Totals go with the process, by design."""

    def supports(self, capability: Capability) -> bool:
        """Declare nothing. Aggregation is not a model capability."""
        del capability
        return False

    async def health_check(self) -> ComponentHealth:
        """Report what has been counted so far."""
        return ComponentHealth(
            name=self._provider_id,
            status=HealthStatus.HEALTHY,
            detail=(
                f"{self._overall.invocations} invocation(s) counted in this process. "
                "Totals reset on restart and are not shared between replicas."
            ),
        )

    # -- Evaluation --------------------------------------------------------

    async def record(self, record: EvaluationRecord, context: ExecutionContext) -> None:
        """Add one record to the totals. Never raises."""
        del context
        try:
            async with self._lock:
                self._overall.add(record)
                self._by_model[record.model_id].add(record)
                self._by_provider[record.provider_id].add(record)
                if record.agent_id:
                    self._by_agent[record.agent_id].add(record)
        except Exception:
            _logger.warning("analytics.record_failed", exc_info=True)

    # -- Reporting ---------------------------------------------------------

    async def summary(self) -> CostSummary:
        """Return the totals, broken down three ways.

        A snapshot taken under the lock: reading each grouping separately would
        let a record land between them and produce a summary whose parts do not
        add up to its whole — which is exactly the kind of small inconsistency
        that destroys trust in a cost figure.
        """
        async with self._lock:
            return CostSummary(
                overall=self._overall.to_usage(),
                by_model=_breakdown(self._by_model),
                by_provider=_breakdown(self._by_provider),
                by_agent=_breakdown(self._by_agent),
            )

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"InMemoryCostAnalytics(invocations={self._overall.invocations})"


class CompositeEvaluationProvider:
    """Fans one record out to several providers.

    The reason the runtime can stay ignorant of how many sinks exist: it records
    once, to one port, and the composition root decides who listens.

    A failing provider does not stop the others, and none of them can fail a
    request — the contract already says `record` must never raise, and this
    enforces it rather than trusting it.
    """

    def __init__(
        self,
        providers: tuple[EvaluationProvider, ...],
        provider_id: str = "evaluation",
    ) -> None:
        self._providers = providers
        self._provider_id = provider_id

    @property
    def provider_id(self) -> str:
        """Identifier this provider is registered under."""
        return self._provider_id

    async def initialize(self) -> None:
        """Initialise each sink."""
        for provider in self._providers:
            await provider.initialize()

    async def close(self) -> None:
        """Close each sink, whatever the others do."""
        for provider in self._providers:
            try:
                await provider.close()
            except Exception:
                _logger.warning(
                    "analytics.close_failed",
                    provider_id=provider.provider_id,
                    exc_info=True,
                )

    def supports(self, capability: Capability) -> bool:
        """Declare nothing."""
        del capability
        return False

    async def health_check(self) -> ComponentHealth:
        """Report the sinks it fans out to."""
        return ComponentHealth(
            name=self._provider_id,
            status=HealthStatus.HEALTHY,
            detail=f"Recording to: {', '.join(p.provider_id for p in self._providers) or 'nothing'}.",
        )

    async def record(self, record: EvaluationRecord, context: ExecutionContext) -> None:
        """Pass the record to every sink. Never raises."""
        for provider in self._providers:
            try:
                await provider.record(record, context)
            except Exception:
                _logger.warning(
                    "analytics.sink_failed",
                    provider_id=provider.provider_id,
                    exc_info=True,
                )


def _breakdown(totals: dict[str, _Totals]) -> tuple[CostBreakdown, ...]:
    """Convert a grouping into rows, most expensive first.

    Ordered by cost because that is the question being asked. Ties break on the
    key so the output is stable between calls — a table that reshuffles between
    refreshes looks broken even when the numbers are right.
    """
    rows = [
        CostBreakdown(key=key, usage=accumulated.to_usage()) for key, accumulated in totals.items()
    ]
    rows.sort(key=lambda row: (-row.usage.estimated_cost, row.key))
    return tuple(rows)
