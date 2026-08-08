"""Request-scoped dependency providers for FastAPI route handlers.

Bridges the ``dependency-injector`` container into FastAPI's ``Depends``
mechanism. The container is stored on ``app.state`` and read from the request,
rather than resolved from a module-level global.

That choice matters for testing: a test builds its own app with its own
container and gets full isolation. With a global, tests would share one graph
and leak state between each other.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from agent_platform.application.health_service import HealthService
from agent_platform.configuration.settings import PlatformSettings
from agent_platform.dependencies.container import ApplicationContainer

__all__ = [
    "ContainerDep",
    "HealthServiceDep",
    "SettingsDep",
    "get_container",
    "get_health_service",
    "get_platform_settings",
]

#: Attribute under which the application factory stores the container.
CONTAINER_STATE_KEY = "container"


def get_container(request: Request) -> ApplicationContainer:
    """Return the container attached to the running application.

    Raises:
        RuntimeError: if no container is present. That can only happen when an
            app was built without the factory, which is a programming error
            worth failing loudly on rather than papering over.
    """
    container = getattr(request.app.state, CONTAINER_STATE_KEY, None)
    if container is None:
        message = (
            "No dependency container on app.state. "
            "Build the application with agent_platform.api.app.create_app()."
        )
        raise RuntimeError(message)
    return container  # type: ignore[no-any-return]  # attribute is untyped on Starlette State


ContainerDep = Annotated[ApplicationContainer, Depends(get_container)]


def get_platform_settings(container: ContainerDep) -> PlatformSettings:
    """Return the validated platform settings."""
    settings: PlatformSettings = container.settings()
    return settings


SettingsDep = Annotated[PlatformSettings, Depends(get_platform_settings)]


def get_health_service(container: ContainerDep) -> HealthService:
    """Return the health aggregation service."""
    service: HealthService = container.health_service()
    return service


HealthServiceDep = Annotated[HealthService, Depends(get_health_service)]
