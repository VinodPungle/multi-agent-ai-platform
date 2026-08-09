"""Retrieval-augmented generation, end to end.

Chunking, embedding, indexing and retrieval — driven through the *real*
components rather than fakes. `HashingEmbeddingProvider` and
`InMemoryVectorStore` are production classes with a documented scope, not test
doubles, so a pipeline exercised here is the same pipeline that runs.

What the tests deliberately do **not** assert is retrieval quality in any
semantic sense. The development embedder matches shared character sequences, not
meaning, and a test claiming "the right passage was returned for a paraphrased
question" would be asserting a property this provider does not have and quietly
encoding a false belief about the platform.
"""

from __future__ import annotations

import pytest

from agent_platform.knowledge.chunking import chunk_document
from agent_platform.knowledge.in_memory_vector_store import InMemoryVectorStore
from agent_platform.knowledge.indexer import KnowledgeIndexer
from agent_platform.knowledge.retriever import KnowledgeRetriever
from agent_platform.providers.mock.hashing_embedding_provider import HashingEmbeddingProvider
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.dto.knowledge import KnowledgeDocument
from agent_platform_sdk.interfaces.embedding_provider import EmbeddingProvider
from agent_platform_sdk.interfaces.vector_store_provider import (
    VectorRecord,
    VectorStoreProvider,
)
from agent_platform_sdk.types.enums import HealthStatus

pytestmark = pytest.mark.unit

CONTEXT = ExecutionContext()


def a_document(document_id: str = "doc-1", content: str = "hello world") -> KnowledgeDocument:
    return KnowledgeDocument(
        document_id=document_id,
        title=f"Title of {document_id}",
        content=content,
        source=f"{document_id}.md",
    )


def a_pipeline(
    *,
    max_chunk_characters: int = 1_200,
    minimum_score: float = 0.0,
) -> tuple[KnowledgeIndexer, KnowledgeRetriever, InMemoryVectorStore]:
    """The real components, wired the way the composition root wires them."""
    embeddings = HashingEmbeddingProvider(dimensions=128)
    store = InMemoryVectorStore()
    indexer = KnowledgeIndexer(
        embeddings=embeddings,
        vectors=store,
        max_chunk_characters=max_chunk_characters,
    )
    retriever = KnowledgeRetriever(
        embeddings=embeddings,
        vectors=store,
        minimum_score=minimum_score,
    )
    return indexer, retriever, store


class TestContractConformance:
    def test_the_embedding_provider_satisfies_its_contract(self) -> None:
        assert isinstance(HashingEmbeddingProvider(), EmbeddingProvider)

    def test_the_vector_store_satisfies_its_contract(self) -> None:
        assert isinstance(InMemoryVectorStore(), VectorStoreProvider)


class TestChunking:
    def test_a_short_document_is_one_chunk(self) -> None:
        """Splitting for consistency's sake would fragment a passage for nothing."""
        chunks = chunk_document(a_document(content="Short."), max_characters=1_000)

        assert len(chunks) == 1

    def test_a_long_document_is_split(self) -> None:
        document = a_document(content="\n\n".join(f"Paragraph {i}. " * 20 for i in range(20)))

        chunks = chunk_document(document, max_characters=500)

        assert len(chunks) > 1

    def test_no_chunk_exceeds_the_limit_before_overlap(self) -> None:
        document = a_document(content="\n\n".join(f"Paragraph {i}. " * 20 for i in range(20)))

        chunks = chunk_document(document, max_characters=500, overlap_characters=0)

        assert all(len(chunk.content) <= 500 for chunk in chunks)

    def test_a_paragraph_longer_than_the_limit_is_still_split(self) -> None:
        """A minified file or a base64 blob has no structural boundary to use."""
        document = a_document(content="x" * 5_000)

        chunks = chunk_document(document, max_characters=400, overlap_characters=0)

        assert all(len(chunk.content) <= 400 for chunk in chunks)
        assert len(chunks) >= 12

    def test_chunks_are_indexed_in_document_order(self) -> None:
        document = a_document(content="\n\n".join(f"Paragraph {i}. " * 20 for i in range(10)))

        chunks = chunk_document(document, max_characters=300)

        assert [chunk.index for chunk in chunks] == list(range(len(chunks)))

    def test_overlap_repeats_the_previous_tail(self) -> None:
        """Guards the answer that falls exactly on a boundary."""
        document = a_document(content="\n\n".join(f"Paragraph {i}. " * 20 for i in range(6)))

        without = chunk_document(document, max_characters=400, overlap_characters=0)
        with_overlap = chunk_document(document, max_characters=400, overlap_characters=100)

        assert len(with_overlap[1].content) > len(without[1].content)

    def test_an_empty_document_produces_nothing(self) -> None:
        assert chunk_document(a_document(content="   ")) == ()


class TestEmbedding:
    async def test_it_returns_one_vector_per_text(self) -> None:
        vectors = await HashingEmbeddingProvider(dimensions=64).embed(("a", "b", "c"), CONTEXT)

        assert len(vectors) == 3

    async def test_vectors_have_the_declared_dimensionality(self) -> None:
        """An index is built at one dimensionality and cannot accept another."""
        provider = HashingEmbeddingProvider(dimensions=64)

        (vector,) = await provider.embed(("anything",), CONTEXT)

        assert len(vector) == provider.dimensions

    async def test_it_is_deterministic_across_instances(self) -> None:
        """Otherwise the index would be invalid after every restart.

        Not a hypothetical: Python's built-in `hash()` is randomised per
        process, and using it here would rebuild a different index each boot
        while every query silently matched nothing.
        """
        first = await HashingEmbeddingProvider(dimensions=64).embed(("stable",), CONTEXT)
        second = await HashingEmbeddingProvider(dimensions=64).embed(("stable",), CONTEXT)

        assert first == second

    async def test_similar_text_embeds_more_closely_than_unrelated_text(self) -> None:
        """Lexical, not semantic — the property this provider actually has."""
        provider = HashingEmbeddingProvider(dimensions=256)

        related, same_topic, unrelated = await provider.embed(
            (
                "conversation memory is stored in redis",
                "redis stores the conversation memory",
                "quarterly aubergine harvest forecast",
            ),
            CONTEXT,
        )

        def similarity(a: tuple[float, ...], b: tuple[float, ...]) -> float:
            return sum(x * y for x, y in zip(a, b, strict=True))

        assert similarity(related, same_topic) > similarity(related, unrelated)

    async def test_text_with_nothing_hashable_does_not_fail(self) -> None:
        """One odd passage must not fail a whole ingestion run."""
        (vector,) = await HashingEmbeddingProvider(dimensions=32).embed(("!!!",), CONTEXT)

        assert len(vector) == 32


class TestIndexingAndRetrieval:
    async def test_an_indexed_document_can_be_found(self) -> None:
        indexer, retriever, _ = a_pipeline()
        await indexer.index((a_document(content="The platform uses Redis for memory."),), CONTEXT)

        passages = await retriever.retrieve("Redis memory", CONTEXT)

        assert passages
        assert "Redis" in passages[0].content

    async def test_a_passage_carries_its_citation(self) -> None:
        """An answer has to point at something checkable."""
        indexer, retriever, _ = a_pipeline()
        await indexer.index((a_document(content="Budgets are enforced by the runtime."),), CONTEXT)

        (passage,) = await retriever.retrieve("budgets runtime", CONTEXT)

        assert passage.document_id == "doc-1"
        assert passage.title == "Title of doc-1"
        assert passage.source == "doc-1.md"

    async def test_results_are_ordered_best_first(self) -> None:
        indexer, retriever, _ = a_pipeline()
        await indexer.index(
            (
                a_document("doc-1", "Conversation memory is stored in Redis."),
                a_document("doc-2", "The aubergine harvest was disappointing."),
            ),
            CONTEXT,
        )

        passages = await retriever.retrieve("conversation memory redis", CONTEXT, limit=2)

        assert passages[0].score >= passages[1].score
        assert passages[0].document_id == "doc-1"

    async def test_the_limit_is_respected(self) -> None:
        """Every passage returned is prompt context spent on the next call."""
        indexer, retriever, _ = a_pipeline()
        await indexer.index(
            tuple(a_document(f"doc-{i}", f"Document number {i} about memory.") for i in range(8)),
            CONTEXT,
        )

        assert len(await retriever.retrieve("memory", CONTEXT, limit=3)) == 3

    async def test_an_empty_index_returns_nothing_rather_than_failing(self) -> None:
        _, retriever, _ = a_pipeline()

        assert await retriever.retrieve("anything", CONTEXT) == ()


class TestReindexing:
    async def test_reindexing_replaces_rather_than_duplicates(self) -> None:
        """A pipeline that is not safe to re-run is one nobody dares re-run."""
        indexer, _, store = a_pipeline()
        document = a_document(content="Original content about budgets.")

        await indexer.index((document,), CONTEXT)
        await indexer.index((document,), CONTEXT)

        assert store.count("knowledge") == 1

    async def test_edited_content_replaces_the_old_text(self) -> None:
        indexer, retriever, _ = a_pipeline()

        await indexer.index((a_document(content="Budgets are advisory."),), CONTEXT)
        await indexer.index((a_document(content="Budgets are enforced."),), CONTEXT)

        (passage,) = await retriever.retrieve("budgets", CONTEXT)
        assert passage.content == "Budgets are enforced."

    async def test_a_document_that_shrinks_leaves_no_orphans(self) -> None:
        """Old passages would otherwise still be returned as though they existed."""
        indexer, _, store = a_pipeline(max_chunk_characters=200)
        long_content = "\n\n".join(f"Paragraph {i} about the platform. " * 5 for i in range(10))

        await indexer.index((a_document(content=long_content),), CONTEXT)
        many = store.count("knowledge")

        await indexer.index((a_document(content="Now it is short."),), CONTEXT)

        assert many > 1
        assert store.count("knowledge") == 1


class TestScoreThreshold:
    async def test_a_weak_match_is_excluded(self) -> None:
        """Nearest neighbours are always returned; that is not the same as relevant.

        Without a threshold, a corpus with nothing to say about the question
        still hands the model its least-unlike text — which invites a confident
        answer grounded in noise.
        """
        indexer, retriever, _ = a_pipeline(minimum_score=0.99)
        await indexer.index((a_document(content="Conversation memory uses Redis."),), CONTEXT)

        assert await retriever.retrieve("aubergine harvest forecast", CONTEXT) == ()

    async def test_a_strong_match_still_passes_the_threshold(self) -> None:
        indexer, retriever, _ = a_pipeline(minimum_score=0.2)
        await indexer.index((a_document(content="Conversation memory uses Redis."),), CONTEXT)

        assert await retriever.retrieve("conversation memory uses redis", CONTEXT)


class TestVectorStore:
    async def test_collections_do_not_leak_into_each_other(self) -> None:
        store = InMemoryVectorStore()
        await store.upsert("a", (VectorRecord("1", (1.0, 0.0)),), CONTEXT)
        await store.upsert("b", (VectorRecord("2", (0.0, 1.0)),), CONTEXT)

        results = await store.query("a", (1.0, 0.0), 10, CONTEXT)

        assert [record.record_id for record, _ in results] == ["1"]

    async def test_a_record_can_be_deleted(self) -> None:
        store = InMemoryVectorStore()
        await store.upsert("a", (VectorRecord("1", (1.0, 0.0)),), CONTEXT)

        await store.delete("a", ("1",), CONTEXT)

        assert await store.query("a", (1.0, 0.0), 10, CONTEXT) == ()

    async def test_deleting_an_unknown_record_succeeds(self) -> None:
        store = InMemoryVectorStore()

        await store.delete("nowhere", ("nothing",), CONTEXT)

    async def test_similarity_is_scale_invariant(self) -> None:
        """Cosine similarity compares direction; magnitude must not decide a ranking."""
        store = InMemoryVectorStore()
        await store.upsert("a", (VectorRecord("long", (10.0, 0.0)),), CONTEXT)

        ((_, score),) = await store.query("a", (1.0, 0.0), 1, CONTEXT)

        assert score == pytest.approx(1.0)

    async def test_a_zero_vector_is_indexed_rather_than_rejected(self) -> None:
        """Refusing would fail an ingestion run over one empty passage."""
        store = InMemoryVectorStore()

        await store.upsert("a", (VectorRecord("empty", (0.0, 0.0)),), CONTEXT)

        assert store.count("a") == 1

    async def test_the_index_is_capped(self) -> None:
        """An unbounded index fed by ingestion is a way to exhaust the process."""
        store = InMemoryVectorStore(max_records_per_collection=5)

        await store.upsert(
            "a",
            tuple(VectorRecord(str(i), (float(i), 1.0)) for i in range(20)),
            CONTEXT,
        )

        assert store.count("a") == 5

    async def test_an_empty_index_is_healthy(self) -> None:
        """Nothing ingested yet is a legitimate state, unlike having no prompts."""
        assert (await InMemoryVectorStore().health_check()).status is HealthStatus.HEALTHY
