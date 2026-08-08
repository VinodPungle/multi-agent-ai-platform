"""Health aggregation use case.

Answers "is this instance fit to serve traffic?" by probing each registered
component and combining the results.

The service depends on the SDK's ``Provider`` protocol, never on a concrete
provider. When Milestone 05 registers an Azure AI Foundry provider, that
provider becomes probeable here without this file changing.
"""

from __future__ import annotations

from agent_platform.configuration.settings import PlatformSettings
from agent_platform.telemetry.logging import get_logger
from agent_platform.telemetry.tracing import get_tracer
from agent_platform_sdk.contracts.health import ComponentHealth, HealthReport
from agent_platform_sdk.interfaces.provider import Provider
from agent_platform_sdk.types.enums import HealthStatus
from agent_platform_shared.clock import Clock

__all__ = ["HealthService"]

_logger = get_logger(__name__)
_tracer = get_tracer(__name__)


class HealthService:
    """Aggregates the health of every registered platform component."""

    def __init__(
        self,
        settings: PlatformSettings,
        clock: Clock,
        providers: tuple[Provider, ...] = (),
    ) -> None:
        """Create the service.

        Args:
            settings: Validated platform configuration.
            clock: Injected time source, used to measure probe latency.
            providers: Components to probe. Empty in Milestone 01 — no provider
                is registered yet — and populated by the container as later
                milestones add providers.
        """
        self._settings = settings
        self._clock = clock
        self._providers = providers

    async def check(self) -> HealthReport:
        """Probe every registered component and return an aggregated report.

        A provider that raises is reported ``UNHEALTHY`` rather than allowed to
        propagate: one broken dependency must not take down the endpoint that
        exists to tell operators which dependency is broken.
        """
        with _tracer.start_as_current_span("health.check") as span:
            components: list[ComponentHealth] = [self._configuration_health()]

            for provider in self._providers:
                components.append(await self._probe(provider))

            report = HealthReport.from_components(tuple(components))
            span.set_attribute("health.status", report.status.value)
            span.set_attribute("health.component_count", len(components))

            if report.status is not HealthStatus.HEALTHY:
                _logger.warning(
                    "health.degraded",
                    status=report.status.value,
                    unhealthy=[
                        component.name
                        for component in report.components
                        if component.status is not HealthStatus.HEALTHY
                    ],
                )

            return report

    def _configuration_health(self) -> ComponentHealth:
        """Report configuration health.

        Always healthy by construction: settings are validated before the
        application starts, so an invalid configuration means this code is never
        reached. It is reported anyway so that the readiness payload always names
        the environment an instance believes it is running in — the single most
        useful field when diagnosing a misrouted deployment.
        """
        return ComponentHealth(
            name="configuration",
            status=HealthStatus.HEALTHY,
            detail=f"environment={self._settings.app.environment.value}",
        )

    async def _probe(self, provider: Provider) -> ComponentHealth:
        """Probe a single provider, converting any failure into a health result."""
        started = self._clock.monotonic()
        try:
            health = await provider.health_check()
        # Deliberately blind: a probe may fail in any way a provider's transport
        # can fail, and every one of those is a health result rather than a crash.
        except Exception as error:
            elapsed_ms = (self._clock.monotonic() - started) * 1000
            _logger.warning(
                "health.probe_failed",
                provider_id=provider.provider_id,
                error_type=type(error).__name__,
                exc_info=True,
            )
            return ComponentHealth(
                name=provider.provider_id,
                status=HealthStatus.UNHEALTHY,
                # The exception type only — a message could carry an endpoint or
                # credential fragment, and this value is returned over HTTP.
                detail=f"health check raised {type(error).__name__}",
                latency_ms=elapsed_ms,
            )

        if health.latency_ms is None:
            elapsed_ms = (self._clock.monotonic() - started) * 1000
            return health.model_copy(update={"latency_ms": elapsed_ms})
        return health
