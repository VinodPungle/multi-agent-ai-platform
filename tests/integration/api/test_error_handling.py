"""Centralised error handling.

Pins the two guarantees ``CLAUDE.md`` states outright: every error uses one
envelope, and no stack trace or internal detail ever reaches a client.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_platform.configuration.settings import PlatformSettings
from agent_platform.exceptions.base import (
    ConfigurationError,
    NotFoundError,
    PlatformError,
    PlatformTimeoutError,
    PolicyViolationError,
    ProviderError,
    ValidationError,
)
from agent_platform_sdk.types.enums import ErrorCategory

pytestmark = pytest.mark.integration

#: A phrase a real failure might carry that must never cross the boundary.
SECRET_FRAGMENT = "AccountKey=super-secret-value"  # noqa: S105


@pytest.fixture
def failing_app(app: FastAPI) -> FastAPI:
    """Register routes that raise, so the handlers can be exercised end to end."""

    @app.get("/test/platform-error")
    async def _platform_error() -> None:
        raise NotFoundError("Agent 'unknown-agent' is not registered")

    @app.get("/test/provider-error")
    async def _provider_error() -> None:
        raise ProviderError(
            "The model provider is unavailable",
            provider_id="azure-foundry",
            details={"endpoint": SECRET_FRAGMENT},
        )

    @app.get("/test/unexpected-error")
    async def _unexpected_error() -> None:
        raise RuntimeError(SECRET_FRAGMENT)

    @app.get("/test/validated")
    async def _validated(temperature: float = 0.0) -> dict[str, float]:
        return {"temperature": temperature}

    return app


@pytest.fixture
def failing_client(failing_app: FastAPI) -> TestClient:
    # `raise_server_exceptions=False` makes the client behave like a real
    # server: the handler converts the exception rather than re-raising it
    # into the test, which is the behaviour under test.
    return TestClient(failing_app, raise_server_exceptions=False)


class TestEnvelope:
    """One shape for every failure, so clients need one parser."""

    def test_platform_error_uses_the_standard_envelope(self, failing_client: TestClient) -> None:
        response = failing_client.get("/test/platform-error")

        assert response.status_code == 404
        error = response.json()["error"]
        assert error["category"] == ErrorCategory.NOT_FOUND.value
        assert error["message"] == "Agent 'unknown-agent' is not registered"
        assert error["correlation_id"]

    def test_correlation_id_in_the_body_matches_the_header(
        self, failing_client: TestClient
    ) -> None:
        """This is what makes a user's bug report searchable."""
        response = failing_client.get("/test/platform-error")

        assert response.json()["error"]["correlation_id"] == response.headers["X-Correlation-ID"]

    def test_starlette_404_uses_the_same_envelope(self, failing_client: TestClient) -> None:
        """A framework 404 must not look different from ours."""
        error = failing_client.get("/no-such-route").json()["error"]

        assert error["category"] == ErrorCategory.NOT_FOUND.value

    def test_request_validation_failure_reports_fields(self, failing_client: TestClient) -> None:
        response = failing_client.get("/test/validated", params={"temperature": "hot"})

        assert response.status_code == 422
        error = response.json()["error"]
        assert error["category"] == ErrorCategory.VALIDATION.value
        assert error["fields"], "field-level detail should be present"
        assert "temperature" in error["fields"][0]["location"]


class TestInformationDisclosure:
    """Nothing internal may cross the network boundary."""

    def test_unexpected_exception_returns_an_opaque_message(
        self, failing_client: TestClient
    ) -> None:
        response = failing_client.get("/test/unexpected-error")

        assert response.status_code == 500
        assert SECRET_FRAGMENT not in response.text
        assert "RuntimeError" not in response.text
        assert "Traceback" not in response.text

    def test_provider_error_details_are_logged_but_not_returned(
        self, failing_client: TestClient
    ) -> None:
        """`details` is diagnostic context for logs, never part of the response."""
        response = failing_client.get("/test/provider-error")

        assert response.status_code == 502
        assert response.json()["error"]["message"] == "The model provider is unavailable"
        assert SECRET_FRAGMENT not in response.text

    def test_unexpected_failure_is_logged_with_its_traceback(
        self, failing_client: TestClient, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Hidden from the client, but never lost."""
        failing_client.get("/test/unexpected-error")

        output = capsys.readouterr().out
        assert "api.unhandled_exception" in output
        assert "RuntimeError" in output


class TestStatusMapping:
    """Category drives status, so a new exception type needs no handler change."""

    @pytest.mark.parametrize(
        ("error", "expected_status"),
        [
            (ValidationError("bad input"), 422),
            (NotFoundError("missing"), 404),
            (PolicyViolationError("over budget"), 403),
            (PlatformTimeoutError("too slow"), 504),
            (ProviderError("upstream down"), 502),
            (ConfigurationError("misconfigured"), 500),
        ],
    )
    def test_category_maps_to_status(
        self,
        app: FastAPI,
        error: PlatformError,
        expected_status: int,
    ) -> None:
        @app.get("/test/mapped")
        async def _mapped() -> None:
            raise error

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/test/mapped")

        assert response.status_code == expected_status
        assert response.json()["error"]["category"] == error.category.value


class TestApiDocumentationExposure:
    """Docs describe the attack surface and are withdrawn with debug mode."""

    def test_docs_are_available_in_debug_mode(self, client: TestClient) -> None:
        assert client.get("/docs").status_code == 200
        assert client.get("/openapi.json").status_code == 200

    def test_docs_are_withdrawn_when_debug_is_off(self, test_settings: PlatformSettings) -> None:
        from agent_platform.api.app import create_app

        production_like = test_settings.model_copy(
            update={"app": test_settings.app.model_copy(update={"debug": False})}
        )

        with TestClient(create_app(production_like)) as client:
            assert client.get("/docs").status_code == 404
            assert client.get("/openapi.json").status_code == 404
