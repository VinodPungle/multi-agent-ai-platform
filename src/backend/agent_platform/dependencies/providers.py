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

from agent_platform.application.chat_service import ChatService
from agent_platform.application.health_service import HealthService
from agent_platform.configuration.settings import PlatformSettings
from agent_platform.dependencies.container import ApplicationContainer
from agent_platform.evaluation.cost_analytics import InMemoryCostAnalytics
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_shared import get_correlation_id, get_request_id

__all__ = [
    "ChatServiceDep",
    "ContainerDep",
    "CostAnalyticsDep",
    "ExecutionContextDep",
    "HealthServiceDep",
    "SettingsDep",
    "get_chat_service",
    "get_container",
    "get_execution_context",
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


def get_chat_service(container: ContainerDep) -> ChatService:
    """Return the chat use case."""
    service: ChatService = container.chat_service()
    return service


ChatServiceDep = Annotated[ChatService, Depends(get_chat_service)]


def get_cost_analytics(container: ContainerDep) -> InMemoryCostAnalytics:
    """Return the running cost totals.

    Typed as the concrete class rather than `EvaluationProvider`, and that is
    deliberate: the endpoint needs to *query* the totals, and querying is not
    part of the recording contract. Widening the interface so this could be
    abstract would force every future sink to implement a report it has no
    way to produce.
    """
    analytics: InMemoryCostAnalytics = container.cost_analytics()
    return analytics


CostAnalyticsDep = Annotated[InMemoryCostAnalytics, Depends(get_cost_analytics)]


def get_execution_context(settings: SettingsDep) -> ExecutionContext:
    """Build the execution context for the current request.

    The identifiers come from the correlation middleware, which has already
    read the inbound headers or generated new values. Reading them from the
    ambient context rather than re-deriving them here is what guarantees the
    context, the log records and the response headers all carry the same ids.

    Feature flags are resolved once, at entry, and carried on the context.
    Resolving them per component would let one request see a flag change
    halfway through — which produces behaviour no log can explain.
    """
    return ExecutionContext(
        correlation_id=get_correlation_id() or ExecutionContext().correlation_id,
        request_id=get_request_id() or ExecutionContext().request_id,
        feature_flags=settings.features.as_dict(),
    )


ExecutionContextDep = Annotated[ExecutionContext, Depends(get_execution_context)]
