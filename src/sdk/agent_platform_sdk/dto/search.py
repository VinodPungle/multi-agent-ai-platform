"""Search contracts.

One shape for every search backend — internet search, Azure AI Search, SharePoint,
GitHub — so an agent that cites results does not change when the backend does.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["SearchQuery", "SearchResult", "SearchResults"]


class SearchQuery(BaseModel):
    """A request to a search provider."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    query: str = Field(min_length=1, description="Natural-language or keyword query.")
    max_results: int = Field(default=5, gt=0, le=50)
    locale: str | None = Field(default=None, description="BCP 47 locale hint.")
    freshness_days: int | None = Field(
        default=None,
        gt=0,
        description="Restrict to results published within this many days, where supported.",
    )


class SearchResult(BaseModel):
    """A single result.

    ``url`` and ``title`` are required because grounded answers must be
    citable — a result the user cannot verify is not usable evidence.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str = Field(description="Result title.")
    url: str = Field(description="Canonical link, used as the citation.")
    snippet: str = Field(default="", description="Extract supplied by the provider.")
    published_at: datetime | None = Field(default=None, description="Publication time, if known.")
    score: float | None = Field(default=None, description="Provider relevance score, if reported.")


class SearchResults(BaseModel):
    """The outcome of one search, with the metadata needed to evaluate it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    query: str = Field(description="Query as submitted to the provider.")
    provider_id: str = Field(description="Provider that served the search.")
    results: tuple[SearchResult, ...] = Field(default=())
    latency_ms: float | None = Field(default=None, ge=0)
    from_cache: bool = Field(
        default=False,
        description="Whether the results were served from cache, for cost attribution.",
    )
