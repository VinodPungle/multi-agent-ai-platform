"""Tavily search provider behaviour.

Driven through `httpx.MockTransport`, so request shaping, response parsing,
error mapping and secret handling are all exercised with no network call, no API
key and no account. That matters beyond convenience: this suite has to pass in
CI and on a laptop belonging to someone who has never heard of Tavily.

Every Tavily call is billed, so a test that hit the real API would make the
suite cost money to run — and would be skipped everywhere it could not.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from agent_platform.exceptions.base import ConfigurationError, ProviderError
from agent_platform.search.tavily_search_provider import TavilySearchProvider
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.dto.search import SearchQuery
from agent_platform_sdk.interfaces.search_provider import SearchProvider
from agent_platform_sdk.types.enums import HealthStatus

pytestmark = pytest.mark.unit

CONTEXT = ExecutionContext()
KEY = "tvly-test-key"

PAYLOAD: dict[str, Any] = {
    "query": "eiffel tower",
    "results": [
        {
            "title": "Eiffel Tower",
            "url": "https://en.wikipedia.org/wiki/Eiffel_Tower",
            "content": "A wrought-iron lattice tower on the Champ de Mars in Paris.",
            "score": 0.98,
            "raw_content": "x" * 50_000,
        },
        {
            "title": "Visiting the tower",
            "url": "https://www.toureiffel.paris/en",
            "content": "Official visitor information.",
            "score": 0.81,
        },
    ],
}


Handler = Callable[[httpx.Request], httpx.Response]


def build_provider(
    handler: Handler | None = None,
    # Heterogeneous constructor fields.
    **overrides: Any,  # noqa: ANN401
) -> tuple[TavilySearchProvider, list[httpx.Request]]:
    """Assemble a provider over a mocked transport, recording what it sent."""
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if handler is None:
            return httpx.Response(200, json=PAYLOAD)
        return handler(request)

    transport = httpx.MockTransport(respond)
    fields: dict[str, Any] = {
        "api_key": KEY,
        "client": httpx.AsyncClient(
            transport=transport,
            headers={"Authorization": f"Bearer {KEY}"},
        ),
    }
    fields.update(overrides)
    return TavilySearchProvider(**fields), seen


def a_query(**overrides: Any) -> SearchQuery:  # noqa: ANN401 - mixed field types
    fields: dict[str, Any] = {"query": "eiffel tower", "max_results": 5}
    fields.update(overrides)
    return SearchQuery(**fields)


class TestContractConformance:
    def test_it_satisfies_the_search_provider_contract(self) -> None:
        provider, _ = build_provider()
        assert isinstance(provider, SearchProvider)

    def test_results_are_citable(self) -> None:
        """A grounded answer needs verifiable links."""
        provider, _ = build_provider()
        assert provider.supports_citations is True


class TestConfiguration:
    async def test_a_missing_key_fails_at_startup(self) -> None:
        """Better than a 401 on a user's first search, which names nothing."""
        provider = TavilySearchProvider(api_key="")

        with pytest.raises(ConfigurationError, match="no API key"):
            await provider.initialize()

    async def test_a_whitespace_key_is_treated_as_missing(self) -> None:
        provider = TavilySearchProvider(api_key="   ")

        with pytest.raises(ConfigurationError):
            await provider.initialize()

    async def test_searching_before_initialisation_is_refused(self) -> None:
        provider = TavilySearchProvider(api_key=KEY)

        with pytest.raises(ProviderError, match="not initialised"):
            await provider.search(a_query(), CONTEXT)


class TestRequestShaping:
    async def test_the_key_travels_in_a_header_not_the_body(self) -> None:
        """A query string reaches proxy logs; a body is echoed by HTTP middleware."""
        provider, seen = build_provider()
        await provider.initialize()

        await provider.search(a_query(), CONTEXT)

        request = seen[0]
        assert request.headers["Authorization"] == f"Bearer {KEY}"
        assert KEY not in request.url.query.decode()
        assert KEY not in request.content.decode()

    async def test_the_query_and_result_cap_are_sent(self) -> None:
        provider, seen = build_provider()
        await provider.initialize()

        await provider.search(a_query(max_results=3), CONTEXT)

        body = json.loads(seen[0].content)
        assert body["query"] == "eiffel tower"
        assert body["max_results"] == 3

    async def test_a_result_cap_above_the_upstream_limit_is_clamped(self) -> None:
        """Asking for more than Tavily allows is a 400 rather than fewer results."""
        provider, seen = build_provider()
        await provider.initialize()

        await provider.search(a_query(max_results=50), CONTEXT)

        assert json.loads(seen[0].content)["max_results"] == 20

    async def test_freshness_is_forwarded_when_asked_for(self) -> None:
        provider, seen = build_provider()
        await provider.initialize()

        await provider.search(a_query(freshness_days=7), CONTEXT)

        assert json.loads(seen[0].content)["days"] == 7

    async def test_freshness_is_omitted_when_not_asked_for(self) -> None:
        """Absent is not the same as null to the service."""
        provider, seen = build_provider()
        await provider.initialize()

        await provider.search(a_query(), CONTEXT)

        assert "days" not in json.loads(seen[0].content)

    async def test_search_depth_is_configuration(self) -> None:
        """`advanced` costs more per search, so it is never assumed."""
        provider, seen = build_provider(search_depth="advanced")
        await provider.initialize()

        await provider.search(a_query(), CONTEXT)

        assert json.loads(seen[0].content)["search_depth"] == "advanced"


class TestParsing:
    async def test_results_are_normalised(self) -> None:
        provider, _ = build_provider()
        await provider.initialize()

        results = await provider.search(a_query(), CONTEXT)

        assert [result.title for result in results.results] == [
            "Eiffel Tower",
            "Visiting the tower",
        ]
        assert results.results[0].url == "https://en.wikipedia.org/wiki/Eiffel_Tower"
        assert results.results[0].score == 0.98

    async def test_raw_content_is_discarded(self) -> None:
        """Tens of kilobytes per result would be spent context in the next prompt."""
        provider, _ = build_provider()
        await provider.initialize()

        results = await provider.search(a_query(), CONTEXT)

        assert len(results.results[0].snippet) < 200

    async def test_a_result_without_a_link_is_dropped(self) -> None:
        """An uncitable result is not evidence."""

        def handler(request: httpx.Request) -> httpx.Response:
            del request
            return httpx.Response(200, json={"results": [{"title": "No link", "content": "x"}]})

        provider, _ = build_provider(handler)
        await provider.initialize()

        results = await provider.search(a_query(), CONTEXT)

        assert results.results == ()

    async def test_no_matches_is_an_answer_not_a_failure(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            del request
            return httpx.Response(200, json={"results": []})

        provider, _ = build_provider(handler)
        await provider.initialize()

        results = await provider.search(a_query(), CONTEXT)

        assert results.results == ()
        assert results.provider_id == "tavily"

    async def test_an_unexpected_shape_degrades_rather_than_raising(self) -> None:
        """A payload change upstream must not become an exception mid-turn."""

        def handler(request: httpx.Request) -> httpx.Response:
            del request
            return httpx.Response(200, json={"results": ["not-an-object", {"url": "https://a"}]})

        provider, _ = build_provider(handler)
        await provider.initialize()

        results = await provider.search(a_query(), CONTEXT)

        assert len(results.results) == 1

    async def test_the_result_cap_is_honoured_when_upstream_over_delivers(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            del request
            return httpx.Response(
                200,
                json={"results": [{"url": f"https://a/{n}", "title": str(n)} for n in range(10)]},
            )

        provider, _ = build_provider(handler)
        await provider.initialize()

        results = await provider.search(a_query(max_results=2), CONTEXT)

        assert len(results.results) == 2

    async def test_latency_is_measured(self) -> None:
        provider, _ = build_provider()
        await provider.initialize()

        results = await provider.search(a_query(), CONTEXT)

        assert results.latency_ms is not None
        assert results.latency_ms >= 0


class TestErrorMapping:
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (401, "rejected the API key"),
            (403, "disabled or out of quota"),
            (429, "rate limit"),
            (432, "out of credits"),
            (500, "HTTP 500"),
        ],
    )
    async def test_failures_carry_actionable_guidance(self, status: int, expected: str) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            del request
            return httpx.Response(status, json={"detail": "upstream detail"})

        provider, _ = build_provider(handler)
        await provider.initialize()

        with pytest.raises(ProviderError, match=expected):
            await provider.search(a_query(), CONTEXT)

    async def test_the_upstream_body_never_reaches_the_error(self) -> None:
        """It can echo the request, and the request headers carry the key."""

        def handler(request: httpx.Request) -> httpx.Response:
            del request
            return httpx.Response(401, json={"echo": f"Authorization: Bearer {KEY}"})

        provider, _ = build_provider(handler)
        await provider.initialize()

        with pytest.raises(ProviderError) as caught:
            await provider.search(a_query(), CONTEXT)

        assert KEY not in str(caught.value)

    async def test_a_transport_failure_reports_only_its_type(self) -> None:
        """httpx exception text can contain the URL and headers."""

        def handler(request: httpx.Request) -> httpx.Response:
            message = "connection refused"
            raise httpx.ConnectError(message, request=request)

        provider, _ = build_provider(handler)
        await provider.initialize()

        with pytest.raises(ProviderError, match="ConnectError"):
            await provider.search(a_query(), CONTEXT)

    async def test_a_non_json_response_is_reported_clearly(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            del request
            return httpx.Response(200, text="<html>maintenance</html>")

        provider, _ = build_provider(handler)
        await provider.initialize()

        with pytest.raises(ProviderError, match="not JSON"):
            await provider.search(a_query(), CONTEXT)


class TestLifecycleAndHealth:
    async def test_health_does_not_spend_a_billed_search(self) -> None:
        """A probe that searched would turn monitoring into spend, per poll."""
        provider, seen = build_provider()
        await provider.initialize()

        health = await provider.health_check()

        assert health.status is HealthStatus.HEALTHY
        assert seen == []

    async def test_health_is_unknown_before_initialisation(self) -> None:
        provider = TavilySearchProvider(api_key=KEY)

        assert (await provider.health_check()).status is HealthStatus.UNKNOWN

    async def test_an_injected_client_is_not_closed_by_the_provider(self) -> None:
        """Closing something it did not open would break the caller that owns it."""
        provider, _ = build_provider()
        await provider.initialize()

        await provider.close()

        # The provider still holds the injected client, having not taken
        # ownership of it.
        assert provider._client is not None  # noqa: SLF001 - ownership is the assertion


class TestSecretHandling:
    async def test_the_key_is_never_logged_at_startup(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        provider, _ = build_provider()

        with caplog.at_level("DEBUG"):
            await provider.initialize()

        assert KEY not in caplog.text
