"""Correlation identifier propagation.

``CLAUDE.md`` requires a correlation id per request, propagated through every
layer and present on every log record. These tests pin that contract at the HTTP
boundary and in the log pipeline.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_platform.api.app import create_app
from agent_platform.configuration.settings import PlatformSettings
from agent_platform_shared import (
    CORRELATION_ID_HEADER,
    REQUEST_ID_HEADER,
    correlation_scope,
    get_correlation_id,
    get_request_id,
)

pytestmark = pytest.mark.integration


class TestResponseHeaders:
    """Both ids are echoed so a caller can quote them in a bug report."""

    def test_ids_are_present_on_a_successful_response(self, client: TestClient) -> None:
        response = client.get("/live")

        assert response.headers[CORRELATION_ID_HEADER]
        assert response.headers[REQUEST_ID_HEADER]

    def test_ids_are_present_on_an_error_response(self, client: TestClient) -> None:
        """The failing case is precisely when the id matters most."""
        response = client.get("/no-such-route")

        assert response.status_code == 404
        assert response.headers[CORRELATION_ID_HEADER]

    def test_inbound_correlation_id_is_honoured(self, client: TestClient) -> None:
        """An upstream trace must continue rather than fragment in two."""
        supplied = "upstream-correlation-id-1234"

        response = client.get("/live", headers={CORRELATION_ID_HEADER: supplied})

        assert response.headers[CORRELATION_ID_HEADER] == supplied

    def test_request_id_is_always_generated_locally(self, client: TestClient) -> None:
        """A client-supplied request id cannot be trusted to be unique."""
        supplied = "client-supplied-request-id"

        response = client.get("/live", headers={REQUEST_ID_HEADER: supplied})

        assert response.headers[REQUEST_ID_HEADER] != supplied

    def test_each_request_gets_a_distinct_correlation_id(self, client: TestClient) -> None:
        first = client.get("/live").headers[CORRELATION_ID_HEADER]
        second = client.get("/live").headers[CORRELATION_ID_HEADER]

        assert first != second

    @pytest.mark.parametrize("supplied", ["", "   "])
    def test_blank_inbound_id_is_replaced(self, client: TestClient, supplied: str) -> None:
        response = client.get("/live", headers={CORRELATION_ID_HEADER: supplied})

        assert response.headers[CORRELATION_ID_HEADER].strip()

    def test_over_long_inbound_id_is_replaced_not_rejected(self, client: TestClient) -> None:
        """Unbounded client input would flow into every log record for the request.

        Rejecting the request would turn a caller's cosmetic mistake into an
        outage, so the id is replaced instead.
        """
        oversized = "x" * 5000

        response = client.get("/live", headers={CORRELATION_ID_HEADER: oversized})

        assert response.status_code == 200
        assert response.headers[CORRELATION_ID_HEADER] != oversized
        assert len(response.headers[CORRELATION_ID_HEADER]) < 200


class TestCorsExposure:
    """Browsers hide non-safelisted headers from scripts unless exposed."""

    def test_correlation_headers_are_exposed_to_the_browser(self, client: TestClient) -> None:
        response = client.get("/live", headers={"Origin": "http://localhost:5173"})

        exposed = response.headers.get("access-control-expose-headers", "")
        assert CORRELATION_ID_HEADER in exposed
        assert REQUEST_ID_HEADER in exposed


class TestLogEnrichment:
    """Every record must carry the ids without any call site passing them."""

    def test_access_log_record_carries_both_ids(
        self, client: TestClient, capsys: pytest.CaptureFixture[str]
    ) -> None:
        response = client.get("/api/v1/info")
        correlation_id = response.headers[CORRELATION_ID_HEADER]

        records = [
            json.loads(line)
            for line in capsys.readouterr().out.splitlines()
            if line.startswith("{")
        ]
        access_records = [r for r in records if r.get("event") == "http.request_completed"]

        assert access_records, "expected an access log record"
        assert access_records[-1]["correlation_id"] == correlation_id
        assert access_records[-1]["request_id"] == response.headers[REQUEST_ID_HEADER]

    def test_health_probes_are_not_access_logged(
        self, client: TestClient, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Orchestrators probe every few seconds; logging that buries real traffic."""
        capsys.readouterr()

        client.get("/live")
        client.get("/ready")

        output = capsys.readouterr().out
        assert "http.request_completed" not in output


class TestContextPropagation:
    """The ids must survive the async boundaries the platform is built on."""

    async def test_ids_survive_an_await(self) -> None:
        with correlation_scope(correlation_id="corr-1", request_id="req-1"):
            await asyncio.sleep(0)

            assert get_correlation_id() == "corr-1"
            assert get_request_id() == "req-1"

    async def test_ids_are_inherited_by_a_spawned_task(self) -> None:
        """`asyncio.create_task` copies the context, so tool and provider calls inherit it."""
        captured: list[str | None] = []

        async def child() -> None:
            captured.append(get_correlation_id())

        with correlation_scope(correlation_id="corr-2"):
            await asyncio.create_task(child())

        assert captured == ["corr-2"]

    def test_scope_restores_the_previous_value(self) -> None:
        """Without restoration, an id leaks into the next unit of work on the same worker."""
        with correlation_scope(correlation_id="outer"):
            with correlation_scope(correlation_id="inner"):
                assert get_correlation_id() == "inner"
            assert get_correlation_id() == "outer"

        assert get_correlation_id() is None

    def test_scope_restores_even_when_the_body_raises(self) -> None:
        def _fail_inside_scope() -> None:
            with correlation_scope(correlation_id="doomed"):
                message = "boom"
                raise RuntimeError(message)

        with pytest.raises(RuntimeError):
            _fail_inside_scope()

        assert get_correlation_id() is None

    def test_partial_scope_leaves_the_other_id_untouched(self) -> None:
        with correlation_scope(correlation_id="corr-3"):
            with correlation_scope(request_id="req-3"):
                assert get_correlation_id() == "corr-3"
                assert get_request_id() == "req-3"

            assert get_correlation_id() == "corr-3"
            assert get_request_id() is None


class TestIsolationBetweenApplications:
    """Each application resolves from its own container, never a module global."""

    def test_two_apps_do_not_share_a_container(
        self, app: FastAPI, test_settings: PlatformSettings
    ) -> None:
        other = create_app(test_settings)

        assert app.state.container is not other.state.container
