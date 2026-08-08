"""OpenTelemetry bootstrap.

Milestone 01 acceptance criterion: "Logging and tracing initialize successfully".

The OpenTelemetry SDK installs a *global* tracer provider and refuses to replace
one, so each test tears down what it installed. Without that, test order would
decide the outcome.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

from agent_platform.configuration.settings import AppSettings, TelemetrySettings
from agent_platform.telemetry import tracing

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_global_tracer_state() -> Iterator[None]:
    """Restore global tracing state around every test."""
    tracing.shutdown_tracing()
    yield
    tracing.shutdown_tracing()
    # The SDK guards against a second `set_tracer_provider`; clearing the
    # internal flag is the only way to leave a clean slate for the next test.
    trace._TRACER_PROVIDER = None  # noqa: SLF001 - no public reset exists
    trace._TRACER_PROVIDER_SET_ONCE._done = False  # noqa: SLF001 - same reason


@pytest.fixture
def app_settings() -> AppSettings:
    return AppSettings(name="test-platform", version="9.9.9")


class TestConfiguration:
    """Tracing must initialise without a collector present."""

    def test_provider_is_installed_when_enabled(self, app_settings: AppSettings) -> None:
        tracing.configure_tracing(app_settings, TelemetrySettings(enabled=True))

        assert isinstance(trace.get_tracer_provider(), TracerProvider)

    def test_no_provider_is_installed_when_disabled(self, app_settings: AppSettings) -> None:
        """The API then returns no-op spans, so instrumentation still costs nothing."""
        tracing.configure_tracing(app_settings, TelemetrySettings(enabled=False))

        assert not isinstance(trace.get_tracer_provider(), TracerProvider)

    def test_configuring_without_an_exporter_succeeds(self, app_settings: AppSettings) -> None:
        """A developer machine has no collector; that must not be an error.

        Spans are still created and still correlate log records, so
        instrumentation remains useful with nothing to export to.
        """
        tracing.configure_tracing(
            app_settings,
            TelemetrySettings(enabled=True, otlp_endpoint=None, console_exporter=False),
        )

        provider = trace.get_tracer_provider()
        assert isinstance(provider, TracerProvider)

        with tracing.get_tracer("test").start_as_current_span("still.records") as span:
            assert span.is_recording()

    def test_configuring_twice_is_a_no_op(self, app_settings: AppSettings) -> None:
        """Idempotence matters: a second call must not replace a live provider."""
        settings = TelemetrySettings(enabled=True)
        tracing.configure_tracing(app_settings, settings)
        first = trace.get_tracer_provider()

        tracing.configure_tracing(app_settings, settings)

        assert trace.get_tracer_provider() is first


class TestResourceAttributes:
    """Without these, every replica looks like an anonymous span producer."""

    def test_service_identity_is_attached(self, app_settings: AppSettings) -> None:
        tracing.configure_tracing(
            app_settings,
            TelemetrySettings(enabled=True, service_name="agent-platform-backend"),
        )

        provider = trace.get_tracer_provider()
        assert isinstance(provider, TracerProvider)
        attributes = provider.resource.attributes

        assert attributes["service.name"] == "agent-platform-backend"
        assert attributes["service.version"] == "9.9.9"
        assert attributes["service.namespace"] == "test-platform"
        assert attributes["deployment.environment"] == "development"


class TestSpans:
    """Spans must actually record, and must carry the ids logs join on."""

    def test_a_span_records_when_tracing_is_enabled(self, app_settings: AppSettings) -> None:
        tracing.configure_tracing(app_settings, TelemetrySettings(enabled=True))

        with tracing.get_tracer("test").start_as_current_span("unit.operation") as span:
            assert span.is_recording()
            assert span.get_span_context().is_valid

    def test_nested_spans_share_a_trace_id(self, app_settings: AppSettings) -> None:
        """A trace with unrelated ids is not a trace."""
        tracing.configure_tracing(app_settings, TelemetrySettings(enabled=True))
        tracer = tracing.get_tracer("test")

        with (
            tracer.start_as_current_span("parent") as parent,
            tracer.start_as_current_span("child") as child,
        ):
            assert child.get_span_context().trace_id == parent.get_span_context().trace_id
            assert child.get_span_context().span_id != parent.get_span_context().span_id

    def test_get_tracer_is_safe_before_configuration(self) -> None:
        """Module-level tracer creation must not depend on import order."""
        span_context = tracing.get_tracer("early").start_span("noop").get_span_context()

        assert span_context is not None


class TestShutdown:
    """Spans queued at shutdown are the ones an operator most wants."""

    def test_shutdown_clears_the_provider(self, app_settings: AppSettings) -> None:
        tracing.configure_tracing(app_settings, TelemetrySettings(enabled=True))

        tracing.shutdown_tracing()

        assert tracing._tracer_provider is None  # noqa: SLF001 - asserting teardown

    def test_shutdown_without_configuration_is_safe(self) -> None:
        tracing.shutdown_tracing()
        tracing.shutdown_tracing()
