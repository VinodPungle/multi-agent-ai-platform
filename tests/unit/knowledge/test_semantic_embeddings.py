"""The local semantic embedder.

Skipped when the `knowledge` extra is not installed, because it needs a real
model — roughly 200 MB of packages and a 67 MB download. Skipping is honest
here: the suite's other RAG tests already prove the pipeline with the lexical
provider, and what these add is the one property that provider does not have.

The test worth having is the paraphrase test. It is precisely what could not be
written against the hashing provider, and writing it there anyway would have
encoded a false belief about the platform.
"""

from __future__ import annotations

import pytest

from agent_platform.knowledge.in_memory_vector_store import InMemoryVectorStore
from agent_platform.knowledge.indexer import KnowledgeIndexer
from agent_platform.knowledge.retriever import KnowledgeRetriever
from agent_platform.providers.local.semantic_embedding_provider import (
    LocalSemanticEmbeddingProvider,
)
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.dto.knowledge import KnowledgeDocument
from agent_platform_sdk.interfaces.embedding_provider import EmbeddingProvider
from agent_platform_sdk.types.enums import HealthStatus

pytestmark = pytest.mark.unit

# Skips the whole module when the extra is absent, before anything imports the
# provider. `importorskip` rather than a `skipif` on a truthiness check: it
# reports the reason on the collected skip, so a developer sees the command to
# run rather than a bare "skipped".
pytest.importorskip(
    "fastembed",
    reason="needs the `knowledge` extra: uv sync --extra knowledge",
)

CONTEXT = ExecutionContext()

CORPUS = (
    KnowledgeDocument(
        document_id="expenses",
        title="Expense Policy",
        content=(
            "Employees must submit receipts within thirty days of purchase. "
            "Reimbursement is paid with the following month's salary."
        ),
        source="expenses.md",
    ),
    KnowledgeDocument(
        document_id="vehicles",
        title="Company Vehicles",
        content=(
            "A car allocated to a member of staff may be used for personal "
            "journeys at weekends. Fuel is charged to the driver."
        ),
        source="vehicles.md",
    ),
)


async def a_retriever() -> KnowledgeRetriever:
    provider = LocalSemanticEmbeddingProvider()
    await provider.initialize()
    store = InMemoryVectorStore()
    await KnowledgeIndexer(embeddings=provider, vectors=store).index(CORPUS, CONTEXT)
    return KnowledgeRetriever(embeddings=provider, vectors=store)


class TestContractConformance:
    def test_it_satisfies_the_embedding_contract(self) -> None:
        assert isinstance(LocalSemanticEmbeddingProvider(), EmbeddingProvider)

    async def test_health_is_unknown_before_the_model_loads(self) -> None:
        provider = LocalSemanticEmbeddingProvider()

        assert (await provider.health_check()).status is HealthStatus.UNKNOWN


class TestEmbedding:
    async def test_vectors_have_the_models_dimensionality(self) -> None:
        provider = LocalSemanticEmbeddingProvider()
        await provider.initialize()

        (vector,) = await provider.embed(("anything",), CONTEXT)

        assert len(vector) == provider.dimensions == 384

    async def test_a_declared_dimensionality_that_lies_is_refused(self) -> None:
        """An index built at the wrong size cannot be searched, and fails silently."""
        from agent_platform.exceptions.base import ConfigurationError

        provider = LocalSemanticEmbeddingProvider(dimensions=1536)

        with pytest.raises(ConfigurationError, match="dimensional"):
            await provider.initialize()

    async def test_one_vector_per_input_in_order(self) -> None:
        provider = LocalSemanticEmbeddingProvider()
        await provider.initialize()

        first = await provider.embed(("alpha", "beta"), CONTEXT)
        second = await provider.embed(("beta",), CONTEXT)

        assert len(first) == 2
        assert first[1] == pytest.approx(second[0], abs=1e-6)


class TestSemanticRetrieval:
    """What the lexical provider cannot do, and the reason this exists."""

    async def test_a_paraphrase_finds_the_right_document(self) -> None:
        """No shared vocabulary with the source at all.

        "money back" against "reimbursement", "spent" against "purchase". A
        lexical embedder scores this on incidental character overlap; a semantic
        one scores it on meaning. This is the test that could not honestly be
        written against `HashingEmbeddingProvider`.
        """
        retriever = await a_retriever()

        passages = await retriever.retrieve(
            "how soon do I need to claim money back for something I spent?",
            CONTEXT,
            limit=1,
        )

        assert passages
        assert passages[0].source == "expenses.md"

    async def test_a_synonym_finds_the_right_document(self) -> None:
        """ "Automobile" appears nowhere in the corpus; "car" does."""
        retriever = await a_retriever()

        passages = await retriever.retrieve(
            "can I drive the automobile on holiday?",
            CONTEXT,
            limit=1,
        )

        assert passages
        assert passages[0].source == "vehicles.md"

    async def test_related_meaning_scores_above_unrelated_meaning(self) -> None:
        provider = LocalSemanticEmbeddingProvider()
        await provider.initialize()

        claim, reimbursement, weather = await provider.embed(
            (
                "claiming back money I spent at work",
                "employees are reimbursed for expenses",
                "the forecast is for heavy rain on Tuesday",
            ),
            CONTEXT,
        )

        def similarity(a: tuple[float, ...], b: tuple[float, ...]) -> float:
            return sum(x * y for x, y in zip(a, b, strict=True))

        assert similarity(claim, reimbursement) > similarity(claim, weather)
