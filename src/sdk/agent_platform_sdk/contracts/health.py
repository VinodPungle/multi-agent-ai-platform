"""Health reporting contracts.

``CLAUDE.md`` requires every provider to expose ready / live / healthy state and
the runtime to avoid unhealthy providers. A single shared shape lets the API
aggregate heterogeneous components without knowing what any of them are.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from agent_platform_sdk.types.enums import HealthStatus

__all__ = ["ComponentHealth", "HealthReport"]


class ComponentHealth(BaseModel):
    """Health of one named component."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(description="Stable component identifier, e.g. 'configuration'.")
    status: HealthStatus = Field(description="Current status of the component.")
    detail: str | None = Field(
        default=None,
        description=(
            "Operator-facing explanation. Must never contain secrets, credentials or "
            "user data — this value is returned over HTTP."
        ),
    )
    latency_ms: float | None = Field(
        default=None,
        ge=0,
        description="Time the health probe itself took, to spot slow dependencies.",
    )


class HealthReport(BaseModel):
    """Aggregated health of the platform."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: HealthStatus = Field(description="Worst status across all components.")
    components: tuple[ComponentHealth, ...] = Field(
        default=(),
        description="Individual component results, in registration order.",
    )

    @classmethod
    def from_components(cls, components: tuple[ComponentHealth, ...]) -> HealthReport:
        """Aggregate component results into a single report.

        The overall status is the worst individual status: one unhealthy
        dependency makes the platform unhealthy even if everything else is fine.
        An empty component set reports ``HEALTHY`` — there is nothing failing.
        """
        severity = {
            HealthStatus.HEALTHY: 0,
            HealthStatus.UNKNOWN: 1,
            HealthStatus.DEGRADED: 2,
            HealthStatus.UNHEALTHY: 3,
        }
        worst = max(
            (component.status for component in components),
            key=lambda status: severity[status],
            default=HealthStatus.HEALTHY,
        )
        return cls(status=worst, components=components)
