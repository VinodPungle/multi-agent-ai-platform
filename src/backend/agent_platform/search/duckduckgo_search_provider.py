"""Internet search via DuckDuckGo's Instant Answer API.

The first provider in the platform that talks to something real. Chosen for one
reason above all: it needs no API key, so `docker compose up` gives a working
internet search with no signup, which is what "local development first" requires.

What it actually returns, and the honesty that requires
    The Instant Answer API is *not* a web-results API. It returns DuckDuckGo's
    abstract for a topic plus related topics — encyclopaedic answers, not ranked
    pages. For "eiffel tower" that is genuinely useful; for "best python
    profiler 2026" it returns very little.

    That limitation is documented here, surfaced in the provider's health detail,
    and is the reason the platform ships two search providers rather than
    pretending one is enough. A keyed provider (Brave, Tavily, Bing) is a new
    adapter in this package plus configuration — the tool, the runtime and every
    agent are unaffected, which is the point of the abstraction.

Network discipline
    One client, created at startup and closed at shutdown, because creating a
    client per request leaks connections and re-does TLS every time. Timeouts are
    configured, never unbounded: a search that hangs would hold a chat turn open
    for as long as the upstream cared to take.
"""

from __future__ import annotations

from time import perf_counter
from typing import Any

import httpx

from agent_platform.exceptions.base import ProviderError
from agent_platform.telemetry.logging import get_logger
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.contracts.health import ComponentHealth
from agent_platform_sdk.dto.search import SearchQuery, SearchResult, SearchResults
from agent_platform_sdk.types.enums import Capability, HealthStatus

__all__ = ["DuckDuckGoSearchProvider"]

_logger = get_logger(__name__)

_ENDPOINT = "https://api.duckduckgo.com/"


class DuckDuckGoSearchProvider:
    """Keyless internet search.

    Satisfies :class:`~agent_platform_sdk.interfaces.search_provider.SearchProvider`
    structurally.
    """

    def __init__(
        self,
        provider_id: str = "duckduckgo",
        timeout_seconds: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Create the provider.

        Args:
            provider_id: Identifier it registers under.
            timeout_seconds: Whole-request budget. Bounded deliberately.
            client: Injected client, so tests exercise the parsing without a
                network call and without patching a global.
        """
        self._provider_id = provider_id
        self._timeout_seconds = timeout_seconds
        self._client = client
        self._owns_client = client is None

    @property
    def provider_id(self) -> str:
        """Identifier this provider is registered under."""
        return self._provider_id

    @property
    def supports_citations(self) -> bool:
        """Every result carries a resolvable source URL."""
        return True

    async def initialize(self) -> None:
        """Open the HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout_seconds),
                # A descriptive agent string is basic courtesy to a free service
                # and makes our traffic identifiable in their logs.
                headers={"User-Agent": "agent-platform/0.1 (+https://github.com/)"},
            )
        _logger.info(
            "search.initialized",
            provider_id=self._provider_id,
            timeout_seconds=self._timeout_seconds,
            detail="DuckDuckGo Instant Answer API. Abstracts and related topics, not web results.",
        )

    async def health_check(self) -> ComponentHealth:
        """Report readiness without calling the upstream service.

        Deliberately does not probe the network. A readiness endpoint that made
        an outbound call would fail this instance for someone else's outage, and
        would be called often enough to become traffic of its own.
        """
        return ComponentHealth(
            name=self._provider_id,
            status=HealthStatus.HEALTHY if self._client is not None else HealthStatus.UNKNOWN,
            detail="DuckDuckGo Instant Answer API — abstracts and related topics, not web results.",
        )

    def supports(self, capability: Capability) -> bool:
        """Declare nothing. Search is not a model capability."""
        del capability
        return False

    async def close(self) -> None:
        """Close the HTTP client, if this provider opened it."""
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    async def search(self, query: SearchQuery, context: ExecutionContext) -> SearchResults:
        """Execute ``query`` against the Instant Answer API.

        Raises:
            ProviderError: the service could not be reached or returned a
                response that is not usable. A query with *no matches* is not a
                failure — it returns empty results, because "nothing found" is an
                answer the agent should reason about.
        """
        del context

        if self._client is None:
            message = "Search provider was not initialised."
            raise ProviderError(message, provider_id=self._provider_id)

        started = perf_counter()

        started = perf_counter()

        try:
            response = await self._client.get(
                _ENDPOINT,
                params={
                    "q": query.query,
                    "format": "json",
                    # Strip markup and tracking redirects: the snippet is going
                    # into a prompt, and HTML there is noise a model may echo.
                    "no_html": "1",
                    "no_redirect": "1",
                    "skip_disambig": "1",
                },
            )
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
        except httpx.HTTPError as error:
            # The exception text can contain the full URL and headers, so only
            # the type is reported outward.
            message = f"Search request failed: {type(error).__name__}."
            raise ProviderError(
                message,
                provider_id=self._provider_id,
                details={"error_type": type(error).__name__},
            ) from error
        except ValueError as error:
            message = "Search provider returned a response that is not JSON."
            raise ProviderError(message, provider_id=self._provider_id) from error

        return SearchResults(
            query=query.query,
            provider_id=self._provider_id,
            results=self._extract(payload, query.max_results),
            # Measured here rather than read from `response.elapsed`: that
            # attribute is only populated once the response has been read,
            # and it times httpx's transport rather than the budget this
            # provider is actually accountable for.
            latency_ms=(perf_counter() - started) * 1000,
        )

    @staticmethod
    def _extract(payload: dict[str, Any], limit: int) -> tuple[SearchResult, ...]:
        """Turn an Instant Answer payload into normalised results.

        Two shapes are mined, in order of usefulness: the topic abstract, then
        related topics. Both are optional and either may be absent, so every
        access is defensive — a payload shape that changes upstream must degrade
        to fewer results, never to an exception in the middle of a chat turn.
        """
        results: list[SearchResult] = []

        abstract = str(payload.get("AbstractText") or "").strip()
        abstract_url = str(payload.get("AbstractURL") or "").strip()
        if abstract and abstract_url:
            results.append(
                SearchResult(
                    title=str(payload.get("Heading") or "Summary").strip(),
                    url=abstract_url,
                    snippet=abstract,
                    score=1.0,
                )
            )

        related = payload.get("RelatedTopics")
        if isinstance(related, list):
            for index, topic in enumerate(related):
                if len(results) >= limit:
                    break
                if not isinstance(topic, dict):
                    continue

                # A grouped topic has `Topics` instead of a URL. Skipped rather
                # than flattened: the group's children are usually
                # disambiguations, which make poor evidence.
                url = str(topic.get("FirstURL") or "").strip()
                text = str(topic.get("Text") or "").strip()
                if not url or not text:
                    continue

                # `Text` is "Title - description" when a description exists.
                title, separator, snippet = text.partition(" - ")
                results.append(
                    SearchResult(
                        title=title.strip() or text[:80],
                        url=url,
                        snippet=(snippet if separator else text).strip(),
                        score=max(0.1, 0.9 - (index * 0.05)),
                    )
                )

        return tuple(results[:limit])
