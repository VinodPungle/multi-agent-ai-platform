"""An in-process vector index.

The platform's first vector store, and the same shape of first implementation as
`InMemorySessionMemoryProvider`: complete, correct, and honest about not being
durable. It makes the whole RAG pipeline real on a laptop with nothing
provisioned, which is what ``CLAUDE.md`` asks for — *"Always implement locally
before Azure deployment"*.

Brute-force cosine similarity
    Every query scores every vector in the collection. That is O(n) and it is
    the right algorithm here: an approximate index (HNSW, IVF) earns its
    complexity in the hundreds of thousands of vectors, and below that it is
    slower to build, harder to reason about, and *approximate* — it can miss the
    best match. For a corpus that fits in a process, exact search is both
    simpler and better.

    The scale where that reverses is where Azure AI Search replaces this, behind
    the same interface, and no calling code changes.

Vectors are normalised once, on write
    Cosine similarity is a dot product between unit vectors. Normalising at
    write time turns every query into a multiply-and-sum instead of two norms
    plus a division per candidate — the difference is the whole inner loop, and
    a write happens once while a query happens constantly.
"""

from __future__ import annotations

import math
from threading import RLock

from agent_platform.telemetry.logging import get_logger
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.contracts.health import ComponentHealth
from agent_platform_sdk.interfaces.vector_store_provider import VectorRecord
from agent_platform_sdk.types.enums import Capability, HealthStatus

__all__ = ["InMemoryVectorStore"]

_logger = get_logger(__name__)


class InMemoryVectorStore:
    """Brute-force cosine similarity over vectors held in the process.

    Satisfies
    :class:`~agent_platform_sdk.interfaces.vector_store_provider.VectorStoreProvider`
    structurally — it inherits nothing, per ADR-0004.
    """

    def __init__(
        self,
        provider_id: str = "in-memory-vectors",
        max_records_per_collection: int = 50_000,
    ) -> None:
        """Create the store.

        Args:
            provider_id: Identifier it registers under.
            max_records_per_collection: Hard cap. Mandatory rather than tuning:
                an unbounded index fed by an ingestion endpoint is a way to
                exhaust the process's memory, and this store shares that memory
                with everything else in it.
        """
        self._provider_id = provider_id
        self._max_records = max_records_per_collection
        # record_id -> (unit vector, record). A dict per collection, so an
        # upsert replaces by id rather than appending a second copy.
        self._collections: dict[str, dict[str, tuple[tuple[float, ...], VectorRecord]]] = {}
        # Ingestion can run from a background task while requests query. A
        # plain lock rather than an async one: every operation here is CPU-bound
        # and short, so there is nothing to await and no risk of holding it
        # across a suspension point.
        self._lock = RLock()

    @property
    def provider_id(self) -> str:
        """Identifier this provider is registered under."""
        return self._provider_id

    # -- Lifecycle ---------------------------------------------------------

    async def initialize(self) -> None:
        """Nothing to open."""
        _logger.info(
            "vector_store.initialized",
            provider_id=self._provider_id,
            max_records=self._max_records,
            detail="In-process vector index. Not durable, not shared between replicas.",
        )

    async def close(self) -> None:
        """Release the index."""
        with self._lock:
            self._collections.clear()

    def supports(self, capability: Capability) -> bool:
        """Declare nothing. Storage is not a model capability."""
        del capability
        return False

    async def health_check(self) -> ComponentHealth:
        """Report what is indexed.

        Healthy when empty, unlike the prompt provider. An empty index is a
        legitimate state — nothing has been ingested yet — whereas a platform
        with no prompts cannot answer at all.
        """
        with self._lock:
            collections = len(self._collections)
            records = sum(len(entries) for entries in self._collections.values())

        return ComponentHealth(
            name=self._provider_id,
            status=HealthStatus.HEALTHY,
            detail=f"{records} vector(s) across {collections} collection(s). In-process.",
        )

    # -- Vector store ------------------------------------------------------

    async def upsert(
        self,
        collection: str,
        records: tuple[VectorRecord, ...],
        context: ExecutionContext,
    ) -> None:
        """Insert or replace ``records``.

        Replacement is by ``record_id``, which is what makes re-ingesting a
        changed document safe: the old passages are overwritten rather than
        joined by near-duplicates that then compete in every search.
        """
        del context
        if not records:
            return

        with self._lock:
            entries = self._collections.setdefault(collection, {})
            for record in records:
                entries[record.record_id] = (_normalise(record.vector), record)

            if len(entries) > self._max_records:
                # Oldest-first, by insertion order. Crude, and stated as such:
                # a real store evicts by policy. The cap exists to bound memory,
                # not to be a retention strategy.
                excess = len(entries) - self._max_records
                for record_id in list(entries)[:excess]:
                    del entries[record_id]
                _logger.warning(
                    "vector_store.capacity_reached",
                    provider_id=self._provider_id,
                    collection=collection,
                    dropped=excess,
                    detail="Oldest vectors were dropped. Move to a durable store.",
                )

    async def query(
        self,
        collection: str,
        vector: tuple[float, ...],
        limit: int,
        context: ExecutionContext,
    ) -> tuple[tuple[VectorRecord, float], ...]:
        """Return the nearest records, most similar first."""
        del context
        if limit <= 0:
            return ()

        query_vector = _normalise(vector)

        with self._lock:
            entries = self._collections.get(collection)
            if not entries:
                return ()
            # Copied under the lock, scored outside it: scoring is the expensive
            # part, and holding a lock across it would serialise every query.
            candidates = list(entries.values())

        scored = [
            (record, _dot(query_vector, stored))
            for stored, record in candidates
            if len(stored) == len(query_vector)
        ]
        scored.sort(key=lambda pair: (-pair[1], pair[0].record_id))
        return tuple(scored[:limit])

    async def delete(
        self,
        collection: str,
        record_ids: tuple[str, ...],
        context: ExecutionContext,
    ) -> None:
        """Remove records by id. Unknown ids are ignored."""
        del context
        with self._lock:
            entries = self._collections.get(collection)
            if entries is None:
                return
            for record_id in record_ids:
                entries.pop(record_id, None)

    # -- Beyond the interface ----------------------------------------------

    async def delete_collection(self, collection: str) -> None:
        """Drop a whole collection.

        Not on ``VectorStoreProvider``: a hosted index deletes by filter or by
        dropping an index resource, which is a different operation with
        different permissions. Kept off the interface until a second
        implementation shows what it should actually look like — inventing the
        signature from one example is how an interface ends up shaped like its
        first implementation.
        """
        with self._lock:
            self._collections.pop(collection, None)

    def count(self, collection: str) -> int:
        """Return how many vectors a collection holds. For tests and health."""
        with self._lock:
            return len(self._collections.get(collection, {}))

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        with self._lock:
            return f"InMemoryVectorStore(collections={len(self._collections)})"


def _normalise(vector: tuple[float, ...]) -> tuple[float, ...]:
    """Scale a vector to unit length.

    A zero vector is returned unchanged rather than raising: it scores zero
    against everything, which is the correct answer for text that carried no
    signal, and refusing to index it would fail an ingestion run over one empty
    passage.
    """
    magnitude = math.sqrt(sum(component * component for component in vector))
    if magnitude == 0.0:
        return vector
    return tuple(component / magnitude for component in vector)


def _dot(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    """Dot product of two unit vectors, which is their cosine similarity."""
    return sum(a * b for a, b in zip(left, right, strict=True))
