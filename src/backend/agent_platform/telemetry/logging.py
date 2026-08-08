"""Structured logging bootstrap.

``CLAUDE.md`` requires structured logging only, with a correlation id on every
record and no secrets. This module configures structlog once at startup and
routes the standard library's ``logging`` through the same pipeline, so that
records emitted by uvicorn and third-party libraries come out in the same format
as ours instead of as unparsable free text.

Two processors do the platform-specific work:

``_add_correlation_ids``
    Injects the ambient correlation and request ids, so no call site has to
    remember to pass them.
``_add_trace_context``
    Injects the active OpenTelemetry trace and span ids, which is what lets an
    operator pivot from a log line to the trace that produced it.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from opentelemetry import trace
from structlog.types import EventDict, Processor

from agent_platform.configuration.settings import LoggingSettings
from agent_platform_shared import get_correlation_id, get_request_id

__all__ = ["configure_logging", "get_logger"]


class _CurrentStdoutHandler(logging.Handler):
    """Writes to whatever ``sys.stdout`` is at the moment of the write.

    :class:`logging.StreamHandler` captures the stream when it is constructed.
    That binding outlives any later redirection of ``sys.stdout`` — under
    pytest's output capture, and under any tooling that wraps the stream after
    startup, records would be written to a stream nobody is reading, or to one
    that has since been closed.

    Resolving the stream per record costs one attribute lookup and removes the
    whole class of problem.
    """

    def emit(self, record: logging.LogRecord) -> None:
        """Format ``record`` and write it to the current stdout."""
        try:
            stream = sys.stdout
            stream.write(self.format(record) + "\n")
            stream.flush()
        except RecursionError:  # pragma: no cover - defended against by logging itself
            raise
        except Exception:  # noqa: BLE001 - a logging failure must never crash the caller
            self.handleError(record)


def _add_correlation_ids(
    _logger: object,
    _method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Attach the ambient correlation and request ids to the record.

    Values are omitted rather than written as ``null`` when unset — records
    emitted during startup and shutdown have no request to belong to.
    """
    correlation_id = get_correlation_id()
    if correlation_id is not None:
        event_dict.setdefault("correlation_id", correlation_id)

    request_id = get_request_id()
    if request_id is not None:
        event_dict.setdefault("request_id", request_id)

    return event_dict


def _add_trace_context(
    _logger: object,
    _method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Attach the active trace and span ids, when a span is recording.

    Formatted as the 32- and 16-character hex strings the OpenTelemetry
    specification defines, so the values match what tracing backends display.
    """
    span = trace.get_current_span()
    span_context = span.get_span_context()
    if span_context.is_valid:
        event_dict.setdefault("trace_id", format(span_context.trace_id, "032x"))
        event_dict.setdefault("span_id", format(span_context.span_id, "016x"))
    return event_dict


def _build_processor_chain(settings: LoggingSettings) -> list[Processor]:
    """Assemble the shared processor chain.

    Order matters: context is merged first so later processors can see it, and
    the renderer must be last.
    """
    processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        _add_correlation_ids,
        _add_trace_context,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        # Renders `exc_info` into a string. Without it, exception objects reach
        # the JSON renderer unserialisable and the record is silently dropped.
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if settings.include_source:
        processors.append(
            structlog.processors.CallsiteParameterAdder(
                {
                    structlog.processors.CallsiteParameter.MODULE,
                    structlog.processors.CallsiteParameter.FUNC_NAME,
                    structlog.processors.CallsiteParameter.LINENO,
                }
            )
        )

    return processors


def configure_logging(settings: LoggingSettings) -> None:
    """Configure structlog and the standard library logging module.

    Idempotent: safe to call again in tests that need a different renderer.

    Args:
        settings: Validated logging configuration.
    """
    shared_processors = _build_processor_chain(settings)

    renderer: Processor = (
        structlog.dev.ConsoleRenderer(colors=False)
        if settings.renderer == "console"
        else structlog.processors.JSONRenderer()
    )

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Route stdlib logging (uvicorn, opentelemetry, third-party libraries)
    # through the same processor chain so every line in the stream has the same
    # shape and carries the same correlation fields.
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = _CurrentStdoutHandler()
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    # Replace rather than append: calling this twice would otherwise duplicate
    # every record, which is easy to miss and expensive in log volume.
    root_logger.handlers = [handler]
    root_logger.setLevel(settings.level)

    # uvicorn installs its own handlers; clearing them prevents each request
    # being logged twice, once formatted and once not.
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(logger_name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound logger for ``name``.

    Always use this rather than :func:`logging.getLogger`, so that every logger
    in the platform carries the processor chain configured above.
    """
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger


def bind_log_context(**fields: Any) -> None:  # noqa: ANN401 - arbitrary log fields
    """Bind fields to every subsequent record in this context.

    Backed by contextvars, so the fields follow the ``await`` chain and are
    cleared when the context ends.
    """
    structlog.contextvars.bind_contextvars(**fields)


def clear_log_context() -> None:
    """Remove all context-bound log fields.

    Called at the end of a request so that fields cannot leak into the next one
    handled by the same worker.
    """
    structlog.contextvars.clear_contextvars()
