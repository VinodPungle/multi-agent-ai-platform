"""The default LLM Gateway implementation.

Provider independent by construction: the only model-facing type it names is the
:class:`~agent_platform_sdk.interfaces.llm_provider.LLMProvider` protocol, and
the only way it obtains one is through the injected resolver. Adding an
OpenAI-compatible provider therefore changes nothing in this file.

What "normalisation" means here, concretely:

**Request**
    Validate against the contract before a call is spent, and stamp the resolved
    provider and model onto the context handed downstream. Defaulting unset
    parameters from the model registry joins this step in Milestone 03 — the
    registry does not exist yet, and inventing defaults without it would hide
    which value actually reached the provider.

**Response**
    Guarantee that ``latency_ms`` and ``estimated_cost`` are populated for every
    provider, whether or not that provider reports them. Without this the
    evaluation and cost pipelines would need a per-provider special case, which
    is exactly the coupling the gateway exists to prevent.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from decimal import Decimal
from secrets import SystemRandom

from agent_platform.exceptions.base import (
    PlatformError,
    PlatformTimeoutError,
    ProviderError,
    ValidationError,
)
from agent_platform.telemetry.logging import get_logger
from agent_platform.telemetry.tracing import get_tracer
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.dto.completion import (
    CompletionChunk,
    CompletionRequest,
    CompletionResponse,
    TokenUsage,
)
from agent_platform_sdk.interfaces.llm_provider import LLMProvider
from agent_platform_sdk.interfaces.llm_provider_resolver import LLMProviderResolver
from agent_platform_sdk.policies.retry import RetryPolicy
from agent_platform_sdk.policies.timeout import TimeoutPolicy
from agent_platform_shared.clock import Clock

__all__ = ["DefaultLLMGateway"]

_logger = get_logger(__name__)
_tracer = get_tracer(__name__)

#: Jitter source. ``SystemRandom`` rather than the module-level ``random``
#: functions: it needs no seeding, is not affected by anything else in the
#: process seeding the global generator, and costs nothing at this call volume.
_random = SystemRandom()


class DefaultLLMGateway:
    """Applies platform policy around a resolved provider.

    Satisfies :class:`~agent_platform_sdk.interfaces.llm_gateway.LLMGateway`
    structurally. Stateless and safe to share across requests — per-call state
    lives in the :class:`ExecutionContext`, never on the instance.
    """

    def __init__(
        self,
        resolver: LLMProviderResolver,
        clock: Clock,
        retry_policy: RetryPolicy,
        timeout_policy: TimeoutPolicy,
    ) -> None:
        """Create the gateway.

        Args:
            resolver: Port that answers which provider serves a model.
            clock: Injected time source. Latency is measured from its monotonic
                counter, never from wall-clock time, which can step backwards.
            retry_policy: Attempts and backoff for non-streaming calls.
            timeout_policy: Per-call budgets. Required rather than defaulted, so
                that a deployment cannot silently inherit a timeout nobody chose.
        """
        self._resolver = resolver
        self._clock = clock
        self._retry_policy = retry_policy
        self._timeout_policy = timeout_policy

    # -- Inference ---------------------------------------------------------

    async def generate(
        self,
        request: CompletionRequest,
        context: ExecutionContext,
    ) -> CompletionResponse:
        """Produce a complete response, applying retry and timeout policy."""
        self._validate(request)
        provider = await self._resolver.resolve(request.model_id, context)
        call_context = context.derive(
            provider_id=provider.provider_id,
            model_id=request.model_id,
        )

        with _tracer.start_as_current_span("llm.generate") as span:
            span.set_attribute("llm.provider_id", provider.provider_id)
            span.set_attribute("llm.model_id", request.model_id)
            span.set_attribute("llm.streaming", False)

            started = self._clock.monotonic()
            response = await self._generate_with_retry(provider, request, call_context)
            elapsed_ms = (self._clock.monotonic() - started) * 1000

            normalised = self._normalise_response(response, provider, elapsed_ms)

            span.set_attribute("llm.usage.prompt_tokens", normalised.usage.prompt_tokens)
            span.set_attribute("llm.usage.completion_tokens", normalised.usage.completion_tokens)
            span.set_attribute("llm.latency_ms", elapsed_ms)
            if normalised.estimated_cost is not None:
                span.set_attribute("llm.estimated_cost", str(normalised.estimated_cost))

            _logger.info(
                "llm.call_completed",
                streaming=False,
                prompt_tokens=normalised.usage.prompt_tokens,
                completion_tokens=normalised.usage.completion_tokens,
                latency_ms=round(elapsed_ms, 2),
                estimated_cost=(
                    str(normalised.estimated_cost)
                    if normalised.estimated_cost is not None
                    else None
                ),
                finish_reason=normalised.finish_reason,
                **call_context.to_log_fields(),
            )
            return normalised

    async def stream(
        self,
        request: CompletionRequest,
        context: ExecutionContext,
    ) -> AsyncGenerator[CompletionChunk, None]:
        """Produce a response incrementally.

        Returns the narrower ``AsyncGenerator`` rather than the ``AsyncIterator``
        the protocol declares — a permitted narrowing that gives callers holding
        the concrete type an ``aclose()`` to release the provider connection
        early. Callers holding the protocol keep the smaller contract.

        Deliberately *not* retried. Once the first chunk has reached the caller
        the call is no longer idempotent, and re-attempting would emit the start
        of the answer twice.

        Only the first chunk carries a timeout. It detects the failure mode a
        total-duration limit catches far too late — a provider that accepted the
        connection and never began generating. Policing total duration here would
        instead measure how fast the *consumer* reads, which is not a provider
        fault; that budget belongs to the runtime's request deadline.
        """
        self._validate(request)
        provider = await self._resolver.resolve(request.model_id, context)
        call_context = context.derive(
            provider_id=provider.provider_id,
            model_id=request.model_id,
        )

        with _tracer.start_as_current_span("llm.stream") as span:
            span.set_attribute("llm.provider_id", provider.provider_id)
            span.set_attribute("llm.model_id", request.model_id)
            span.set_attribute("llm.streaming", True)

            started = self._clock.monotonic()
            iterator = provider.stream(request, call_context).__aiter__()
            chunk_count = 0

            try:
                try:
                    async with asyncio.timeout(self._timeout_policy.first_token_seconds):
                        first_chunk = await anext(iterator)
                except StopAsyncIteration:
                    # An empty stream is a provider result, not an error. The
                    # caller sees no chunks; the log line records that it happened.
                    _logger.warning(
                        "llm.stream_empty",
                        **call_context.to_log_fields(),
                    )
                    return
                except Exception as error:
                    failure, _ = self._classify(error, provider.provider_id)
                    self._log_failure(failure, attempt=1, streaming=True, context=call_context)
                    raise failure from error

                time_to_first_token_ms = (self._clock.monotonic() - started) * 1000
                span.set_attribute("llm.time_to_first_token_ms", time_to_first_token_ms)

                chunk_count += 1
                yield first_chunk

                async for chunk in iterator:
                    chunk_count += 1
                    yield chunk
            finally:
                await self._close(iterator)

            elapsed_ms = (self._clock.monotonic() - started) * 1000
            span.set_attribute("llm.chunk_count", chunk_count)
            span.set_attribute("llm.latency_ms", elapsed_ms)
            _logger.info(
                "llm.call_completed",
                streaming=True,
                chunk_count=chunk_count,
                time_to_first_token_ms=round(time_to_first_token_ms, 2),
                latency_ms=round(elapsed_ms, 2),
                **call_context.to_log_fields(),
            )

    # -- Accounting --------------------------------------------------------

    async def count_tokens(
        self,
        request: CompletionRequest,
        context: ExecutionContext,
    ) -> TokenUsage:
        """Estimate prompt tokens for ``request`` without dispatching it.

        Not retried and not timed out: tokenisation is local computation, so a
        failure is deterministic and a second attempt would fail identically.
        """
        self._validate(request)
        provider = await self._resolver.resolve(request.model_id, context)
        return await provider.count_tokens(request)

    async def estimate_cost(
        self,
        model_id: str,
        usage: TokenUsage,
        context: ExecutionContext,
    ) -> Decimal:
        """Return the estimated cost of ``usage`` for ``model_id``."""
        provider = await self._resolver.resolve(model_id, context)
        return provider.estimate_cost(model_id, usage)

    # -- Normalisation -----------------------------------------------------

    def _validate(self, request: CompletionRequest) -> None:
        """Reject a request that no provider could serve.

        Structural checks only — the ones that are true of every provider. A
        limit that varies by model (context window, output cap) is checked
        against the model registry from Milestone 03, not here.

        Raises:
            ValidationError: the request cannot be dispatched as written.
        """
        if not request.model_id.strip():
            message = "A completion request must name a model."
            raise ValidationError(message)

        if not request.messages and not request.system_prompt:
            message = (
                "A completion request must carry at least one message or a system prompt. "
                "An empty request would spend a call to produce nothing."
            )
            raise ValidationError(message, details={"model_id": request.model_id})

    def _normalise_response(
        self,
        response: CompletionResponse,
        provider: LLMProvider,
        elapsed_ms: float,
    ) -> CompletionResponse:
        """Fill in what the provider did not report.

        Every response leaving the gateway carries a latency and — when tokens
        were used — a cost, so downstream evaluation never has to ask which
        provider produced it.
        """
        updates: dict[str, object] = {}

        if response.latency_ms is None:
            updates["latency_ms"] = elapsed_ms

        if response.estimated_cost is None and response.usage.total_tokens > 0:
            updates["estimated_cost"] = provider.estimate_cost(response.model_id, response.usage)

        return response.model_copy(update=updates) if updates else response

    # -- Policy ------------------------------------------------------------

    async def _generate_with_retry(
        self,
        provider: LLMProvider,
        request: CompletionRequest,
        context: ExecutionContext,
    ) -> CompletionResponse:
        """Call ``provider.generate`` under the retry and timeout policies."""
        attempt = 0
        while True:
            attempt += 1
            try:
                async with asyncio.timeout(self._timeout_policy.model_call_seconds):
                    return await provider.generate(request, context)
            except Exception as error:
                failure, retryable = self._classify(error, provider.provider_id)

                if not retryable or attempt >= self._retry_policy.max_attempts:
                    self._log_failure(failure, attempt=attempt, streaming=False, context=context)
                    raise failure from error

                delay_seconds = self._backoff_delay(attempt)
                _logger.warning(
                    "llm.retry",
                    attempt=attempt,
                    max_attempts=self._retry_policy.max_attempts,
                    delay_seconds=round(delay_seconds, 3),
                    error_category=failure.category.value,
                    error_type=type(error).__name__,
                    **context.to_log_fields(),
                )
                await asyncio.sleep(delay_seconds)

    def _classify(self, error: Exception, provider_id: str) -> tuple[PlatformError, bool]:
        """Map a raised exception onto a platform error and a retry decision.

        Three cases, and the third is the interesting one:

        ``TimeoutError``
            The budget expired. Transient by definition, so the policy decides.
        :class:`PlatformError`
            The provider mapped its own failure, as the contract requires. Its
            category drives the decision.
        Anything else
            A contract violation — the provider let a raw exception escape.
            Never retried: the platform has no basis for calling it transient,
            and repeating a programming error three times only delays the report.
        """
        if isinstance(error, TimeoutError) and not isinstance(error, PlatformError):
            failure = PlatformTimeoutError(
                f"Model call exceeded {self._timeout_policy.model_call_seconds}s.",
                details={
                    "provider_id": provider_id,
                    "timeout_seconds": self._timeout_policy.model_call_seconds,
                },
            )
            return failure, self._retry_policy.is_retryable(failure.category)

        if isinstance(error, PlatformError):
            return error, self._retry_policy.is_retryable(error.category)

        # The exception message is deliberately dropped: it may carry an
        # endpoint, a header or a credential fragment, and this string is
        # returned over HTTP. The type name is enough to identify the fault.
        wrapped = ProviderError(
            f"Provider raised an unhandled {type(error).__name__}.",
            provider_id=provider_id,
            details={"error_type": type(error).__name__},
        )
        return wrapped, False

    def _backoff_delay(self, attempt: int) -> float:
        """Return the delay before ``attempt`` + 1.

        Exponential growth capped by the policy, then *full* jitter — a delay
        drawn from the whole interval rather than a narrow band around it.
        Replicas that fail together otherwise retry together and re-create the
        load spike that caused the failure.
        """
        policy = self._retry_policy
        delay = policy.initial_backoff_seconds * (policy.backoff_multiplier ** (attempt - 1))
        delay = min(delay, policy.max_backoff_seconds)
        return _random.uniform(0.0, delay) if policy.jitter else delay

    def _log_failure(
        self,
        failure: PlatformError,
        *,
        attempt: int,
        streaming: bool,
        context: ExecutionContext,
    ) -> None:
        """Record a terminal call failure.

        Logs ``failure.message`` rather than the original exception text: the
        message is the client-safe summary, and the raw provider string is the
        one place a credential fragment is likely to appear.
        """
        _logger.error(
            "llm.call_failed",
            streaming=streaming,
            attempts=attempt,
            error_category=failure.category.value,
            error_type=type(failure).__name__,
            error_message=failure.message,
            **context.to_log_fields(),
        )

    @staticmethod
    async def _close(iterator: AsyncIterator[CompletionChunk]) -> None:
        """Close a provider stream that was abandoned before exhaustion.

        The provider contract makes closing the caller's responsibility, and the
        gateway is the caller. Skipping this leaks the underlying HTTP
        connection whenever a consumer stops reading early — a client
        disconnecting mid-response, which is routine rather than exceptional.

        ``AsyncIterator`` does not require ``aclose``; async generators, which
        every provider will realistically return, provide it.
        """
        close = getattr(iterator, "aclose", None)
        if close is not None:
            await close()
