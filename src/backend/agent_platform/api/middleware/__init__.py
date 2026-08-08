"""HTTP middleware.

Order is significant and is fixed in
:func:`agent_platform.api.app.create_app`. Outermost first:

1. :class:`CorrelationMiddleware` — establishes the ids everything else logs under.
2. ``CORSMiddleware`` — must see the response before it is returned to a browser.
3. :class:`RequestLoggingMiddleware` — times the handler, not the middleware above it.
"""

from agent_platform.api.middleware.correlation import CorrelationMiddleware
from agent_platform.api.middleware.request_logging import RequestLoggingMiddleware

__all__ = ["CorrelationMiddleware", "RequestLoggingMiddleware"]
