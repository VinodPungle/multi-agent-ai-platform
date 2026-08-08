"""Cross-cutting runtime utilities shared by every platform service.

This package is deliberately dependency-free (standard library only). Anything
imported here is imposed on every service that imports the platform, so the bar
for adding a dependency is deliberately high.

See ``src/shared/README.md`` for the boundary between this package and
``agent_platform_sdk``.
"""

from agent_platform_shared.clock import Clock, SystemClock
from agent_platform_shared.correlation import (
    CORRELATION_ID_HEADER,
    REQUEST_ID_HEADER,
    bind_correlation_id,
    bind_request_id,
    correlation_scope,
    get_correlation_id,
    get_request_id,
    reset_correlation_id,
    reset_request_id,
)
from agent_platform_shared.identifiers import (
    new_correlation_id,
    new_execution_id,
    new_request_id,
)

__all__ = [
    "CORRELATION_ID_HEADER",
    "REQUEST_ID_HEADER",
    "Clock",
    "SystemClock",
    "bind_correlation_id",
    "bind_request_id",
    "correlation_scope",
    "get_correlation_id",
    "get_request_id",
    "new_correlation_id",
    "new_execution_id",
    "new_request_id",
    "reset_correlation_id",
    "reset_request_id",
]
