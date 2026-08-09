"""Finding the passages that answer a question.

Embed the query with the same provider that embedded the corpus, search, return
passages. Short, because the difficult parts are elsewhere — chunking decided
what *can* be retrieved, and the tool decides what reaches the model.

The score threshold is the decision that matters
    A vector search always returns its `limit` nearest neighbours. On a corpus
    that has nothing to say about the question, the nearest neighbours are still
    returned, and they look exactly like an answer. Passing those to a model
    invites it to ground a confident reply in text that happens to be least
    unlike the question.

    A minimum score turns "nothing relevant" into an empty result, which the
    tool reports honestly and the model can act on. The threshold is
    configuration, not a constant, because score semantics differ between
    providers — one tuned against this store is meaningless against another, and
    the setting says so.
"""

from __future__ import annotations

from agent_platform.telemetry.logging import get_logger
from agent_platform.telemetry.tracing import get_tracer
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.dto.knowledge import RetrievedPassage
from agent_platform_sdk.interfaces.embedding_provider import EmbeddingProvider
from agent_platform_sdk.interfaces.vector_store_provider import (
    VectorRecord,
    VectorStoreProvider,
)

__all__ = ["KnowledgeRetriever"]

_logger = get_logger(__name__)
_tracer = get_tracer(__name__)


class KnowledgeRetriever:
    """Answers "which passages relate to this question?"."""

    def __init__(
        self,
        embeddings: EmbeddingProvider,
        vectors: VectorStoreProvider,
        collection: str = "knowledge",
        default_limit: int = 5,
        minimum_score: float = 0.0,
    ) -> None:
        """Create the retriever.

        Args:
            embeddings: Must be the provider that embedded the corpus. Two
                different models produce vectors in unrelated spaces, and
                searching one with the other returns confident nonsense rather
                than an error — which is why the composition root injects one
                provider into both this and the indexer.
            vectors: Where to search.
            collection: Index to search.
            default_limit: Passages returned when the caller does not say.
            minimum_score: Below this, a match is treated as no match. See the
                module docstring — this is the difference between "I found
                nothing" and a confident answer grounded in noise.
        """
        self._embeddings = embeddings
        self._vectors = vectors
        self._collection = collection
        self._default_limit = default_limit
        self._minimum_score = minimum_score

    async def retrieve(
        self,
        query: str,
        context: ExecutionContext,
        limit: int | None = None,
    ) -> tuple[RetrievedPassage, ...]:
        """Return the passages most related to ``query``, best first.

        An empty tuple means nothing cleared the threshold. That is an answer,
        not a failure: "the knowledge base has nothing on this" is useful, and
        far better than passages that merely resemble the question.

        Raises:
            ProviderError: embedding the query failed. Raised rather than
                returning empty, because "the embedding service is down" and
                "there is nothing about this in the corpus" are different facts
                and must not look alike.
        """
        requested = limit if limit is not None and limit > 0 else self._default_limit

        with _tracer.start_as_current_span("knowledge.retrieve") as span:
            span.set_attribute("knowledge.collection", self._collection)
            span.set_attribute("knowledge.limit", requested)
            # The query is not a span attribute: it is user content, and spans
            # go to systems with different retention and access rules.
            span.set_attribute("knowledge.query_length", len(query))

            (vector,) = await self._embeddings.embed((query,), context)
            matches = await self._vectors.query(self._collection, vector, requested, context)

            passages = tuple(
                _to_passage(record, score)
                for record, score in matches
                if score >= self._minimum_score
            )
            span.set_attribute("knowledge.passage_count", len(passages))

            if not passages:
                _logger.debug(
                    "knowledge.no_matches",
                    collection=self._collection,
                    candidates=len(matches),
                    minimum_score=self._minimum_score,
                    detail=(
                        "Nothing cleared the score threshold. Reported as no "
                        "result rather than as the nearest available text."
                    ),
                    **context.to_log_fields(),
                )

            return passages


def _to_passage(record: VectorRecord, score: float) -> RetrievedPassage:
    """Shape a stored record into a passage.

    Reads defensively from metadata: records may have been written by an earlier
    version of the indexer, and a missing title should degrade a citation rather
    than fail a search.
    """
    metadata = record.metadata
    return RetrievedPassage(
        document_id=str(metadata.get("document_id", record.record_id)),
        title=str(metadata.get("title", "")),
        source=str(metadata.get("source", "")),
        content=str(metadata.get("content", "")),
        score=score,
        chunk_index=int(metadata.get("chunk_index", 0)),
    )
