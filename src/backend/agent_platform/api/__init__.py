"""Presentation layer — the platform's HTTP surface.

Responsibility
    Routing, request validation, serialisation, middleware and error mapping.

Dependency rule
    No business logic. Route handlers resolve an application service through
    dependency injection, call it, and shape the result. A handler that contains
    a decision belongs in ``application`` instead.
"""

from agent_platform.api.app import create_app

__all__ = ["create_app"]
