"""Centralised HTTP error handling.

``CLAUDE.md`` requires exception handling to be centralised, stack traces never
to be exposed, meaningful errors to be returned, and full diagnostics to be
logged internally. This module is the single place where a Python exception
becomes an HTTP response.

Every response uses one envelope, so clients parse errors the same way no matter
what failed:

.. code-block:: json

    {
      "error": {
        "category": "validation",
        "message": "Request validation failed",
        "correlation_id": "5e2f...",
        "fields": [{"location": "body.temperature", "message": "less than or equal to 2"}]
      }
    }

The correlation id is included deliberately: it is what turns a user's bug report
into a searchable trace.
"""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from agent_platform.exceptions.base import PlatformError
from agent_platform.telemetry.logging import get_logger
from agent_platform_sdk.types.enums import ErrorCategory
from agent_platform_shared import get_correlation_id

__all__ = ["ErrorBody", "ErrorResponse", "FieldError", "register_exception_handlers"]

_logger = get_logger(__name__)

#: Maps a normalised failure category to an HTTP status. Adding an exception
#: type therefore needs no change here — only a category on the new class.
_STATUS_BY_CATEGORY: dict[ErrorCategory, int] = {
    ErrorCategory.VALIDATION: status.HTTP_422_UNPROCESSABLE_CONTENT,
    ErrorCategory.NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCategory.POLICY_VIOLATION: status.HTTP_403_FORBIDDEN,
    ErrorCategory.TIMEOUT: status.HTTP_504_GATEWAY_TIMEOUT,
    ErrorCategory.PROVIDER: status.HTTP_502_BAD_GATEWAY,
    ErrorCategory.NETWORK: status.HTTP_502_BAD_GATEWAY,
    ErrorCategory.TOOL: status.HTTP_502_BAD_GATEWAY,
    ErrorCategory.MEMORY: status.HTTP_500_INTERNAL_SERVER_ERROR,
    ErrorCategory.CONFIGURATION: status.HTTP_500_INTERNAL_SERVER_ERROR,
    ErrorCategory.UNEXPECTED: status.HTTP_500_INTERNAL_SERVER_ERROR,
}

#: Returned instead of the real message for unhandled exceptions. An arbitrary
#: exception's text can contain a connection string, a file path or user data,
#: none of which may cross the network boundary.
_OPAQUE_MESSAGE = "An unexpected error occurred. Quote the correlation id when reporting this."


class FieldError(BaseModel):
    """A single field-level validation failure."""

    model_config = ConfigDict(frozen=True)

    location: str = Field(description="Dotted path to the offending field, e.g. 'body.name'.")
    message: str = Field(description="What was wrong with the value.")


class ErrorBody(BaseModel):
    """The error envelope."""

    model_config = ConfigDict(frozen=True)

    category: ErrorCategory = Field(description="Normalised failure classification.")
    message: str = Field(description="Client-safe summary. Never contains internal detail.")
    correlation_id: str | None = Field(
        default=None,
        description="Identifier joining this response to server logs and traces.",
    )
    fields: tuple[FieldError, ...] = Field(
        default=(),
        description="Field-level detail, present for validation failures.",
    )


class ErrorResponse(BaseModel):
    """Top-level error response returned by every failing endpoint."""

    model_config = ConfigDict(frozen=True)

    error: ErrorBody


def _render(
    category: ErrorCategory,
    message: str,
    http_status: int,
    fields: tuple[FieldError, ...] = (),
) -> JSONResponse:
    """Build a JSON error response in the standard envelope."""
    body = ErrorResponse(
        error=ErrorBody(
            category=category,
            message=message,
            correlation_id=get_correlation_id(),
            fields=fields,
        )
    )
    return JSONResponse(status_code=http_status, content=body.model_dump(mode="json"))


async def _handle_platform_error(_request: Request, exc: Exception) -> JSONResponse:
    """Convert a deliberate platform failure into an HTTP response.

    ``exc.message`` is safe to return: platform errors are raised by our own
    code with client-facing text. ``exc.details`` is logged but never returned,
    since it may hold internal identifiers.
    """
    error = exc if isinstance(exc, PlatformError) else PlatformError(str(exc))
    http_status = _STATUS_BY_CATEGORY.get(error.category, status.HTTP_500_INTERNAL_SERVER_ERROR)

    log = _logger.error if http_status >= status.HTTP_500_INTERNAL_SERVER_ERROR else _logger.warning
    log(
        "api.platform_error",
        error_type=type(error).__name__,
        error_category=error.category.value,
        http_status=http_status,
        details=error.details,
        exc_info=http_status >= status.HTTP_500_INTERNAL_SERVER_ERROR,
    )

    return _render(error.category, error.message, http_status)


async def _handle_request_validation_error(_request: Request, exc: Exception) -> JSONResponse:
    """Convert FastAPI's request validation failure into the standard envelope.

    Without this, FastAPI returns its own shape and clients would need two
    parsers for errors.
    """
    raw_errors = exc.errors() if isinstance(exc, RequestValidationError) else []
    fields = tuple(
        FieldError(
            location=".".join(str(part) for part in error.get("loc", ())),
            message=str(error.get("msg", "invalid value")),
        )
        for error in raw_errors
    )

    _logger.info("api.validation_failed", field_count=len(fields))

    return _render(
        ErrorCategory.VALIDATION,
        "Request validation failed",
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        fields,
    )


async def _handle_http_exception(_request: Request, exc: Exception) -> JSONResponse:
    """Convert Starlette's ``HTTPException`` — including 404s — into the envelope."""
    http_status = (
        exc.status_code
        if isinstance(exc, StarletteHTTPException)
        else status.HTTP_500_INTERNAL_SERVER_ERROR
    )
    detail = exc.detail if isinstance(exc, StarletteHTTPException) else _OPAQUE_MESSAGE

    category = (
        ErrorCategory.NOT_FOUND
        if http_status == status.HTTP_404_NOT_FOUND
        else (
            ErrorCategory.VALIDATION
            if http_status < status.HTTP_500_INTERNAL_SERVER_ERROR
            else ErrorCategory.UNEXPECTED
        )
    )

    return _render(category, str(detail), http_status)


async def _handle_unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
    """Catch anything not handled above.

    Logs the full traceback internally and returns an opaque message. This is
    the boundary that guarantees no stack trace ever reaches a client, however
    the failure arose.
    """
    _logger.exception("api.unhandled_exception", error_type=type(exc).__name__)
    return _render(
        ErrorCategory.UNEXPECTED,
        _OPAQUE_MESSAGE,
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Attach every error handler to ``app``.

    Registration order does not matter — FastAPI dispatches on the most specific
    registered exception class.
    """
    app.add_exception_handler(PlatformError, _handle_platform_error)
    app.add_exception_handler(RequestValidationError, _handle_request_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(Exception, _handle_unexpected_error)
