"""Platform exception hierarchy.

Every platform failure derives from :class:`PlatformError` and carries an
:class:`~agent_platform_sdk.types.enums.ErrorCategory`. The API error handler
maps the category to an HTTP status, so adding an exception type never requires
touching the handler, and retry logic can decide from the category alone whether
a failure is worth retrying.

Two naming deviations from the handbook's example list, both to avoid shadowing
a builtin — ``except MemoryError`` catching a platform error instead of a real
out-of-memory condition would be a genuinely dangerous bug:

===========================  ==========================
Handbook name                Name used here
===========================  ==========================
``MemoryError``              :class:`MemoryOperationError`
``Timeout``                  :class:`PlatformTimeoutError`
===========================  ==========================
"""

from __future__ import annotations

from typing import Any

from agent_platform_sdk.types.enums import ErrorCategory

__all__ = [
    "ConfigurationError",
    "ConflictError",
    "MemoryOperationError",
    "NotFoundError",
    "PlatformError",
    "PlatformTimeoutError",
    "PolicyViolationError",
    "ProviderError",
    "ToolExecutionError",
    "ValidationError",
    "WorkflowError",
]


class PlatformError(Exception):
    """Base class for every failure the platform raises deliberately.

    Attributes:
        message: Operator- and client-safe summary. Must never contain a
            credential, a connection string or user content — this string is
            returned over HTTP.
        category: Normalised classification driving status mapping and retries.
        details: Structured diagnostic context attached to logs. **Not**
            returned to clients, so it may hold internal identifiers.
    """

    category: ErrorCategory = ErrorCategory.UNEXPECTED

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __repr__(self) -> str:
        return f"{type(self).__name__}(category={self.category.value!r}, message={self.message!r})"


class ConfigurationError(PlatformError):
    """Configuration is missing, malformed, or invalid for the environment.

    Raised during startup. The application must not continue: serving traffic
    with unknown configuration is worse than not serving it at all.
    """

    category = ErrorCategory.CONFIGURATION


class ValidationError(PlatformError):
    """Input failed validation.

    Never retried — the same input will fail identically, so retrying only
    delays the error the caller needs to see.
    """

    category = ErrorCategory.VALIDATION


class NotFoundError(PlatformError):
    """A requested agent, model, tool, prompt or conversation does not exist."""

    category = ErrorCategory.NOT_FOUND


class ConflictError(PlatformError):
    """An operation conflicts with existing state.

    Chiefly duplicate registration: registering two providers under one key is a
    configuration mistake that must surface at startup rather than resolve
    silently in favour of whichever loaded last.
    """

    category = ErrorCategory.VALIDATION


class ProviderError(PlatformError):
    """An external provider failed.

    Carries ``provider_id`` so that failures can be attributed and, later,
    unhealthy providers routed around.
    """

    category = ErrorCategory.PROVIDER

    def __init__(
        self,
        message: str,
        *,
        provider_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        merged = {**(details or {})}
        if provider_id is not None:
            merged["provider_id"] = provider_id
        super().__init__(message, details=merged)
        self.provider_id = provider_id


class ToolExecutionError(PlatformError):
    """A tool failed in a way the agent cannot reason about.

    Expected tool outcomes — no results, an upstream 404 — belong in a
    ``ToolResult`` with ``succeeded=False``. This is for failures that should
    abort the step.
    """

    category = ErrorCategory.TOOL


class MemoryOperationError(PlatformError):
    """A memory provider operation failed."""

    category = ErrorCategory.MEMORY


class PlatformTimeoutError(PlatformError):
    """An operation exceeded its configured timeout."""

    category = ErrorCategory.TIMEOUT


class PolicyViolationError(PlatformError):
    """An operation would breach a budget, permission or safety policy.

    Never retried: the policy will reject the retry identically.
    """

    category = ErrorCategory.POLICY_VIOLATION


class WorkflowError(PlatformError):
    """A workflow could not complete."""

    category = ErrorCategory.UNEXPECTED
