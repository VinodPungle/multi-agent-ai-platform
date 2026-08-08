"""Health, readiness and liveness endpoints.

Milestone 01 acceptance criteria: "Backend health endpoints respond
successfully" and "Health endpoint returns HTTP 200".

These run through the real application — middleware, dependency injection, error
handling and routing included — because that wiring is exactly what the milestone
delivers, and a test that bypasses it would prove nothing about it.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_platform.application.health_service import HealthService
from agent_platform.configuration.settings import PlatformSettings
from agent_platform_sdk.contracts.health import ComponentHealth, HealthReport
from agent_platform_sdk.types.enums import Capability, HealthStatus

pytestmark = pytest.mark.integration


class StubProvider:
    """A provider whose health result the test controls.

    Structurally satisfies ``Provider`` without inheriting from it, which is the
    property protocol-based contracts exist to give us.
    """

    def __init__(self, provider_id: str, status: HealthStatus, *, raises: bool = False) -> None:
        self._provider_id = provider_id
        self._status = status
        self._raises = raises

    @property
    def provider_id(self) -> str:
        return self._provider_id

    async def initialize(self) -> None:
        return None

    async def health_check(self) -> ComponentHealth:
        if self._raises:
            message = "connection refused to https://internal.example/secret-path"
            raise RuntimeError(message)
        return ComponentHealth(name=self._provider_id, status=self._status)

    def supports(self, capability: Capability) -> bool:
        return False

    async def close(self) -> None:
        return None


def _client_with_providers(
    app: FastAPI,
    settings: PlatformSettings,
    *providers: StubProvider,
) -> TestClient:
    """Return a client whose health service probes ``providers``.

    Overriding the container provider — rather than the FastAPI dependency —
    proves the container is genuinely the composition root: swapping one
    registration changes what the endpoint reports.
    """
    container = app.state.container
    container.health_service.override(
        HealthService(
            settings=settings,
            clock=container.clock(),
            providers=tuple(providers),
        )
    )
    return TestClient(app)


class TestLiveness:
    """Liveness answers one question: is the process running?"""

    def test_returns_200_and_alive(self, client: TestClient) -> None:
        response = client.get("/live")

        assert response.status_code == 200
        assert response.json() == {"status": "alive"}

    def test_stays_alive_when_a_dependency_is_unhealthy(
        self, app: FastAPI, test_settings: PlatformSettings
    ) -> None:
        """A liveness probe must not restart a container over a downstream outage.

        Restarting on a dependency failure turns one outage into two.
        """
        with _client_with_providers(
            app,
            test_settings,
            StubProvider("broken-provider", HealthStatus.UNHEALTHY),
        ) as client:
            assert client.get("/live").status_code == 200


class TestReadiness:
    """Readiness decides whether this instance should receive traffic."""

    def test_ready_when_no_providers_are_registered(self, client: TestClient) -> None:
        """Milestone 01 registers no providers; the platform is still ready."""
        response = client.get("/ready")

        assert response.status_code == 200
        assert response.json() == {"status": "healthy", "ready": True}

    def test_returns_503_when_a_provider_is_unhealthy(
        self, app: FastAPI, test_settings: PlatformSettings
    ) -> None:
        with _client_with_providers(
            app,
            test_settings,
            StubProvider("failing-provider", HealthStatus.UNHEALTHY),
        ) as client:
            response = client.get("/ready")

        assert response.status_code == 503
        assert response.json()["ready"] is False

    def test_degraded_instance_still_receives_traffic(
        self, app: FastAPI, test_settings: PlatformSettings
    ) -> None:
        """A partially working instance beats no instance.

        The degradation stays visible on ``/health`` and in the logs.
        """
        with _client_with_providers(
            app,
            test_settings,
            StubProvider("slow-provider", HealthStatus.DEGRADED),
        ) as client:
            response = client.get("/ready")

        assert response.status_code == 200
        assert response.json() == {"status": "degraded", "ready": True}


class TestHealthReport:
    """The detailed report is what an operator reads during an incident."""

    def test_returns_identity_and_component_detail(self, client: TestClient) -> None:
        response = client.get("/health")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "healthy"
        assert body["name"] == "test-platform"
        assert body["version"] == "0.0.0-test"
        assert body["environment"] == "testing"

        component_names = {component["name"] for component in body["report"]["components"]}
        assert "configuration" in component_names

    def test_returns_200_even_when_unhealthy(
        self, app: FastAPI, test_settings: PlatformSettings
    ) -> None:
        """The payload carries the verdict, so 'unhealthy' and 'unreachable' stay distinguishable."""
        with _client_with_providers(
            app,
            test_settings,
            StubProvider("failing-provider", HealthStatus.UNHEALTHY),
        ) as client:
            response = client.get("/health")

        assert response.status_code == 200
        assert response.json()["status"] == "unhealthy"

    def test_a_raising_provider_is_reported_not_propagated(
        self, app: FastAPI, test_settings: PlatformSettings
    ) -> None:
        """One broken dependency must not break the endpoint that reports it."""
        with _client_with_providers(
            app,
            test_settings,
            StubProvider("exploding-provider", HealthStatus.HEALTHY, raises=True),
        ) as client:
            response = client.get("/health")

        assert response.status_code == 200
        components = {c["name"]: c for c in response.json()["report"]["components"]}
        assert components["exploding-provider"]["status"] == "unhealthy"

    def test_provider_failure_detail_excludes_the_exception_message(
        self, app: FastAPI, test_settings: PlatformSettings
    ) -> None:
        """An exception message can carry an endpoint or credential fragment.

        Only the exception *type* crosses the network boundary.
        """
        with _client_with_providers(
            app,
            test_settings,
            StubProvider("exploding-provider", HealthStatus.HEALTHY, raises=True),
        ) as client:
            response = client.get("/health")

        body = response.text
        assert "RuntimeError" in body
        assert "secret-path" not in body
        assert "internal.example" not in body

    def test_worst_component_status_wins(
        self, app: FastAPI, test_settings: PlatformSettings
    ) -> None:
        with _client_with_providers(
            app,
            test_settings,
            StubProvider("healthy-provider", HealthStatus.HEALTHY),
            StubProvider("degraded-provider", HealthStatus.DEGRADED),
            StubProvider("unhealthy-provider", HealthStatus.UNHEALTHY),
        ) as client:
            response = client.get("/health")

        assert response.json()["status"] == "unhealthy"

    def test_probe_latency_is_recorded(self, client: TestClient) -> None:
        """Latency is what identifies a slow dependency before it becomes an outage."""
        components = client.get("/health").json()["report"]["components"]

        assert all("latency_ms" in component for component in components)


class TestHealthReportAggregation:
    """Aggregation is pure logic and is worth testing without HTTP."""

    @pytest.mark.parametrize(
        ("statuses", "expected"),
        [
            ((), HealthStatus.HEALTHY),
            ((HealthStatus.HEALTHY,), HealthStatus.HEALTHY),
            ((HealthStatus.HEALTHY, HealthStatus.UNKNOWN), HealthStatus.UNKNOWN),
            ((HealthStatus.UNKNOWN, HealthStatus.DEGRADED), HealthStatus.DEGRADED),
            ((HealthStatus.DEGRADED, HealthStatus.UNHEALTHY), HealthStatus.UNHEALTHY),
            ((HealthStatus.UNHEALTHY, HealthStatus.HEALTHY), HealthStatus.UNHEALTHY),
        ],
    )
    def test_worst_status_wins(
        self, statuses: tuple[HealthStatus, ...], expected: HealthStatus
    ) -> None:
        components = tuple(
            ComponentHealth(name=f"component-{index}", status=status)
            for index, status in enumerate(statuses)
        )

        assert HealthReport.from_components(components).status is expected
