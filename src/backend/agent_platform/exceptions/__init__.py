"""Platform exception hierarchy.

The handbook requires a custom hierarchy so that failures can be categorised and
converted into consistent API responses without exposing internals
(``architecture.md`` §22).
"""

from agent_platform.exceptions.base import (
    ConfigurationError,
    ConflictError,
    MemoryOperationError,
    NotFoundError,
    PlatformError,
    PlatformTimeoutError,
    PolicyViolationError,
    ProviderError,
    ToolExecutionError,
    ValidationError,
    WorkflowError,
)

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
