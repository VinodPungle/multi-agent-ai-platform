"""Getting documents into the index.

Chunk, embed, upsert. The interesting decisions are about repeatability and
failure, because an ingestion pipeline that is not safe to re-run is one nobody
dares re-run, and a corpus half-indexed is worse than one not indexed at all —
it answers, incompletely, without saying so.

Record ids are derived, not generated
    ``<document_id>#<chunk_index>``. Re-indexing a changed document overwrites
    its passages instead of adding near-duplicates that then compete with the
    originals in every search. The one case this does not cover is a document
    that gets *shorter*: chunks beyond the new length would survive as orphans,
    so they are deleted explicitly.

Embedding failures stop the run
    A batch that fails leaves the document unindexed rather than partially
    indexed. Partial ingestion is the failure that is hard to notice: retrieval
    keeps working and quietly cannot see half the corpus.
"""

from __future__ import annotations

from agent_platform.knowledge.chunking import chunk_document
from agent_platform.telemetry.logging import get_logger
from agent_platform.telemetry.tracing import get_tracer
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.dto.knowledge import KnowledgeDocument
from agent_platform_sdk.interfaces.embedding_provider import EmbeddingProvider
from agent_platform_sdk.interfaces.vector_store_provider import (
    VectorRecord,
    VectorStoreProvider,
)

__all__ = ["KnowledgeIndexer"]

_logger = get_logger(__name__)
_tracer = get_tracer(__name__)

#: Chunk ids beyond a document's current length that are cleaned up on re-index.
#:
#: A document could in principle shrink by any amount, and querying the store
#: for "everything belonging to this document" is not on the interface — a
#: hosted index does that by filter, which is a different operation with
#: different permissions. Deleting a fixed window past the end covers every
#: realistic edit; a document that loses more than this many chunks at once is a
#: replacement, and re-creating the collection is the honest answer.
_ORPHAN_CLEANUP_WINDOW = 64


class KnowledgeIndexer:
    """Turns documents into searchable passages."""

    def __init__(
        self,
        embeddings: EmbeddingProvider,
        vectors: VectorStoreProvider,
        collection: str = "knowledge",
        max_chunk_characters: int = 1_200,
        chunk_overlap_characters: int = 150,
        embedding_batch_size: int = 32,
    ) -> None:
        """Create the indexer.

        Args:
            embeddings: Turns text into vectors. The interface, never a model.
            vectors: Where they are stored. The interface, never a database.
            collection: Index name. One per corpus, so a corpus can be dropped
                without touching another.
            max_chunk_characters: Largest passage to produce.
            chunk_overlap_characters: Overlap between adjacent passages.
            embedding_batch_size: Texts per embedding request. Batched because
                per-item calls dominate cost and latency; bounded because a
                deployment rejects an over-large request, and finding that out
                halfway through a corpus is expensive.
        """
        self._embeddings = embeddings
        self._vectors = vectors
        self._collection = collection
        self._max_chunk_characters = max_chunk_characters
        self._chunk_overlap_characters = chunk_overlap_characters
        self._batch_size = embedding_batch_size

    @property
    def collection(self) -> str:
        """Collection this indexer writes to."""
        return self._collection

    async def index(
        self,
        documents: tuple[KnowledgeDocument, ...],
        context: ExecutionContext,
    ) -> int:
        """Index ``documents`` and return how many passages were written.

        Raises:
            ProviderError: embedding failed. Nothing is written for the document
                that failed, deliberately — see the module docstring.
        """
        written = 0
        for document in documents:
            written += await self._index_one(document, context)

        _logger.info(
            "knowledge.indexed",
            collection=self._collection,
            documents=len(documents),
            passages=written,
            **context.to_log_fields(),
        )
        return written

    async def _index_one(self, document: KnowledgeDocument, context: ExecutionContext) -> int:
        """Index one document, replacing whatever it had before."""
        with _tracer.start_as_current_span("knowledge.index_document") as span:
            span.set_attribute("knowledge.collection", self._collection)
            span.set_attribute("knowledge.document_id", document.document_id)

            chunks = chunk_document(
                document,
                max_characters=self._max_chunk_characters,
                overlap_characters=self._chunk_overlap_characters,
            )
            span.set_attribute("knowledge.chunk_count", len(chunks))

            if not chunks:
                return 0

            records: list[VectorRecord] = []
            for start in range(0, len(chunks), self._batch_size):
                batch = chunks[start : start + self._batch_size]
                vectors = await self._embeddings.embed(
                    tuple(chunk.content for chunk in batch),
                    context,
                )
                # `strict=True`: a provider returning a different number of
                # vectors than texts would otherwise silently pair passages with
                # the wrong embeddings, which produces confident nonsense rather
                # than an error.
                records.extend(
                    VectorRecord(
                        record_id=_record_id(document.document_id, chunk.index),
                        vector=vector,
                        metadata={
                            "document_id": document.document_id,
                            "title": document.title,
                            "source": document.source,
                            "content": chunk.content,
                            "chunk_index": chunk.index,
                        },
                    )
                    for chunk, vector in zip(batch, vectors, strict=True)
                )

            await self._vectors.upsert(self._collection, tuple(records), context)
            await self._delete_orphans(document.document_id, len(chunks), context)

            return len(records)

    async def _delete_orphans(
        self,
        document_id: str,
        chunk_count: int,
        context: ExecutionContext,
    ) -> None:
        """Remove passages left behind when a document gets shorter.

        Without this, editing a document down leaves its old tail in the index —
        passages that no longer exist in the source, still being returned as
        though they did. Unknown ids are ignored by the contract, so deleting a
        window past the end is cheap and safe.
        """
        stale = tuple(
            _record_id(document_id, index)
            for index in range(chunk_count, chunk_count + _ORPHAN_CLEANUP_WINDOW)
        )
        await self._vectors.delete(self._collection, stale, context)


def _record_id(document_id: str, chunk_index: int) -> str:
    """Derive a stable id, so re-indexing replaces rather than duplicates."""
    return f"{document_id}#{chunk_index}"
