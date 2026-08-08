"""Application factory.

A factory rather than a module-level ``app = FastAPI()`` instance. Importing a
module must not construct an application, read configuration or install global
telemetry — that would make every test share one implicitly-built app and make
import order significant.

Startup sequence, in the order failures should surface:

1. **Configuration** — validated first. A misconfigured instance must not start
   (``CLAUDE.md``, "Fail Fast").
2. **Logging** — configured second, so every subsequent step is observable.
3. **Tracing** — installed before any request can be served.
4. **Container** — the object graph, built from validated configuration.
5. **Middleware, handlers, routes.**

Shutdown reverses the order, flushing telemetry last so that shutdown itself is
recorded.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from pydantic import ValidationError as PydanticValidationError

from agent_platform.api.errors import register_exception_handlers
from agent_platform.api.middleware.correlation import CorrelationMiddleware
from agent_platform.api.middleware.request_logging import RequestLoggingMiddleware
from agent_platform.api.v1.health import router as health_router
from agent_platform.api.v1.router import api_v1_router
from agent_platform.configuration.settings import PlatformSettings, get_settings
from agent_platform.dependencies.container import ApplicationContainer
from agent_platform.dependencies.providers import CONTAINER_STATE_KEY
from agent_platform.exceptions.base import ConfigurationError
from agent_platform.telemetry.logging import configure_logging, get_logger
from agent_platform.telemetry.tracing import configure_tracing, shutdown_tracing

__all__ = ["create_app"]

_logger = get_logger(__name__)


def _load_settings() -> PlatformSettings:
    """Load and validate configuration, or fail with an actionable message.

    Pydantic's raw ``ValidationError`` names fields but not what an operator
    should do about them, so it is translated into a
    :class:`~agent_platform.exceptions.base.ConfigurationError` that says which
    environment variables are involved.

    Raises:
        ConfigurationError: when configuration is missing or invalid.
    """
    try:
        return get_settings()
    except PydanticValidationError as error:
        message = (
            "Platform configuration is invalid and the application cannot start.\n"
            f"{error}\n"
            "Check your environment variables and .env file against .env.example. "
            "Nested settings use the PLATFORM_<SECTION>__<FIELD> form, "
            "for example PLATFORM_SERVER__PORT."
        )
        raise ConfigurationError(message) from error


def _build_lifespan(
    settings: PlatformSettings,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """Create the lifespan handler bound to this application's settings.

    Startup work that must not happen at import time — installing global
    telemetry, initialising providers — belongs here.
    """

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        configure_tracing(settings.app, settings.telemetry)

        _logger.info(
            "platform.started",
            platform_name=settings.app.name,
            version=settings.app.version,
            environment=settings.app.environment.value,
            debug=settings.app.debug,
            features=settings.features.as_dict(),
        )

        # Provider initialisation is added here as later milestones register
        # providers, so a misconfigured provider fails at boot rather than on a
        # user's first request.

        try:
            yield
        finally:
            _logger.info("platform.stopping")
            # Telemetry is flushed last so the shutdown record above is exported.
            shutdown_tracing()

    return lifespan


def create_app(settings: PlatformSettings | None = None) -> FastAPI:
    """Build a configured FastAPI application.

    Args:
        settings: Pre-built settings. Tests pass an explicit instance to get an
            isolated app; production passes nothing and configuration is loaded
            and validated from the environment.

    Returns:
        A fully wired application.

    Raises:
        ConfigurationError: when configuration is missing or invalid.
    """
    resolved = settings if settings is not None else _load_settings()

    configure_logging(resolved.logging)

    container = ApplicationContainer(settings=resolved)

    application = FastAPI(
        title=resolved.app.name,
        version=resolved.app.version,
        description=(
            "Enterprise Multi-Agent AI Platform — provider-agnostic runtime for "
            "hosting collaborating AI agents."
        ),
        # Interactive docs and the raw schema are development aids. In a
        # production-like environment they describe the attack surface, so they
        # are withdrawn along with debug mode.
        docs_url="/docs" if resolved.app.debug else None,
        redoc_url="/redoc" if resolved.app.debug else None,
        openapi_url="/openapi.json" if resolved.app.debug else None,
        lifespan=_build_lifespan(resolved),
    )

    # Read by dependency providers, so route handlers resolve from *this* app's
    # container rather than a module-level global.
    setattr(application.state, CONTAINER_STATE_KEY, container)

    _register_middleware(application, resolved)
    register_exception_handlers(application)
    _register_routes(application, resolved)

    if resolved.telemetry.enabled:
        # Produces a server span per request, which every span created inside a
        # handler then nests under.
        FastAPIInstrumentor.instrument_app(
            application,
            # Probes would otherwise dominate trace volume and cost.
            excluded_urls="live,ready,health",
        )

    return application


def _register_middleware(application: FastAPI, settings: PlatformSettings) -> None:
    """Install middleware.

    Starlette applies middleware in reverse registration order, so the *last*
    one added is outermost. Correlation is registered last so it wraps
    everything else and every record — including CORS rejections and unhandled
    errors — carries a correlation id.
    """
    application.add_middleware(RequestLoggingMiddleware)

    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.server.cors_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        # Browsers hide non-safelisted response headers from scripts unless they
        # are exposed. Without this the frontend cannot read the correlation id
        # it needs to attach to a client-side error report.
        expose_headers=["X-Correlation-ID", "X-Request-ID"],
    )

    application.add_middleware(CorrelationMiddleware)


def _register_routes(application: FastAPI, settings: PlatformSettings) -> None:
    """Mount health probes at the root and the versioned API under its prefix."""
    # Probes are infrastructure, not API: they stay at the root so orchestrator
    # configuration does not change when the API is versioned.
    application.include_router(health_router)

    application.include_router(api_v1_router, prefix=settings.server.api_prefix)
