"""Knowledge base contracts.

What goes in, and what comes back out. Both are deliberately provider-neutral:
nothing here knows what embedded the text or what stored the vector.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["KnowledgeDocument", "RetrievedPassage"]


class KnowledgeDocument(BaseModel):
    """A document before it is chunked and indexed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: str = Field(
        min_length=1,
        description=(
            "Stable identifier. Re-indexing the same id replaces its passages "
            "rather than duplicating them, which is what makes ingestion "
            "repeatable — a pipeline that is not safe to re-run is a pipeline "
            "nobody dares re-run."
        ),
    )
    title: str = Field(default="", description="Human-readable title, cited back to the user.")
    content: str = Field(min_length=1, description="Full text.")
    source: str = Field(
        default="",
        description=(
            "Where it came from — a path, a URL, a ticket. Carried through to "
            "the passage so an answer can point at something checkable."
        ),
    )


class RetrievedPassage(BaseModel):
    """One chunk found in response to a query."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: str = Field(description="Document this passage came from.")
    title: str = Field(default="")
    source: str = Field(default="")
    content: str = Field(description="The passage text, as it will reach the model.")
    score: float = Field(
        description=(
            "Similarity, higher is better. Comparable only within one "
            "provider's results — score semantics differ between vector stores, "
            "so a threshold tuned against one is meaningless against another."
        ),
    )
    chunk_index: int = Field(
        default=0,
        ge=0,
        description="Position within the document, so adjacent passages are recognisable.",
    )
