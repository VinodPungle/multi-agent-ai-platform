# ADR-0005: OpenTelemetry-first observability, with Azure reached through a collector

- **Status:** Accepted
- **Date:** 2026-08-08
- **Milestone:** 01 — Repository Foundation

## Context

`CLAUDE.md` requires every request to be observable and every significant action
traceable, using OpenTelemetry, Application Insights, correlation IDs,
distributed tracing, metrics and structured logs. It also states that Azure is
the primary cloud but the platform must remain cloud-portable, and that
infrastructure must never leak into business logic.

Those two pull in different directions for telemetry specifically. The most
direct route to Application Insights is the `azure-monitor-opentelemetry`
distribution, which auto-configures exporters from a connection string. It is
also an Azure SDK dependency compiled into the application — in the one
cross-cutting concern that touches every module.

A second problem is joining logs to traces. Without a shared identifier, an
operator holding a log line has no way to reach the trace that produced it, and
the distributed tracing requirement is only half met.

## Decision

**Instrument with the vendor-neutral OpenTelemetry API and SDK only.** The
backend depends on `opentelemetry-api`, `opentelemetry-sdk`, the OTLP/HTTP
exporter and the FastAPI instrumentation. No Azure SDK is imported for
telemetry.

**Reach Azure Monitor through an OpenTelemetry Collector**, configured by
`telemetry.otlp_endpoint`. The connection string is accepted in configuration
(`telemetry.azure_monitor_connection_string`, marked `repr=False`) and consumed
by the collector, not by application code.

**Join logs to traces in the log pipeline.** A structlog processor injects the
active `trace_id` and `span_id` into every record; another injects the ambient
correlation and request IDs from `contextvars`. No call site passes them.

**Telemetry is optional and degrades quietly.** With `telemetry.enabled=false`,
the OpenTelemetry API returns no-op spans, so instrumentation throughout the
codebase stays valid and costs nothing. With tracing enabled but no exporter
configured — the normal state on a developer machine — spans are still created
and still correlate log records; this is logged as information, not an error.

**Health probes are excluded** from both tracing and access logging. Container
platforms probe every few seconds; including them would bury real traffic and
cost real money in ingestion.

## Alternatives Considered

### `azure-monitor-opentelemetry` in the application

**Rejected because:** it compiles a cloud SDK into the one concern that touches
every module. Moving to another cloud, or to Grafana Tempo, would then mean
changing telemetry bootstrap in the application rather than changing one
collector configuration. It is also the exact coupling `CLAUDE.md` prohibits —
provider SDKs belong in the infrastructure layer.

The cost of rejecting it is real: some Application Insights features
(Live Metrics, the application map) work best with the native distribution. If
those turn out to matter in Milestone 08, the collector can be swapped for the
Azure exporter behind the same `configure_tracing` seam, changing one module.

### The Application Insights SDK directly, without OpenTelemetry

**Rejected because:** it is on a deprecation path in favour of OpenTelemetry, and
it would put a vendor API at every instrumentation point rather than at one
exporter.

### Standard-library `logging` with a JSON formatter

**Rejected because:** the handbook mandates structlog, and the processor chain is
what makes automatic correlation and trace-context enrichment possible. With a
formatter, every call site would have to remember to pass the IDs — and the one
that forgets is the one that logs the failure you are trying to diagnose.

### Tracing always on, failing hard when no exporter is configured

**Rejected because:** a developer machine has no collector. Making that an error
would train everyone to disable telemetry locally, which is precisely when
instrumentation bugs should be caught.

## Consequences

### Positive

- No cloud SDK in the telemetry path; moving backends is a collector change.
- Every log record carries `correlation_id`, `request_id`, `trace_id` and
  `span_id` automatically, so an operator can pivot from a log line to its trace.
- Records emitted by uvicorn and third-party libraries flow through the same
  processor chain, so the whole stream has one shape.
- The API client surfaces the correlation ID in user-facing errors, closing the
  loop from a user's report to a server-side trace.
- Telemetry costs nothing when disabled.

### Negative

- A collector is an extra component to deploy and operate in Azure. Milestone 06
  must provision it; until then, Azure telemetry is not wired end to end.
- Some Application Insights features work best with the native distribution.
- The `_CurrentStdoutHandler` resolving `sys.stdout` per record is a small
  deviation from `logging.StreamHandler`, needed because the standard handler
  binds the stream at construction and outlives any later redirection.

### Neutral

- `ParentBased(TraceIdRatioBased(...))` sampling keeps traces intact: once an
  upstream service samples a request, downstream spans are kept too. Sampling
  each span independently would produce traces with holes.
- The tracer provider is process-global, which the OpenTelemetry SDK enforces.
  Tests reset it explicitly.

## Compliance

- `tests/unit/telemetry/test_logging.py` asserts correlation enrichment, JSON
  rendering, level filtering, exception rendering and that reconfiguring does not
  duplicate records.
- `tests/unit/telemetry/test_tracing.py` asserts resource attributes, span
  recording, nested trace IDs and clean shutdown.
- `tests/integration/api/test_correlation.py` asserts end-to-end propagation and
  that health probes are not access-logged.
- Ruff's `T20` rule bans `print()`.

## References

- `CLAUDE.md` — Observability, Correlation, Logging Standards, Metrics
- `architecture.md` §57 — Observability Flow, §58 — Logging Pipeline, §59 — Metrics Pipeline
- `docs/engineering-handbook.md` — Logging, OpenTelemetry
