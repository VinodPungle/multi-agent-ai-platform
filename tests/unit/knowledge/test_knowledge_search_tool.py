"""The knowledge-search tool, and loading a corpus off disk.

Driven through the real retriever over the real in-memory store, so what is
tested is the path a model's tool call actually takes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_platform.exceptions.base import ProviderError, ValidationError
from agent_platform.knowledge.document_loader import load_documents
from agent_platform.knowledge.in_memory_vector_store import InMemoryVectorStore
from agent_platform.knowledge.indexer import KnowledgeIndexer
from agent_platform.knowledge.retriever import KnowledgeRetriever
from agent_platform.providers.mock.hashing_embedding_provider import HashingEmbeddingProvider
from agent_platform.tools.knowledge_search_tool import (
    KNOWLEDGE_SEARCH_TOOL_ID,
    KnowledgeSearchTool,
)
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.dto.knowledge import KnowledgeDocument
from agent_platform_sdk.dto.tool import ToolInvocation
from agent_platform_sdk.interfaces.tool_provider import ToolProvider

pytestmark = pytest.mark.unit

CONTEXT = ExecutionContext()

#: The corpus checked into this repository. Resolved once, at module level:
#: touching the filesystem inside an async test blocks the event loop, and
#: the path does not change between tests.
REPOSITORY_CORPUS = Path(__file__).resolve().parents[3] / "knowledge"


class BrokenEmbeddings:
    """Fails every call, the way an unavailable embedding deployment does."""

    @property
    def provider_id(self) -> str:
        return "broken-embeddings"

    @property
    def dimensions(self) -> int:
        return 8

    async def initialize(self) -> None: ...

    async def close(self) -> None: ...

    def supports(self, capability: object) -> bool:
        del capability
        return False

    async def health_check(self) -> Any:  # noqa: ANN401 - not exercised here
        raise NotImplementedError

    async def embed(self, texts: tuple[str, ...], context: ExecutionContext) -> Any:  # noqa: ANN401
        del texts, context
        message = "embedding deployment unavailable"
        raise ProviderError(message, provider_id="broken-embeddings")


async def a_tool(*documents: KnowledgeDocument) -> KnowledgeSearchTool:
    embeddings = HashingEmbeddingProvider(dimensions=128)
    store = InMemoryVectorStore()
    if documents:
        await KnowledgeIndexer(embeddings=embeddings, vectors=store).index(documents, CONTEXT)
    return KnowledgeSearchTool(retriever=KnowledgeRetriever(embeddings=embeddings, vectors=store))


def an_invocation(**arguments: Any) -> ToolInvocation:  # noqa: ANN401
    return ToolInvocation(tool_id=KNOWLEDGE_SEARCH_TOOL_ID, arguments=arguments)


def a_document(document_id: str, content: str) -> KnowledgeDocument:
    return KnowledgeDocument(
        document_id=document_id,
        title=document_id.replace("-", " ").title(),
        content=content,
        source=f"{document_id}.md",
    )


class TestContractConformance:
    async def test_it_is_an_ordinary_tool_provider(self) -> None:
        assert isinstance(await a_tool(), ToolProvider)


class TestDescriptor:
    async def test_the_description_distinguishes_it_from_internet_search(self) -> None:
        """Prompt material. A vague description sends internal questions to the web."""
        description = (await a_tool()).descriptor.description.lower()

        assert "internal" in description
        assert "internet search" in description

    async def test_it_asks_the_model_to_cite(self) -> None:
        assert "cite" in (await a_tool()).descriptor.description.lower()

    async def test_retrieval_may_be_retried(self) -> None:
        """A read with no side effects, unlike a remote MCP tool."""
        assert (await a_tool()).descriptor.retry_policy.max_attempts == 2


class TestValidation:
    async def test_a_query_is_required(self) -> None:
        with pytest.raises(ValidationError):
            await (await a_tool()).validate(an_invocation())

    async def test_a_blank_query_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            await (await a_tool()).validate(an_invocation(query="   "))

    async def test_an_overlong_query_is_refused(self) -> None:
        """A model occasionally pastes a whole conversation into a search box."""
        with pytest.raises(ValidationError):
            await (await a_tool()).validate(an_invocation(query="x" * 500))

    async def test_a_nonsense_passage_count_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            await (await a_tool()).validate(an_invocation(query="ok", max_passages=99))

    async def test_a_boolean_is_not_an_integer(self) -> None:
        """`True` is an int in Python, and would sail through a naive check."""
        with pytest.raises(ValidationError):
            await (await a_tool()).validate(an_invocation(query="ok", max_passages=True))

    async def test_a_valid_invocation_passes(self) -> None:
        await (await a_tool()).validate(an_invocation(query="budgets", max_passages=3))


class TestExecution:
    async def test_it_returns_passages_the_model_can_read(self) -> None:
        tool = await a_tool(a_document("budgets", "Budgets are enforced by the runtime."))

        result = await tool.execute(an_invocation(query="budgets runtime"), CONTEXT)

        assert result.succeeded is True
        assert result.output is not None
        assert result.output["passage_count"] == 1
        assert "Budgets are enforced" in result.output["passages"][0]["content"]

    async def test_each_passage_carries_a_citation(self) -> None:
        tool = await a_tool(a_document("budgets", "Budgets are enforced by the runtime."))

        result = await tool.execute(an_invocation(query="budgets runtime"), CONTEXT)

        assert result.output is not None
        passage = result.output["passages"][0]
        assert passage["title"] == "Budgets"
        assert passage["source"] == "budgets.md"

    async def test_storage_details_do_not_reach_the_model(self) -> None:
        """Every field returned is context spent, and these are unusable to a model."""
        tool = await a_tool(a_document("budgets", "Budgets are enforced."))

        result = await tool.execute(an_invocation(query="budgets"), CONTEXT)

        assert result.output is not None
        assert "document_id" not in result.output["passages"][0]
        assert "chunk_index" not in result.output["passages"][0]

    async def test_the_score_is_returned_so_a_weak_match_can_be_weighed(self) -> None:
        tool = await a_tool(a_document("budgets", "Budgets are enforced."))

        result = await tool.execute(an_invocation(query="budgets"), CONTEXT)

        assert result.output is not None
        assert isinstance(result.output["passages"][0]["score"], float)

    async def test_no_results_is_a_success_not_a_failure(self) -> None:
        """ "I searched our documents and found nothing" is a useful answer.

        Reporting it as failure would push the model to retry a query that will
        find nothing again — and invite it to answer from memory without saying
        the corpus was silent.
        """
        tool = await a_tool()

        result = await tool.execute(an_invocation(query="anything at all"), CONTEXT)

        assert result.succeeded is True
        assert result.output is not None
        assert result.output["passage_count"] == 0

    async def test_an_unavailable_embedding_service_is_a_visible_failure(self) -> None:
        """Distinct from finding nothing: the agent should be able to say so."""
        tool = KnowledgeSearchTool(
            retriever=KnowledgeRetriever(
                embeddings=BrokenEmbeddings(),  # type: ignore[arg-type]
                vectors=InMemoryVectorStore(),
            )
        )

        result = await tool.execute(an_invocation(query="budgets"), CONTEXT)

        assert result.succeeded is False
        assert result.error_message

    async def test_the_call_id_is_echoed(self) -> None:
        tool = await a_tool(a_document("budgets", "Budgets are enforced."))
        invocation = ToolInvocation(
            tool_id=KNOWLEDGE_SEARCH_TOOL_ID,
            arguments={"query": "budgets"},
            call_id="call-1",
        )

        assert (await tool.execute(invocation, CONTEXT)).call_id == "call-1"


class TestDocumentLoading:
    def test_markdown_files_are_loaded(self, tmp_path: Path) -> None:
        (tmp_path / "policy.md").write_text("# Expense Policy\n\nClaim within 30 days.")

        (document,) = load_documents(tmp_path)

        assert document.content.startswith("# Expense Policy")

    def test_the_first_heading_becomes_the_title(self, tmp_path: Path) -> None:
        """A citation reading "Expense Policy" beats one reading the filename."""
        (tmp_path / "expenses-v2-final.md").write_text("# Expense Policy\n\nBody.")

        (document,) = load_documents(tmp_path)

        assert document.title == "Expense Policy"

    def test_a_file_without_a_heading_falls_back_to_its_name(self, tmp_path: Path) -> None:
        (tmp_path / "release_notes.txt").write_text("Version 2 shipped.")

        (document,) = load_documents(tmp_path)

        assert document.title == "Release Notes"

    def test_the_document_id_is_a_portable_relative_path(self, tmp_path: Path) -> None:
        """An absolute path would change between a laptop and a container.

        The whole corpus would then be duplicated on the first deployment,
        because ids are what make re-indexing a replacement.
        """
        nested = tmp_path / "policies"
        nested.mkdir()
        (nested / "expenses.md").write_text("# Expenses\n\nBody.")

        (document,) = load_documents(tmp_path)

        assert document.document_id == "policies/expenses.md"

    def test_subdirectories_are_searched(self, tmp_path: Path) -> None:
        nested = tmp_path / "a" / "b"
        nested.mkdir(parents=True)
        (nested / "deep.md").write_text("# Deep\n\nBody.")

        assert len(load_documents(tmp_path)) == 1

    def test_unsupported_formats_are_skipped(self, tmp_path: Path) -> None:
        """A bad PDF parser produces text that looks fine and has lost its structure."""
        (tmp_path / "report.pdf").write_bytes(b"%PDF-1.4 binary")
        (tmp_path / "notes.md").write_text("# Notes\n\nBody.")

        (document,) = load_documents(tmp_path)

        assert document.source == "notes.md"

    def test_an_empty_file_is_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "empty.md").write_text("   \n\n  ")

        assert load_documents(tmp_path) == ()

    def test_a_missing_directory_is_not_an_error(self, tmp_path: Path) -> None:
        """No corpus is a legitimate state, reported by the tool finding nothing."""
        assert load_documents(tmp_path / "nope") == ()

    def test_documents_load_in_a_stable_order(self, tmp_path: Path) -> None:
        for name in ("c.md", "a.md", "b.md"):
            (tmp_path / name).write_text(f"# {name}\n\nBody.")

        assert [d.source for d in load_documents(tmp_path)] == ["a.md", "b.md", "c.md"]


class TestTheRepositoryCorpus:
    """The corpus checked into this repository, indexed and queried for real."""

    def test_it_loads(self) -> None:
        assert len(load_documents(REPOSITORY_CORPUS)) >= 3

    async def test_a_question_about_the_platform_finds_the_right_document(self) -> None:
        """A real corpus, a real index, and a query whose wording overlaps it.

        Deliberately worded to overlap the source text: the development embedder
        is lexical, and a paraphrase test here would assert a property this
        provider does not have.
        """
        tool = await a_tool(*load_documents(REPOSITORY_CORPUS))

        result = await tool.execute(
            an_invocation(query="trace sampling telemetry cost lever"),
            CONTEXT,
        )

        assert result.output is not None
        assert result.output["passage_count"] > 0
        assert result.output["passages"][0]["source"] == "cost-controls.md"
