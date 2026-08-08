"""LLM provider contract.

The single most important abstraction in the platform. Every model — Azure AI
Foundry, Azure OpenAI, Anthropic, Gemini, DeepSeek, Ollama, vLLM — reaches the
runtime through this interface, which is what makes the provider replaceable by
configuration alone.

Implementations live in ``agent_platform.providers`` and are the only place a
vendor SDK may be imported.
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
from agent_platform_sdk.dto.model import ModelDescriptor
from agent_platform_sdk.interfaces.provider import Provider

__all__ = ["LLMProvider"]


@runtime_checkable
class LLMProvider(Provider, Protocol):
    """Inference operations, expressed in provider-neutral types.

    Every method takes an :class:`ExecutionContext` so that provider calls are
    attributable in logs and traces without the provider reaching for ambient
    state.
    """

    async def generate(
        self,
        request: CompletionRequest,
        context: ExecutionContext,
    ) -> CompletionResponse:
        """Produce a complete response in one call.

        Implementations translate ``request`` into the vendor's wire format and
        translate the reply back into a :class:`CompletionResponse`. Vendor
        types must not escape the provider package.

        Raises:
            ProviderError: on any failure originating from the provider.
        """
        ...

    def stream(
        self,
        request: CompletionRequest,
        context: ExecutionContext,
    ) -> AsyncIterator[CompletionChunk]:
        """Produce a response incrementally.

        Declared as a regular method returning an ``AsyncIterator`` rather than
        as an ``async def``, so implementations are free to use either an async
        generator or an explicit iterator class.

        Only valid when the provider declares :attr:`Capability.STREAMING`.
        Callers must consume or close the iterator; abandoning it leaks the
        underlying HTTP connection.
        """
        ...

    async def count_tokens(self, request: CompletionRequest) -> TokenUsage:
        """Estimate prompt tokens before dispatching a request.

        Used for budget enforcement and to fail fast when a prompt exceeds the
        model's context window. Providers without a tokeniser should return a
        documented approximation rather than raising.
        """
        ...

    def estimate_cost(self, model_id: str, usage: TokenUsage) -> Decimal:
        """Return the estimated cost of ``usage`` for ``model_id``.

        Computed from registry pricing, so cost tracking works identically for
        providers that report spend and those that do not.
        """
        ...

    async def list_models(self) -> tuple[ModelDescriptor, ...]:
        """Return the models this provider can currently serve."""
        ...
