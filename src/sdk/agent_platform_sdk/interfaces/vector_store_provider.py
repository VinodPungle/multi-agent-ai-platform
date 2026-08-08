"""Vector store contract.

Not required initially (``architecture.md`` §39) — interface only. Future
implementations include Azure AI Search, pgvector, Qdrant, Milvus and Chroma.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.interfaces.provider import Provider

__all__ = ["VectorRecord", "VectorStoreProvider"]


class VectorRecord:
    """A stored vector with its identifier and metadata.

    A plain class rather than a Pydantic model: vectors are written in large
    batches on hot paths, and per-record validation of a several-thousand-element
    float sequence is measurable overhead for no benefit — the embedding provider
    already guarantees the shape.
    """

    __slots__ = ("metadata", "record_id", "vector")

    def __init__(
        self,
        record_id: str,
        vector: tuple[float, ...],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.record_id = record_id
        self.vector = vector
        self.metadata = metadata or {}


@runtime_checkable
class VectorStoreProvider(Provider, Protocol):
    """Persistence and similarity search over embeddings."""

    async def upsert(
        self,
        collection: str,
        records: tuple[VectorRecord, ...],
        context: ExecutionContext,
    ) -> None:
        """Insert or replace ``records`` in ``collection``."""
        ...

    async def query(
        self,
        collection: str,
        vector: tuple[float, ...],
        limit: int,
        context: ExecutionContext,
    ) -> tuple[tuple[VectorRecord, float], ...]:
        """Return the nearest records to ``vector`` with their similarity scores.

        Ordered most similar first. Score semantics are provider-specific, so
        callers must compare scores only within a single provider's results.
        """
        ...

    async def delete(
        self,
        collection: str,
        record_ids: tuple[str, ...],
        context: ExecutionContext,
    ) -> None:
        """Remove records by id. Unknown ids are ignored."""
        ...
