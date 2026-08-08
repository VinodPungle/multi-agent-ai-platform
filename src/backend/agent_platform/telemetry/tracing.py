"""OpenTelemetry bootstrap.

``CLAUDE.md`` requires every request to be observable and every significant
action traceable. This module configures a tracer provider once at startup and
tears it down cleanly on shutdown.

Exporters are additive and entirely configuration-driven:

* **OTLP/HTTP** — the vendor-neutral path. Configure ``telemetry.otlp_endpoint``
  to reach a local collector, Jaeger, Grafana Tempo, or Azure Monitor via a
  collector.
* **Console** — prints spans to stdout for local inspection.

Nothing here imports an Azure SDK. The Application Insights connection string is
accepted in configuration and exported through a collector, so the observability
path stays portable across clouds — see
``docs/adr/0005-opentelemetry-first-observability.md``.
"""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from opentelemetry.trace import Tracer

from agent_platform.configuration.settings import AppSettings, TelemetrySettings
from agent_platform.telemetry.logging import get_logger

__all__ = ["configure_tracing", "get_tracer", "shutdown_tracing"]

_logger = get_logger(__name__)

# Held at module scope so shutdown can flush the exact provider that startup
# installed, rather than whatever happens to be global at the time.
_tracer_provider: TracerProvider | None = None


def _build_resource(app: AppSettings, telemetry: TelemetrySettings) -> Resource:
    """Describe this service to the tracing backend.

    Resource attributes are what let a backend group spans by service and
    environment; without them every replica looks like an anonymous producer.
    """
    return Resource.create(
        {
            "service.name": telemetry.service_name,
            "service.version": app.version,
            "service.namespace": app.name,
            "deployment.environment": app.environment.value,
        }
    )


def configure_tracing(app: AppSettings, telemetry: TelemetrySettings) -> None:
    """Install the global tracer provider.

    Does nothing when ``telemetry.enabled`` is false — the OpenTelemetry API
    then returns no-op spans, so instrumentation throughout the codebase stays
    valid and costs nothing.

    Args:
        app: Application identity, used for resource attributes.
        telemetry: Validated telemetry configuration.
    """
    global _tracer_provider  # noqa: PLW0603 - one process-wide provider by design

    if not telemetry.enabled:
        _logger.info("tracing.disabled", reason="telemetry.enabled is false")
        return

    if _tracer_provider is not None:
        _logger.debug("tracing.already_configured")
        return

    provider = TracerProvider(
        resource=_build_resource(app, telemetry),
        # ParentBased keeps a trace intact: once an upstream service decides to
        # sample a request, every downstream span is kept too. Sampling each
        # span independently produces traces with holes in them.
        sampler=ParentBased(root=TraceIdRatioBased(telemetry.sample_ratio)),
    )

    exporters_configured = 0

    if telemetry.otlp_endpoint:
        provider.add_span_processor(
            # Batching keeps export off the request path. The alternative costs
            # a network round trip per span inside the response.
            BatchSpanProcessor(
                OTLPSpanExporter(endpoint=f"{telemetry.otlp_endpoint.rstrip('/')}/v1/traces")
            )
        )
        exporters_configured += 1

    if telemetry.console_exporter:
        # Simple, not batched: local debugging wants spans printed as they end,
        # not up to five seconds later.
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
        exporters_configured += 1

    trace.set_tracer_provider(provider)
    _tracer_provider = provider

    if exporters_configured == 0:
        # Deliberately not an error. Spans are still created and still correlate
        # log records, which is useful on a developer machine with no collector.
        _logger.info(
            "tracing.configured_without_exporter",
            detail="No OTLP endpoint or console exporter set; spans are created but not exported.",
            service_name=telemetry.service_name,
        )
    else:
        _logger.info(
            "tracing.configured",
            service_name=telemetry.service_name,
            exporters=exporters_configured,
            sample_ratio=telemetry.sample_ratio,
        )


def shutdown_tracing() -> None:
    """Flush and shut down the tracer provider.

    Called during graceful shutdown. Without this, spans sitting in the batch
    processor's queue are lost — which is precisely the traffic around a
    restart, the traffic an operator most wants to see.
    """
    global _tracer_provider  # noqa: PLW0603 - mirrors configure_tracing

    if _tracer_provider is None:
        return

    _tracer_provider.shutdown()
    _tracer_provider = None
    _logger.info("tracing.shutdown")


def get_tracer(name: str) -> Tracer:
    """Return a tracer for ``name``.

    Safe to call before :func:`configure_tracing`: the API returns a no-op
    tracer until a provider is installed, so module-level tracer creation never
    depends on import order.
    """
    return trace.get_tracer(name)
