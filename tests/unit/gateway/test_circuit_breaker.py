"""Circuit breaker behaviour.

Time is advanced, never slept through. A breaker's entire behaviour is "what
happens after N seconds", and a suite that waited for a 30-second reset timeout
would take minutes and be deleted within a week.

The gateway tests at the bottom are the ones that matter operationally: the
breaker in isolation is arithmetic, and the interesting question is whether the
gateway consults it at the right moments.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from agent_platform.exceptions.base import ProviderError, ValidationError
from agent_platform.gateway.circuit_breaker import CircuitBreaker, CircuitState
from agent_platform.gateway.llm_gateway import DefaultLLMGateway
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.contracts.health import ComponentHealth
from agent_platform_sdk.dto.completion import (
    CompletionChunk,
    CompletionRequest,
    CompletionResponse,
    TokenUsage,
)
from agent_platform_sdk.dto.message import Message
from agent_platform_sdk.dto.model import ModelDescriptor
from agent_platform_sdk.interfaces.llm_provider import LLMProvider
from agent_platform_sdk.policies.circuit_breaker import CircuitBreakerPolicy
from agent_platform_sdk.policies.retry import RetryPolicy
from agent_platform_sdk.policies.timeout import TimeoutPolicy
from agent_platform_sdk.types.enums import (
    Capability,
    ErrorCategory,
    HealthStatus,
    MessageRole,
)

pytestmark = pytest.mark.unit

CONTEXT = ExecutionContext()


class ManualClock:
    """A clock that only moves when a test moves it."""

    def __init__(self) -> None:
        self._monotonic = 0.0

    def now(self) -> datetime:
        return datetime(2026, 1, 1, tzinfo=UTC)

    def monotonic(self) -> float:
        return self._monotonic

    def advance(self, seconds: float) -> None:
        self._monotonic += seconds


def build_breaker(clock: ManualClock, **overrides: Any) -> CircuitBreaker:  # noqa: ANN401
    policy = CircuitBreakerPolicy(**overrides)
    return CircuitBreaker("test-provider", policy, clock)


class TestClosedState:
    async def test_a_healthy_provider_is_always_allowed(self) -> None:
        breaker = build_breaker(ManualClock())

        assert await breaker.allows_request() is True
        assert breaker.state is CircuitState.CLOSED

    async def test_failures_below_the_threshold_keep_it_closed(self) -> None:
        breaker = build_breaker(ManualClock(), failure_threshold=3)

        await breaker.record_failure()
        await breaker.record_failure()

        assert breaker.state is CircuitState.CLOSED
        assert await breaker.allows_request() is True

    async def test_a_success_clears_the_failure_count(self) -> None:
        """The threshold counts *consecutive* failures.

        A provider that fails twice, succeeds, then fails twice more is working
        intermittently, not down. Opening on it would be wrong.
        """
        breaker = build_breaker(ManualClock(), failure_threshold=3)

        await breaker.record_failure()
        await breaker.record_failure()
        await breaker.record_success()
        await breaker.record_failure()
        await breaker.record_failure()

        assert breaker.state is CircuitState.CLOSED


class TestOpening:
    async def test_it_opens_at_the_threshold(self) -> None:
        breaker = build_breaker(ManualClock(), failure_threshold=3)

        for _ in range(3):
            await breaker.record_failure()

        assert breaker.state is CircuitState.OPEN

    async def test_an_open_breaker_refuses_calls(self) -> None:
        """The point: fail immediately rather than pay the timeout again."""
        breaker = build_breaker(ManualClock(), failure_threshold=1)
        await breaker.record_failure()

        assert await breaker.allows_request() is False

    async def test_it_stays_open_for_the_whole_reset_timeout(self) -> None:
        clock = ManualClock()
        breaker = build_breaker(clock, failure_threshold=1, reset_timeout_seconds=30)
        await breaker.record_failure()

        clock.advance(29.9)

        assert await breaker.allows_request() is False
        assert breaker.state is CircuitState.OPEN


class TestHalfOpen:
    async def test_a_trial_call_is_allowed_once_the_timeout_expires(self) -> None:
        clock = ManualClock()
        breaker = build_breaker(clock, failure_threshold=1, reset_timeout_seconds=30)
        await breaker.record_failure()

        clock.advance(30)

        assert await breaker.allows_request() is True
        assert breaker.state is CircuitState.HALF_OPEN

    async def test_only_one_trial_is_allowed_at_a_time(self) -> None:
        """A burst through HALF_OPEN would hit an upstream that has proven nothing."""
        clock = ManualClock()
        breaker = build_breaker(clock, failure_threshold=1, reset_timeout_seconds=30)
        await breaker.record_failure()
        clock.advance(30)

        assert await breaker.allows_request() is True
        assert await breaker.allows_request() is False

    async def test_a_successful_trial_closes_the_breaker(self) -> None:
        clock = ManualClock()
        breaker = build_breaker(clock, failure_threshold=1, reset_timeout_seconds=30)
        await breaker.record_failure()
        clock.advance(30)
        await breaker.allows_request()

        await breaker.record_success()

        assert breaker.state is CircuitState.CLOSED
        assert await breaker.allows_request() is True

    async def test_a_failed_trial_reopens_for_a_full_timeout(self) -> None:
        """Otherwise HALF_OPEN degenerates into a retry loop against a dead upstream."""
        clock = ManualClock()
        breaker = build_breaker(clock, failure_threshold=1, reset_timeout_seconds=30)
        await breaker.record_failure()
        clock.advance(30)
        await breaker.allows_request()

        await breaker.record_failure()

        assert breaker.state is CircuitState.OPEN
        clock.advance(29)
        assert await breaker.allows_request() is False

    async def test_several_successes_can_be_required(self) -> None:
        clock = ManualClock()
        breaker = build_breaker(
            clock, failure_threshold=1, reset_timeout_seconds=10, half_open_successes=2
        )
        await breaker.record_failure()
        clock.advance(10)
        await breaker.allows_request()

        await breaker.record_success()
        after_one, _ = await breaker.snapshot()
        assert after_one is CircuitState.HALF_OPEN

        await breaker.record_success()
        after_two, _ = await breaker.snapshot()
        assert after_two is CircuitState.CLOSED


class TestDisabled:
    async def test_a_disabled_breaker_never_refuses(self) -> None:
        """A deployment with one provider and no fallback may prefer to keep trying."""
        breaker = build_breaker(ManualClock(), enabled=False, failure_threshold=1)

        for _ in range(10):
            await breaker.record_failure()

        assert await breaker.allows_request() is True
        assert breaker.state is CircuitState.CLOSED


class TestPolicy:
    def test_provider_failures_count_towards_opening(self) -> None:
        policy = CircuitBreakerPolicy()

        assert policy.counts_towards_opening(ErrorCategory.PROVIDER) is True
        assert policy.counts_towards_opening(ErrorCategory.TIMEOUT) is True
        assert policy.counts_towards_opening(ErrorCategory.NETWORK) is True

    def test_the_callers_own_mistakes_do_not(self) -> None:
        """A stream of malformed requests must not cut off a healthy provider."""
        policy = CircuitBreakerPolicy()

        assert policy.counts_towards_opening(ErrorCategory.VALIDATION) is False
        assert policy.counts_towards_opening(ErrorCategory.POLICY_VIOLATION) is False


class TestSnapshot:
    async def test_state_and_count_are_read_together(self) -> None:
        """Separate reads can straddle a transition and report an impossible pair."""
        breaker = build_breaker(ManualClock(), failure_threshold=5)
        await breaker.record_failure()
        await breaker.record_failure()

        state, failures = await breaker.snapshot()

        assert state is CircuitState.CLOSED
        assert failures == 2


# --- Through the gateway -----------------------------------------------------


class ScriptedProvider:
    """A provider that fails a set number of times, then succeeds.

    Implements the whole `LLMProvider` protocol, including the parts these
    tests never call. A double narrower than the contract passes until the code
    under test reaches for a method it legitimately has — which is how this one
    first failed, on `estimate_cost`.
    """

    def __init__(self, failures: int, error: Exception | None = None) -> None:
        self._remaining = failures
        self._error = error or ProviderError("upstream down", provider_id="test-provider")
        self.calls = 0

    @property
    def provider_id(self) -> str:
        return "test-provider"

    async def initialize(self) -> None:
        return None

    async def close(self) -> None:
        return None

    def supports(self, capability: Capability) -> bool:
        del capability
        return True

    async def health_check(self) -> ComponentHealth:
        return ComponentHealth(name=self.provider_id, status=HealthStatus.HEALTHY)

    async def count_tokens(self, request: CompletionRequest) -> TokenUsage:
        del request
        return TokenUsage(prompt_tokens=1)

    def estimate_cost(self, model_id: str, usage: TokenUsage) -> Decimal:
        del model_id, usage
        return Decimal(0)

    async def list_models(self) -> tuple[ModelDescriptor, ...]:
        return ()

    async def stream(
        self, request: CompletionRequest, context: ExecutionContext
    ) -> AsyncIterator[CompletionChunk]:
        del request, context
        yield CompletionChunk(delta="ok", finish_reason="stop")

    async def generate(
        self, request: CompletionRequest, context: ExecutionContext
    ) -> CompletionResponse:
        del context
        self.calls += 1
        if self._remaining > 0:
            self._remaining -= 1
            raise self._error
        return CompletionResponse(
            message=Message(role=MessageRole.ASSISTANT, content="ok"),
            model_id=request.model_id,
            provider_id=self.provider_id,
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1),
        )


class StaticResolver:
    def __init__(self, provider: ScriptedProvider) -> None:
        self._provider = provider

    async def resolve(self, model_id: str, context: ExecutionContext) -> ScriptedProvider:
        del model_id, context
        return self._provider


def build_gateway(
    provider: ScriptedProvider,
    clock: ManualClock,
    **breaker_overrides: Any,  # noqa: ANN401
) -> DefaultLLMGateway:
    return DefaultLLMGateway(
        resolver=StaticResolver(provider),
        clock=clock,
        # One attempt, so a test's failure count is the provider's call count.
        retry_policy=RetryPolicy(max_attempts=1),
        timeout_policy=TimeoutPolicy(),
        circuit_breaker_policy=CircuitBreakerPolicy(**breaker_overrides),
    )


def a_request() -> CompletionRequest:
    return CompletionRequest(
        model_id="test-model",
        messages=(Message(role=MessageRole.USER, content="hello"),),
    )


class TestGatewayIntegration:
    async def test_the_gateway_stops_calling_a_dead_provider(self) -> None:
        """The behaviour this exists for: stop paying the timeout."""
        provider = ScriptedProvider(failures=100)
        gateway = build_gateway(provider, ManualClock(), failure_threshold=3)

        for _ in range(3):
            with pytest.raises(ProviderError):
                await gateway.generate(a_request(), CONTEXT)

        assert provider.calls == 3

        with pytest.raises(ProviderError, match="temporarily unavailable"):
            await gateway.generate(a_request(), CONTEXT)

        # The provider was not called a fourth time.
        assert provider.calls == 3

    async def test_calls_resume_after_the_reset_timeout(self) -> None:
        clock = ManualClock()
        provider = ScriptedProvider(failures=2)
        gateway = build_gateway(provider, clock, failure_threshold=2, reset_timeout_seconds=30)

        for _ in range(2):
            with pytest.raises(ProviderError):
                await gateway.generate(a_request(), CONTEXT)

        clock.advance(30)
        response = await gateway.generate(a_request(), CONTEXT)

        assert response.message.content == "ok"
        assert await gateway.circuit_states() == {"test-provider": "closed"}

    async def test_a_validation_failure_does_not_open_the_breaker(self) -> None:
        """The caller's mistake must not cut off a healthy provider."""
        provider = ScriptedProvider(
            failures=100,
            error=ValidationError("bad request"),
        )
        gateway = build_gateway(provider, ManualClock(), failure_threshold=2)

        for _ in range(4):
            with pytest.raises(ValidationError):
                await gateway.generate(a_request(), CONTEXT)

        # Every call reached the provider; the breaker never opened.
        assert provider.calls == 4
        assert await gateway.circuit_states() == {"test-provider": "closed"}

    async def test_breaker_state_is_reportable(self) -> None:
        """An operator should see that a provider is being skipped."""
        provider = ScriptedProvider(failures=100)
        gateway = build_gateway(provider, ManualClock(), failure_threshold=1)

        with pytest.raises(ProviderError):
            await gateway.generate(a_request(), CONTEXT)

        assert await gateway.circuit_states() == {"test-provider": "open"}

    async def test_nothing_is_reported_before_a_provider_is_used(self) -> None:
        """Reporting CLOSED for an unexercised provider would claim knowledge."""
        gateway = build_gateway(ScriptedProvider(failures=0), ManualClock())

        assert await gateway.circuit_states() == {}

    async def test_a_successful_call_keeps_the_breaker_closed(self) -> None:
        provider = ScriptedProvider(failures=0)
        gateway = build_gateway(provider, ManualClock(), failure_threshold=2)

        for _ in range(5):
            await gateway.generate(a_request(), CONTEXT)

        assert await gateway.circuit_states() == {"test-provider": "closed"}
        assert provider.calls == 5


class TestRetryInteraction:
    async def test_the_breaker_stops_retries_mid_sequence(self) -> None:
        """A breaker that opens partway through must stop the remaining attempts.

        Continuing to retry an upstream that has just been declared unhealthy is
        precisely what this exists to prevent.
        """
        clock = ManualClock()
        provider = ScriptedProvider(failures=100)
        gateway = DefaultLLMGateway(
            resolver=StaticResolver(provider),
            clock=clock,
            retry_policy=RetryPolicy(max_attempts=5, initial_backoff_seconds=0.001),
            timeout_policy=TimeoutPolicy(),
            circuit_breaker_policy=CircuitBreakerPolicy(failure_threshold=2),
        )

        with pytest.raises(ProviderError):
            await gateway.generate(a_request(), CONTEXT)

        # Two attempts opened the breaker; attempts three to five never ran.
        assert provider.calls == 2


class TestTheDoubleIsHonest:
    def test_the_scripted_provider_satisfies_the_contract(self) -> None:
        """A double narrower than the protocol tests the double, not the code."""
        assert isinstance(ScriptedProvider(failures=0), LLMProvider)
