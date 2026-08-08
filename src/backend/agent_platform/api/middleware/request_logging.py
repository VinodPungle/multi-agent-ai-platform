"""Access logging middleware.

Emits one structured record per request with the fields the handbook requires:
correlation id, request id, method, path, status and latency. Correlation ids
are injected by the logging processor chain, so they are not passed explicitly
here.

Runs inside :class:`~agent_platform.api.middleware.correlation.CorrelationMiddleware`
so every record it emits already carries those ids.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from agent_platform.telemetry.logging import get_logger
from agent_platform_shared.clock import Clock, SystemClock

__all__ = ["RequestLoggingMiddleware"]

_logger = get_logger(__name__)

#: Paths excluded from access logging. Container platforms probe these every few
#: seconds; logging them buries real traffic and costs real money in ingestion.
_UNLOGGED_PATHS = frozenset({"/live", "/ready", "/health"})


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Logs the outcome and duration of every request."""

    def __init__(self, app: object, clock: Clock | None = None) -> None:
        """Create the middleware.

        Args:
            app: The ASGI application to wrap.
            clock: Injected time source. Defaults to the system clock so the
                middleware can be added without threading the container through
                application construction.
        """
        super().__init__(app)  # type: ignore[arg-type]  # Starlette types this as ASGIApp
        self._clock = clock or SystemClock()

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Time the request and emit a single structured access record."""
        if self._is_unlogged(request.url.path):
            return await call_next(request)

        started = self._clock.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            # Logged here because an exception escaping the handler never
            # reaches the success path below, and an unlogged failure is
            # invisible. The exception is re-raised for the error handlers.
            _logger.exception(
                "http.request_failed",
                http_method=request.method,
                http_path=request.url.path,
                latency_ms=(self._clock.monotonic() - started) * 1000,
            )
            raise

        latency_ms = (self._clock.monotonic() - started) * 1000
        _logger.info(
            "http.request_completed",
            http_method=request.method,
            http_path=request.url.path,
            http_status=response.status_code,
            latency_ms=round(latency_ms, 3),
        )
        return response

    @staticmethod
    def _is_unlogged(path: str) -> bool:
        """Return whether ``path`` is a health probe that should not be logged."""
        return any(path.endswith(probe) for probe in _UNLOGGED_PATHS)
