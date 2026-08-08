"""Console entry point.

Runs the application under uvicorn using validated configuration, so that
``uv run agent-platform`` and the container image start the server identically —
no host or port is duplicated between a command line and a Dockerfile.

Configuration is loaded here, before uvicorn starts, so an invalid configuration
produces one clear message rather than a server that boots and then fails on
every request.
"""

from __future__ import annotations

import sys

import uvicorn

from agent_platform.configuration.settings import PlatformSettings, get_settings
from agent_platform.exceptions.base import ConfigurationError

__all__ = ["main"]


def _create_application() -> object:
    """Factory used by uvicorn's ``--factory`` mode and by :func:`main`."""
    from agent_platform.api.app import create_app

    return create_app()


def main() -> int:
    """Start the HTTP server.

    Returns:
        A process exit code: ``0`` on clean shutdown, ``1`` when configuration
        is invalid.
    """
    try:
        settings: PlatformSettings = get_settings()
    # Deliberately blind: this is the process boundary. Nothing above can handle
    # a failure here, so every failure must become an exit code and a message.
    except Exception as error:  # noqa: BLE001 - top-level boundary; nothing above can handle it
        # stderr, not the logger: logging is configured from the very settings
        # that failed to load, so it is not available yet.
        detail = error.message if isinstance(error, ConfigurationError) else str(error)
        sys.stderr.write(f"FATAL: platform configuration is invalid.\n{detail}\n")
        return 1

    uvicorn.run(
        "agent_platform.__main__:_create_application",
        factory=True,
        host=settings.server.host,
        port=settings.server.port,
        # Uvicorn's own logging config is disabled so records flow through the
        # structlog pipeline instead of being emitted in a second, unparsable
        # format alongside ours.
        log_config=None,
        access_log=False,
        timeout_graceful_shutdown=int(settings.server.graceful_shutdown_seconds),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
