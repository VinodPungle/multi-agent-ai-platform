"""Correlation middleware.

Establishes the identifiers every log record, span and downstream call is
attributed to. This must be the outermost middleware so that anything logged by
inner middleware — including failures — already carries a correlation id.

An inbound ``X-Correlation-ID`` is honoured so a trace started by an upstream
caller continues rather than fragmenting into two unrelated traces. A request id
is always generated locally, because a client-supplied one cannot be trusted to
be unique across callers.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from agent_platform.telemetry.logging import bind_log_context, clear_log_context
from agent_platform_shared import (
    CORRELATION_ID_HEADER,
    REQUEST_ID_HEADER,
    correlation_scope,
    new_correlation_id,
    new_request_id,
)

__all__ = ["CorrelationMiddleware"]

#: Upper bound on an accepted inbound correlation id. Unbounded client input
#: would otherwise flow into every log record and span attribute for the
#: request — a cheap way for a caller to inflate log storage.
_MAX_CORRELATION_ID_LENGTH = 128


class CorrelationMiddleware(BaseHTTPMiddleware):
    """Binds correlation and request ids for the lifetime of a request."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Bind identifiers, handle the request, and echo the ids back."""
        correlation_id = self._resolve_correlation_id(request)
        request_id = new_request_id()

        # `correlation_scope` restores the previous values on exit, so ids
        # cannot leak between requests handled by the same worker task.
        with correlation_scope(correlation_id=correlation_id, request_id=request_id):
            bind_log_context(correlation_id=correlation_id, request_id=request_id)
            try:
                response = await call_next(request)
            finally:
                clear_log_context()

        # Echoed on every response, including errors, so a caller can quote the
        # id in a support request and an operator can find the exact trace.
        response.headers[CORRELATION_ID_HEADER] = correlation_id
        response.headers[REQUEST_ID_HEADER] = request_id
        return response

    @staticmethod
    def _resolve_correlation_id(request: Request) -> str:
        """Return the inbound correlation id if usable, otherwise a new one.

        A header that is absent, blank or over-long is replaced rather than
        rejected: refusing the request would turn a caller's cosmetic mistake
        into an outage, and a fresh id loses only the join to the upstream trace.
        """
        inbound = request.headers.get(CORRELATION_ID_HEADER, "").strip()
        if inbound and len(inbound) <= _MAX_CORRELATION_ID_LENGTH:
            return inbound
        return new_correlation_id()
