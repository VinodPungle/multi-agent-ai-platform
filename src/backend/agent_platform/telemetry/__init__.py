"""Observability: structured logging and distributed tracing.

Responsibility
    Configure structlog and OpenTelemetry once at startup, and expose the
    accessors the rest of the platform uses to log and trace.

Design rule
    Every other module obtains its logger from :func:`get_logger` and its tracer
    from :func:`get_tracer`. Nothing calls :func:`logging.getLogger` or
    ``print()`` directly.
"""

from agent_platform.telemetry.logging import (
    bind_log_context,
    clear_log_context,
    configure_logging,
    get_logger,
)
from agent_platform.telemetry.tracing import (
    configure_tracing,
    get_tracer,
    shutdown_tracing,
)

__all__ = [
    "bind_log_context",
    "clear_log_context",
    "configure_logging",
    "configure_tracing",
    "get_logger",
    "get_tracer",
    "shutdown_tracing",
]
