"""Enterprise Multi-Agent AI Platform — backend.

Package layout follows ``architecture.md`` §68. See ``src/backend/README.md`` for
the responsibility of each package and the dependency rules between them.

Deliberately free of side effects: importing this package must not read
configuration, install telemetry or build an application. Use
:func:`agent_platform.api.app.create_app` for that.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
