"""A search provider that answers locally.

The offline counterpart to :class:`MockLLMProvider`: deterministic results, no
network, no API key. It is the default in tests and the fallback in development,
so the tool framework can be exercised on a laptop with no connectivity and in
CI without depending on a third party staying up.

Deterministic on purpose. A test that asserted on live web results would fail
whenever the web changed, which is constantly — so it would be quarantined within
a week and then ignored.
"""

from __future__ import annotations

from agent_platform.telemetry.logging import get_logger
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.contracts.health import ComponentHealth
from agent_platform_sdk.dto.search import SearchQuery, SearchResult, SearchResults
from agent_platform_sdk.types.enums import Capability, HealthStatus

__all__ = ["MockSearchProvider"]

_logger = get_logger(__name__)


class MockSearchProvider:
    """Returns fabricated but well-formed results.

    Satisfies :class:`~agent_platform_sdk.interfaces.search_provider.SearchProvider`
    structurally.
    """

    def __init__(self, provider_id: str = "mock-search") -> None:
        self._provider_id = provider_id

    @property
    def provider_id(self) -> str:
        """Identifier this provider is registered under."""
        return self._provider_id

    @property
    def supports_citations(self) -> bool:
        """Its URLs are fabricated, so they are not citations.

        Reported honestly. A grounded answer built on these would cite links
        that do not resolve, which is worse than an ungrounded answer — the
        reader has no way to tell until they click.
        """
        return False

    async def initialize(self) -> None:
        """No resources to acquire."""
        _logger.info(
            "search.initialized",
            provider_id=self._provider_id,
            detail="Mock search — results are fabricated, not retrieved.",
        )

    async def health_check(self) -> ComponentHealth:
        """Always healthy: there is no dependency that could be unreachable."""
        return ComponentHealth(
            name=self._provider_id,
            status=HealthStatus.HEALTHY,
            detail="Mock search provider. No external dependency.",
        )

    def supports(self, capability: Capability) -> bool:
        """Declare nothing. Search is not a model capability."""
        del capability
        return False

    async def close(self) -> None:
        """Nothing to release."""

    async def search(self, query: SearchQuery, context: ExecutionContext) -> SearchResults:
        """Return deterministic results derived from the query."""
        del context

        results = tuple(
            SearchResult(
                title=f"{query.query.title()} — result {index + 1}",
                url=f"https://example.invalid/search/{index + 1}",
                snippet=(
                    f"A fabricated extract about {query.query!r}. This is the mock search "
                    "provider; no request left the process."
                ),
                score=1.0 - (index * 0.1),
            )
            for index in range(min(query.max_results, 3))
        )

        return SearchResults(
            query=query.query,
            provider_id=self._provider_id,
            results=results,
            latency_ms=0.0,
        )
