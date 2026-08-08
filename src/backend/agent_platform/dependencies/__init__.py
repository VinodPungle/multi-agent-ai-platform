"""Composition root and FastAPI request-scoped dependency providers.

Responsibility
    Construct the object graph (``container.py``) and expose it to route
    handlers through FastAPI's dependency system (``providers.py``).

Design rule
    This is the only package permitted to instantiate implementations. Every
    other module declares its collaborators as constructor parameters.
"""

from agent_platform.dependencies.container import ApplicationContainer

__all__ = ["ApplicationContainer"]
