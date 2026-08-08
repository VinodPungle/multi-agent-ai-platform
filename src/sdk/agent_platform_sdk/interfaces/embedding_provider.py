"""Embedding provider contract.

Not required for the MVP (``architecture.md`` §38). The interface exists now so
that adding Azure OpenAI, Cohere or Sentence Transformers later is an additive
change rather than a refactor of everything that will consume embeddings.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.interfaces.provider import Provider

__all__ = ["EmbeddingProvider"]


@runtime_checkable
class EmbeddingProvider(Provider, Protocol):
    """Conversion of text into dense vectors."""

    @property
    def dimensions(self) -> int:
        """Length of the vectors this provider emits.

        Exposed because a vector store's index is fixed to one dimensionality;
        the runtime must reject a mismatched pairing at startup rather than on
        the first write.
        """
        ...

    async def embed(
        self,
        texts: tuple[str, ...],
        context: ExecutionContext,
    ) -> tuple[tuple[float, ...], ...]:
        """Embed ``texts``, returning one vector per input in the same order.

        Batch-first because per-item calls dominate cost and latency at scale.
        Embedding a single string means passing a one-element tuple.
        """
        ...
