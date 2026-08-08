"""Internet search via Tavily.

The platform's first *keyed* search provider, and the one to reach for when
answers must reflect the live web.

Why it exists alongside DuckDuckGo
    DuckDuckGo's Instant Answer API returns encyclopaedic abstracts, not ranked
    web results. It answers "what is the Eiffel Tower" well and "what changed in
    Python 3.14" barely at all. Tavily is a search API built for retrieval
    augmentation: real ranked pages, extracted content, and relevance scores.

    The trade is a signup and a per-search cost. Both providers stay, because a
    fresh clone with no accounts must still perform a real search — that is what
    "local development first" means.

    Adding this changed no agent, no tool and no runtime code. It is a new module
    plus a configuration branch, which is the entire argument for the
    `SearchProvider` abstraction (``architecture.md`` §37).

Credentials
    Tavily authenticates with an API key and offers no identity-based mechanism,
    so a key is the only option available — the narrow exception `CLAUDE.md`
    allows. It is held as a `SecretStr`, read from configuration, sent in an
    `Authorization` header rather than a query string or body, and never logged.
    Nothing in this module ever renders it.

Network discipline
    One client, opened at startup and closed at shutdown. Timeouts are always
    configured: an unbounded search holds a chat turn open for as long as the
    upstream cares to take.
"""

from __future__ import annotations

from time import perf_counter
from typing import Any

import httpx

from agent_platform.exceptions.base import ConfigurationError, ProviderError
from agent_platform.telemetry.logging import get_logger
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.contracts.health import ComponentHealth
from agent_platform_sdk.dto.search import SearchQuery, SearchResult, SearchResults
from agent_platform_sdk.types.enums import Capability, HealthStatus

__all__ = ["TavilySearchProvider"]

_logger = get_logger(__name__)

_ENDPOINT = "https://api.tavily.com/search"

#: Tavily's own cap on results per request.
_MAX_RESULTS = 20


class TavilySearchProvider:
    """Ranked web search with extracted content.

    Satisfies :class:`~agent_platform_sdk.interfaces.search_provider.SearchProvider`
    structurally — it inherits nothing, per ADR-0004.
    """

    def __init__(
        self,
        api_key: str,
        provider_id: str = "tavily",
        timeout_seconds: float = 10.0,
        search_depth: str = "basic",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Create the provider.

        Args:
            api_key: Tavily API key. Passed as a plain string because the
                caller has already unwrapped the `SecretStr` from configuration;
                it is never logged, echoed or included in an error.
            provider_id: Identifier it registers under.
            timeout_seconds: Whole-request budget. Bounded deliberately.
            search_depth: ``basic`` or ``advanced``. ``advanced`` returns better
                evidence and costs more per search, so it is configuration
                rather than a hardcoded preference.
            client: Injected client, so tests exercise the parsing without a
                network call, without a key and without patching a global.
        """
        self._api_key = api_key
        self._provider_id = provider_id
        self._timeout_seconds = timeout_seconds
        self._search_depth = search_depth
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
        """Open the HTTP client.

        Deliberately does not call the API. A startup probe would spend a billed
        search on every process start and every rolling restart, and would fail
        this instance for an upstream outage it could otherwise ride out.

        Raises:
            ConfigurationError: no API key was supplied. Failing here beats
                failing on a user's first search with an opaque 401.
        """
        if not self._api_key.strip():
            message = (
                "Tavily is the configured search provider but no API key is set. "
                "Set PLATFORM_SEARCH__TAVILY_API_KEY, or select another provider "
                "with PLATFORM_SEARCH__PROVIDER."
            )
            raise ConfigurationError(message)

        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout_seconds),
                # A header, not a query parameter or body field: query strings
                # end up in proxy logs and error messages, and a body is echoed
                # by some HTTP debugging middleware.
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
            )

        _logger.info(
            "search.initialized",
            provider_id=self._provider_id,
            timeout_seconds=self._timeout_seconds,
            search_depth=self._search_depth,
            # No key material, not even a length or prefix.
            detail="Tavily search API. Ranked web results with extracted content.",
        )

    async def health_check(self) -> ComponentHealth:
        """Report readiness without calling the upstream service.

        Every Tavily call is billed, so a readiness probe that searched would
        turn monitoring into spend — at whatever frequency the orchestrator
        polls. Connectivity is proven by the first real search.
        """
        return ComponentHealth(
            name=self._provider_id,
            status=HealthStatus.HEALTHY if self._client is not None else HealthStatus.UNKNOWN,
            detail=(
                "Tavily search API — ranked web results. Configuration only; "
                "connectivity is proven by the first search, because probing "
                "would spend a billed request per poll."
            ),
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
        """Execute ``query`` against the Tavily search API.

        Raises:
            ProviderError: the service could not be reached, rejected the key,
                or returned something unusable. A query with *no matches* is not
                a failure — it returns empty results, because "nothing found" is
                an answer the agent should reason about.
        """
        del context

        if self._client is None:
            message = "Search provider was not initialised."
            raise ProviderError(message, provider_id=self._provider_id)

        started = perf_counter()

        payload: dict[str, Any] = {
            "query": query.query,
            "max_results": min(query.max_results, _MAX_RESULTS),
            "search_depth": self._search_depth,
        }
        if query.freshness_days is not None:
            payload["days"] = query.freshness_days

        try:
            response = await self._client.post(_ENDPOINT, json=payload)
            response.raise_for_status()
            body: dict[str, Any] = response.json()
        except httpx.HTTPStatusError as error:
            raise self._to_provider_error(error) from error
        except httpx.HTTPError as error:
            # The exception text can carry the full URL and headers — and the
            # headers carry the key. Only the type is reported outward.
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
            results=self._extract(body, query.max_results),
            latency_ms=(perf_counter() - started) * 1000,
        )

    def _to_provider_error(self, error: httpx.HTTPStatusError) -> ProviderError:
        """Map an HTTP failure onto an actionable message.

        The upstream body is never included. It can echo the request — headers
        included — and those carry the API key.
        """
        status = error.response.status_code

        guidance = {
            401: (
                "Tavily rejected the API key. Check PLATFORM_SEARCH__TAVILY_API_KEY; "
                "keys begin with 'tvly-'."
            ),
            403: "Tavily refused the request. The key may be disabled or out of quota.",
            429: "Tavily rate limit reached. Reduce search frequency or raise the plan limit.",
            432: "Tavily plan limit reached. The account is out of credits.",
        }.get(status, f"Tavily returned HTTP {status}.")

        return ProviderError(
            guidance,
            provider_id=self._provider_id,
            details={"status_code": str(status)},
        )

    @staticmethod
    def _extract(body: dict[str, Any], limit: int) -> tuple[SearchResult, ...]:
        """Turn a Tavily payload into normalised results.

        Defensive throughout: a payload shape that changes upstream must degrade
        to fewer results, never to an exception in the middle of a chat turn.

        ``raw_content`` is deliberately ignored. It can run to tens of
        kilobytes per result, and every character of it would be spent context
        in the next prompt — a quiet way to multiply the cost of one search.
        """
        results: list[SearchResult] = []

        for item in body.get("results") or []:
            if len(results) >= limit:
                break
            if not isinstance(item, dict):
                continue

            url = str(item.get("url") or "").strip()
            if not url:
                # A result without a link cannot be cited, and an uncitable
                # result is not evidence.
                continue

            score = item.get("score")
            results.append(
                SearchResult(
                    title=str(item.get("title") or url).strip(),
                    url=url,
                    snippet=str(item.get("content") or "").strip(),
                    score=float(score) if isinstance(score, (int, float)) else None,
                )
            )

        return tuple(results[:limit])
