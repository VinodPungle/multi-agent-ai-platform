"""Evaluation recording and cost aggregation.

The behaviours worth holding are the ones that make a cost figure trustworthy:
it counts failures, it counts abandoned turns, it uses `Decimal`, it attributes
to the model that actually answered, and it never fails a request to do any of
it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from agent_platform.evaluation.cost_analytics import (
    CompositeEvaluationProvider,
    InMemoryCostAnalytics,
)
from agent_platform.evaluation.logging_evaluation_provider import LoggingEvaluationProvider
from agent_platform.exceptions.base import ProviderError
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.dto.completion import TokenUsage
from agent_platform_sdk.dto.evaluation import EvaluationRecord
from agent_platform_sdk.interfaces.evaluation_provider import EvaluationProvider
from agent_platform_sdk.types.enums import HealthStatus

pytestmark = pytest.mark.unit

CONTEXT = ExecutionContext()


def a_record(
    model_id: str = "model-a",
    provider_id: str = "provider-a",
    agent_id: str | None = "chat-agent",
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
    cost: str | None = "0.01",
    latency_ms: float = 250.0,
    succeeded: bool = True,
) -> EvaluationRecord:
    return EvaluationRecord(
        correlation_id="c-1",
        request_id="r-1",
        agent_id=agent_id,
        provider_id=provider_id,
        model_id=model_id,
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        latency_ms=latency_ms,
        usage=TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        ),
        estimated_cost=Decimal(cost) if cost is not None else None,
        succeeded=succeeded,
    )


class TestContractConformance:
    def test_the_logging_provider_satisfies_the_contract(self) -> None:
        assert isinstance(LoggingEvaluationProvider(), EvaluationProvider)

    def test_the_analytics_provider_satisfies_the_contract(self) -> None:
        assert isinstance(InMemoryCostAnalytics(), EvaluationProvider)

    def test_the_composite_satisfies_the_contract(self) -> None:
        """It has to, or the runtime could not depend on one port."""
        assert isinstance(CompositeEvaluationProvider(()), EvaluationProvider)


class TestAggregation:
    async def test_tokens_and_cost_accumulate(self) -> None:
        analytics = InMemoryCostAnalytics()

        await analytics.record(a_record(), CONTEXT)
        await analytics.record(a_record(), CONTEXT)

        summary = await analytics.summary()
        assert summary.overall.invocations == 2
        assert summary.overall.prompt_tokens == 200
        assert summary.overall.estimated_cost == Decimal("0.02")

    async def test_cost_is_decimal_not_float(self) -> None:
        """Fractions of a cent, summed over many requests, are where floats drift."""
        analytics = InMemoryCostAnalytics()
        for _ in range(10):
            await analytics.record(a_record(cost="0.1"), CONTEXT)

        # A float sum of ten 0.1s is 0.9999999999999999.
        assert (await analytics.summary()).overall.estimated_cost == Decimal("1.0")

    async def test_it_groups_by_model_provider_and_agent(self) -> None:
        analytics = InMemoryCostAnalytics()

        await analytics.record(a_record(model_id="cheap", provider_id="p1"), CONTEXT)
        await analytics.record(a_record(model_id="dear", provider_id="p2", cost="1.00"), CONTEXT)

        summary = await analytics.summary()
        assert {row.key for row in summary.by_model} == {"cheap", "dear"}
        assert {row.key for row in summary.by_provider} == {"p1", "p2"}
        assert [row.key for row in summary.by_agent] == ["chat-agent"]

    async def test_the_most_expensive_is_listed_first(self) -> None:
        """The question being asked is "what is costing me money?"."""
        analytics = InMemoryCostAnalytics()

        await analytics.record(a_record(model_id="cheap", cost="0.01"), CONTEXT)
        await analytics.record(a_record(model_id="dear", cost="5.00"), CONTEXT)

        assert [row.key for row in (await analytics.summary()).by_model] == ["dear", "cheap"]

    async def test_ordering_is_stable_for_equal_costs(self) -> None:
        """A table that reshuffles between refreshes looks broken."""
        analytics = InMemoryCostAnalytics()
        await analytics.record(a_record(model_id="zeta"), CONTEXT)
        await analytics.record(a_record(model_id="alpha"), CONTEXT)

        first = [row.key for row in (await analytics.summary()).by_model]
        second = [row.key for row in (await analytics.summary()).by_model]

        assert first == second == ["alpha", "zeta"]

    async def test_failures_are_counted_not_discarded(self) -> None:
        """Data that counts only successes flatters the platform when it misbehaves."""
        analytics = InMemoryCostAnalytics()

        await analytics.record(a_record(succeeded=True), CONTEXT)
        await analytics.record(a_record(succeeded=False), CONTEXT)

        summary = await analytics.summary()
        assert summary.overall.invocations == 2
        assert summary.overall.failures == 1

    async def test_a_model_without_pricing_contributes_zero_not_a_guess(self) -> None:
        analytics = InMemoryCostAnalytics()

        await analytics.record(a_record(cost=None), CONTEXT)

        assert (await analytics.summary()).overall.estimated_cost == Decimal(0)

    async def test_average_latency_is_a_mean_over_invocations(self) -> None:
        analytics = InMemoryCostAnalytics()

        await analytics.record(a_record(latency_ms=100.0), CONTEXT)
        await analytics.record(a_record(latency_ms=300.0), CONTEXT)

        assert (await analytics.summary()).overall.average_latency_ms == pytest.approx(200.0)

    async def test_an_anonymous_record_does_not_create_an_agent_row(self) -> None:
        analytics = InMemoryCostAnalytics()

        await analytics.record(a_record(agent_id=None), CONTEXT)

        assert (await analytics.summary()).by_agent == ()

    async def test_concurrent_records_are_not_lost(self) -> None:
        """A cost figure that quietly undercounts is worse than none."""
        analytics = InMemoryCostAnalytics()

        await asyncio.gather(*(analytics.record(a_record(), CONTEXT) for _ in range(50)))

        assert (await analytics.summary()).overall.invocations == 50

    async def test_the_parts_add_up_to_the_whole(self) -> None:
        analytics = InMemoryCostAnalytics()
        await analytics.record(a_record(model_id="a", cost="1.00"), CONTEXT)
        await analytics.record(a_record(model_id="b", cost="2.00"), CONTEXT)

        summary = await analytics.summary()

        assert (
            sum((row.usage.estimated_cost for row in summary.by_model), Decimal(0))
            == summary.overall.estimated_cost
        )


class TestFanOut:
    async def test_every_sink_receives_the_record(self) -> None:
        analytics = InMemoryCostAnalytics()
        composite = CompositeEvaluationProvider((LoggingEvaluationProvider(), analytics))

        await composite.record(a_record(), CONTEXT)

        assert (await analytics.summary()).overall.invocations == 1

    async def test_one_failing_sink_does_not_silence_the_others(self) -> None:
        """Otherwise the first flaky sink added takes cost tracking down with it."""

        class BrokenSink:
            @property
            def provider_id(self) -> str:
                return "broken"

            async def initialize(self) -> None: ...

            async def close(self) -> None: ...

            def supports(self, capability: object) -> bool:
                del capability
                return False

            async def health_check(self) -> object:
                raise NotImplementedError

            async def record(self, record: object, context: object) -> None:
                del record, context
                message = "sink is down"
                raise RuntimeError(message)

        analytics = InMemoryCostAnalytics()
        composite = CompositeEvaluationProvider((BrokenSink(), analytics))  # type: ignore[arg-type]

        await composite.record(a_record(), CONTEXT)

        assert (await analytics.summary()).overall.invocations == 1

    async def test_recording_to_no_sinks_is_not_an_error(self) -> None:
        await CompositeEvaluationProvider(()).record(a_record(), CONTEXT)


class TestDisclosure:
    """What reaches the log, and — more importantly — what does not.

    Read from captured **stdout**, not `caplog`. structlog renders there, so
    `caplog.text` is empty for these events; an absence assertion against an
    empty string passes for the wrong reason and would keep passing if the
    provider started logging conversation content tomorrow. Each test below
    therefore asserts something is present before asserting something is not.
    """

    async def test_no_conversation_content_is_logged(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A record is counts, identifiers and money — never a copy of user data."""
        await LoggingEvaluationProvider().record(a_record(), CONTEXT)

        written = capsys.readouterr().out

        # Proves the capture works, so the absence assertions below mean something.
        assert "evaluation.recorded" in written
        assert "content" not in written
        assert "message" not in written

    async def test_cost_is_logged_without_float_rounding(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """`Decimal` is used precisely so fractions of a cent survive the round trip."""
        await LoggingEvaluationProvider().record(a_record(cost="0.000123"), CONTEXT)

        assert "0.000123" in capsys.readouterr().out


class TestHealth:
    async def test_the_logging_provider_reports_what_it_wrote(self) -> None:
        provider = LoggingEvaluationProvider()
        await provider.record(a_record(), CONTEXT)

        health = await provider.health_check()

        assert health.status is HealthStatus.HEALTHY
        assert "1 evaluation record" in (health.detail or "")

    async def test_analytics_health_states_its_scope(self) -> None:
        """A per-replica figure read as platform-wide spend is actively misleading."""
        health = await InMemoryCostAnalytics().health_check()

        assert "not shared between replicas" in (health.detail or "")


class TestRuntimeIntegration:
    """What the runtime actually records, driven through the real stack.

    `build_stack` wires the real runtime over the real composite evaluation
    provider, so these assert the whole chain rather than the aggregator alone.
    """

    async def test_a_completed_turn_is_recorded(
        self,
        build_stack: Callable[..., Any],
    ) -> None:
        stack = build_stack()
        turn = await stack.runtime.prepare("chat-agent", "hello", CONTEXT)
        await stack.runtime.execute(turn)

        summary = await stack.analytics.summary()

        assert summary.overall.invocations == 1
        assert summary.overall.failures == 0
        assert summary.overall.completion_tokens > 0

    async def test_spend_is_attributed_to_the_model_that_answered(
        self,
        build_stack: Callable[..., Any],
    ) -> None:
        """Not the model configured — routing may have chosen otherwise."""
        stack = build_stack()
        turn = await stack.runtime.prepare("chat-agent", "hello", CONTEXT)
        await stack.runtime.execute(turn)

        summary = await stack.analytics.summary()

        assert [row.key for row in summary.by_model] == [turn.routing.model_id]
        assert [row.key for row in summary.by_provider] == [turn.routing.provider_id]

    async def test_a_failed_turn_is_still_recorded(
        self,
        build_stack: Callable[..., Any],
    ) -> None:
        """Data counting only successes flatters the platform when it misbehaves."""
        stack = build_stack(failure=ProviderError("provider down", provider_id="fake"))
        turn = await stack.runtime.prepare("chat-agent", "hello", CONTEXT)

        with pytest.raises(ProviderError):
            await stack.runtime.execute(turn)

        summary = await stack.analytics.summary()

        assert summary.overall.invocations == 1
        assert summary.overall.failures == 1

    async def test_an_abandoned_stream_is_recorded_when_it_is_closed(
        self,
        build_stack: Callable[..., Any],
    ) -> None:
        """Tokens generated for a turn nobody read were still generated.

        The timing is the subtle part, and it is asserted rather than assumed:
        breaking out of the `async for` does **not** run the runtime's `finally`
        — closing the generator does, which is what the SSE layer and
        `async with` both do. An earlier comment in the runtime claimed the
        abandoned turn was measured without saying when; this is what corrected
        it.
        """
        stack = build_stack()
        turn = await stack.runtime.prepare("chat-agent", "hello", CONTEXT)

        stream = stack.runtime.stream(turn)
        async for _ in stream:
            break

        assert (await stack.analytics.summary()).overall.invocations == 0

        await stream.aclose()

        assert (await stack.analytics.summary()).overall.invocations == 1
