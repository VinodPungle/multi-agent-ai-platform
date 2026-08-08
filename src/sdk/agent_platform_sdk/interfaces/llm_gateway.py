"""LLM Gateway contract.

The single entry point through which the platform reaches *any* model
(``architecture.md`` §30). The Agent Runtime, workflows, agents and evaluation
depend on this interface and never on
:class:`~agent_platform_sdk.interfaces.llm_provider.LLMProvider` — that
indirection is what keeps provider concerns out of business logic.

Why a gateway sits between the runtime and the provider
    Retry, timeout, telemetry and cost estimation are identical for every
    provider. Implemented in the provider they would be written once per vendor
    and drift immediately; implemented in the runtime they would entangle
    orchestration with transport. The gateway is the one place they belong, so a
    provider stays a thin translation layer.

    ==============================  ==============================
    Gateway                         Provider
    ==============================  ==============================
    Request normalisation           Wire-format translation
    Response normalisation          Transport and authentication
    Provider selection              Vendor error mapping
    Retry and timeout policy        Tokenisation
    Telemetry and cost estimation   Nothing else
    ==============================  ==============================

The gateway is deliberately *not* a :class:`~agent_platform_sdk.interfaces.provider.Provider`.
It is a platform component with no external dependency of its own; its health is
the health of the providers behind it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Protocol, runtime_checkable

from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.dto.completion import (
    CompletionChunk,
    CompletionRequest,
    CompletionResponse,
    TokenUsage,
)

__all__ = ["LLMGateway"]


@runtime_checkable
class LLMGateway(Protocol):
    """Provider-independent access to model inference.

    Implementations resolve a provider per call, apply the configured policies,
    and return provider-neutral types. Callers never learn which provider served
    a request except as data on the response.
    """

    async def generate(
        self,
        request: CompletionRequest,
        context: ExecutionContext,
    ) -> CompletionResponse:
        """Produce a complete response, applying retry and timeout policy.

        Args:
            request: A provider-neutral completion request.
            context: Identity and routing metadata for the call. The
                implementation stamps the resolved provider and model onto the
                context it passes downstream, so telemetry records what actually
                served the request rather than what was asked for.

        Returns:
            A normalised response. ``latency_ms`` and ``estimated_cost`` are
            populated by the gateway when the provider does not report them, so
            callers can rely on them being present for every provider.

        Raises:
            NotFoundError: no provider could be resolved for the request.
            ValidationError: the request is not valid against the contract.
            PlatformTimeoutError: the call exceeded its configured budget.
            ProviderError: the provider failed and retries were exhausted or the
                failure was not retryable.
        """
        ...

    def stream(
        self,
        request: CompletionRequest,
        context: ExecutionContext,
    ) -> AsyncIterator[CompletionChunk]:
        """Produce a response incrementally.

        Declared as a regular method returning an ``AsyncIterator`` rather than
        as an ``async def``, matching
        :meth:`~agent_platform_sdk.interfaces.llm_provider.LLMProvider.stream`,
        so an implementation may be an async generator or an explicit iterator.

        Retry policy does **not** apply: once a chunk has been handed to the
        caller the call is no longer idempotent, and a silent re-attempt would
        emit the beginning of the answer twice.

        Callers must consume or close the iterator; abandoning it leaks the
        underlying provider connection.
        """
        ...

    async def count_tokens(
        self,
        request: CompletionRequest,
        context: ExecutionContext,
    ) -> TokenUsage:
        """Estimate prompt tokens for ``request`` without dispatching it.

        Used for budget enforcement and to reject a prompt that exceeds the
        model's context window before spending a call on it.
        """
        ...

    async def estimate_cost(
        self,
        model_id: str,
        usage: TokenUsage,
        context: ExecutionContext,
    ) -> Decimal:
        """Return the estimated cost of ``usage`` for ``model_id``.

        ``Decimal`` rather than ``float``: summing float costs across millions of
        calls accumulates error, and this number ends up on an invoice
        reconciliation.
        """
        ...
