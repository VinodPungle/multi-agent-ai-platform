"""Search provider contract.

Search is abstracted so that internet search, Azure AI Search, SharePoint and
enterprise sources are interchangeable behind one interface
(``architecture.md`` §37).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.dto.search import SearchQuery, SearchResults
from agent_platform_sdk.interfaces.provider import Provider

__all__ = ["SearchProvider"]


@runtime_checkable
class SearchProvider(Provider, Protocol):
    """Retrieval of external documents or web results."""

    async def search(self, query: SearchQuery, context: ExecutionContext) -> SearchResults:
        """Execute ``query`` and return normalised results.

        A query with no matches returns empty results — that is an answer, not a
        failure. Raise only when the provider itself could not be reached.
        """
        ...

    @property
    def supports_citations(self) -> bool:
        """Whether results carry verifiable source links.

        Grounded answers require citations, so the runtime needs to know this
        before choosing a provider for a citation-bearing response.
        """
        ...
