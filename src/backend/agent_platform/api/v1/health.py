"""Health, liveness and readiness endpoints.

Three endpoints because container orchestrators need three different answers,
and conflating them causes real outages:

``/live``
    Is the process alive? Never touches a dependency. A liveness probe that
    checks dependencies will restart a healthy container because a *downstream*
    service is down — turning one outage into two.
``/ready``
    Can this instance serve traffic? Probes registered components. A failure
    removes the instance from the load balancer without restarting it, so it
    can rejoin when the dependency recovers.
``/health``
    Human- and monitor-facing detail: per-component status and probe latency.

These are mounted at the application root, not under ``/api/v1``. Probes are
infrastructure concerns and must not move when the API is versioned.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, ConfigDict, Field

from agent_platform.dependencies.providers import HealthServiceDep, SettingsDep
from agent_platform_sdk.contracts.health import HealthReport
from agent_platform_sdk.types.enums import HealthStatus

__all__ = ["LivenessResponse", "ReadinessResponse", "router"]

router = APIRouter(tags=["health"])


class LivenessResponse(BaseModel):
    """Response of the liveness probe."""

    model_config = ConfigDict(frozen=True)

    status: str = Field(description="Always 'alive' when the process can respond.")


class ReadinessResponse(BaseModel):
    """Response of the readiness probe."""

    model_config = ConfigDict(frozen=True)

    status: HealthStatus = Field(description="Aggregated status across all components.")
    ready: bool = Field(description="Whether this instance should receive traffic.")


class HealthResponse(BaseModel):
    """Detailed health response for operators and monitoring."""

    model_config = ConfigDict(frozen=True)

    status: HealthStatus
    name: str = Field(description="Platform name.")
    version: str = Field(description="Running application version.")
    environment: str = Field(description="Declared deployment environment.")
    report: HealthReport = Field(description="Per-component detail.")


@router.get(
    "/live",
    response_model=LivenessResponse,
    summary="Liveness probe",
    description=(
        "Returns 200 whenever the process can serve a request. Performs no dependency "
        "checks, so a downstream outage never causes a container restart."
    ),
)
async def live() -> LivenessResponse:
    """Report that the process is running."""
    return LivenessResponse(status="alive")


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "One or more components are unhealthy; do not route traffic here."
        }
    },
)
async def ready(health_service: HealthServiceDep, response: Response) -> ReadinessResponse:
    """Report whether this instance should receive traffic.

    ``DEGRADED`` still reports ready: a partially functioning instance serving
    traffic is better than no instance, and the degradation is visible on
    ``/health`` and in the logs.
    """
    report = await health_service.check()
    is_ready = report.status is not HealthStatus.UNHEALTHY

    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(status=report.status, ready=is_ready)


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Detailed health report",
    description=(
        "Per-component status and probe latency. Always returns 200 — the payload "
        "carries the verdict, so a monitoring system can distinguish 'the platform "
        "reports itself unhealthy' from 'the platform did not answer'."
    ),
)
async def health(
    health_service: HealthServiceDep,
    settings: SettingsDep,
) -> HealthResponse:
    """Return detailed per-component health."""
    report = await health_service.check()
    return HealthResponse(
        status=report.status,
        name=settings.app.name,
        version=settings.app.version,
        environment=settings.app.environment.value,
        report=report,
    )
