"""Strongly typed platform configuration.

The handbook forbids scattered environment-variable lookups: configuration is
loaded once, validated once, and injected everywhere else. Nothing in the
platform may call :func:`os.environ` directly.

Sources, highest precedence first (``architecture.md`` §71):

1. Process environment variables
2. Azure Key Vault (Milestone 05)
3. Environment YAML (Milestone 06)
4. Defaults declared on the models below

Nested sections use the ``__`` delimiter, so ``settings.server.port`` is set by
``PLATFORM_SERVER__PORT``.

Every model is frozen. Configuration is immutable after startup — a value that
can change at runtime cannot be reasoned about from a log line that recorded it
an hour earlier.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from pydantic_settings.sources import DotEnvSettingsSource, PydanticBaseSettingsSource

__all__ = [
    "AppSettings",
    "Environment",
    "FeatureFlagSettings",
    "LoggingSettings",
    "PlatformSettings",
    "ServerSettings",
    "TelemetrySettings",
    "get_settings",
]


class Environment(StrEnum):
    """Deployment environment.

    Drives the production-safety checks in :meth:`PlatformSettings.enforce_environment_invariants`.
    """

    DEVELOPMENT = "development"
    TESTING = "testing"
    STAGING = "staging"
    PRODUCTION = "production"

    @property
    def is_production_like(self) -> bool:
        """Whether this environment carries real traffic or real data.

        Staging counts: it holds production-shaped data and is reachable, so the
        same debug and CORS restrictions apply.
        """
        return self in {Environment.STAGING, Environment.PRODUCTION}


class AppSettings(BaseModel):
    """Identity and mode of the running application."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(default="multi-agent-ai-platform", min_length=1)
    version: str = Field(default="0.1.0", min_length=1)
    environment: Environment = Field(default=Environment.DEVELOPMENT)
    debug: bool = Field(
        default=False,
        description="Exposes API docs and verbose errors. Rejected in production.",
    )


class ServerSettings(BaseModel):
    """HTTP server and transport configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    host: str = Field(default="127.0.0.1", min_length=1)
    port: int = Field(default=8000, ge=1, le=65535)
    api_prefix: str = Field(default="/api", description="Base path for all versioned routes.")
    # `NoDecode` is required, not cosmetic. For a field with a collection type,
    # `pydantic-settings` attempts `json.loads` on the raw environment value
    # *before* any validator runs, and raises `SettingsError` when that fails.
    # A comma-separated list would therefore never reach the validator below.
    # `NoDecode` suppresses that attempt and hands the raw string over.
    cors_origins: Annotated[tuple[str, ...], NoDecode] = Field(
        default=("http://localhost:5173",),
        description="Browser origins permitted to call the API.",
    )
    graceful_shutdown_seconds: float = Field(default=15.0, gt=0)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_comma_separated(cls, value: object) -> object:
        """Accept a comma-separated string as well as a list.

        Environment variables and Container Apps settings are single strings;
        without this every deployment surface would need its own JSON encoding
        of what is conceptually a short list.
        """
        if isinstance(value, str):
            return tuple(origin.strip() for origin in value.split(",") if origin.strip())
        return value

    @field_validator("api_prefix")
    @classmethod
    def _normalise_prefix(cls, value: str) -> str:
        """Ensure the prefix has a leading slash and no trailing slash.

        Route registration concatenates this with a version segment, so
        ``/api/`` and ``api`` would both produce malformed paths.
        """
        normalised = value.strip()
        if not normalised.startswith("/"):
            normalised = f"/{normalised}"
        return normalised.rstrip("/")


class LoggingSettings(BaseModel):
    """Structured logging configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(default="INFO")
    renderer: Literal["json", "console"] = Field(
        default="json",
        description="`console` is human-readable; `json` is required outside development.",
    )
    include_source: bool = Field(
        default=False,
        description="Adds module, function and line to every record.",
    )

    @field_validator("level", mode="before")
    @classmethod
    def _uppercase_level(cls, value: object) -> object:
        """Accept lowercase level names, which operators type more often than not."""
        return value.upper() if isinstance(value, str) else value


class TelemetrySettings(BaseModel):
    """OpenTelemetry configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = Field(default=True)
    service_name: str = Field(default="agent-platform-backend", min_length=1)
    otlp_endpoint: str | None = Field(
        default=None,
        description="OTLP/HTTP collector base URL. None disables the OTLP exporter.",
    )
    console_exporter: bool = Field(
        default=False,
        description="Prints spans to stdout. Useful locally, far too noisy in production.",
    )
    sample_ratio: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Head-based trace sampling ratio.",
    )
    azure_monitor_connection_string: str | None = Field(
        default=None,
        repr=False,
        description=(
            "Application Insights connection string. Contains an instrumentation key, "
            "so `repr=False` keeps it out of accidental model dumps and stack traces."
        ),
    )

    @field_validator("otlp_endpoint", "azure_monitor_connection_string", mode="before")
    @classmethod
    def _empty_string_is_none(cls, value: object) -> object:
        """Treat an empty environment variable as unset.

        ``.env`` files and container platforms both represent "not configured"
        as an empty string, which would otherwise become a valid-looking empty
        endpoint and fail at export time instead of at startup.
        """
        if isinstance(value, str) and not value.strip():
            return None
        return value


class FeatureFlagSettings(BaseModel):
    """Runtime feature toggles.

    Declared in Milestone 01 and default to off. Later milestones enable
    capabilities by configuration rather than by code change
    (``CLAUDE.md``, "Feature Flags").
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    streaming: bool = Field(default=False, description="Milestone 02.")
    memory: bool = Field(default=False, description="Milestone 02.")
    search: bool = Field(default=False, description="Milestone 04.")
    evaluation: bool = Field(default=False, description="Milestone 05.")
    cost_tracking: bool = Field(default=False, description="Milestone 05.")

    def as_dict(self) -> dict[str, bool]:
        """Return the flags as a plain mapping for the execution context."""
        return self.model_dump()


class _NamespacedDotEnvSource(DotEnvSettingsSource):
    """Reads only this application's namespace from a shared ``.env`` file.

    One ``.env`` at the repository root serves the backend, the frontend and
    Docker Compose, so it legitimately contains ``VITE_*``, ``BACKEND_PORT`` and
    ``FRONTEND_PORT`` alongside ``PLATFORM_*``. Two files would drift, and a
    developer would have to remember which one holds what.

    The default dotenv source hands *every* key in the file to the model, unlike
    the process-environment source, which filters by prefix. Combined with
    ``extra="forbid"`` that makes the application refuse to start the moment a
    developer copies ``.env.example`` to ``.env`` — the first thing the setup
    guide tells them to do.

    Filtering here rather than relaxing ``extra`` keeps the typo detection that
    ``extra="forbid"`` exists to provide: a misspelled ``PLATFORM_*`` variable is
    still a startup failure, while a variable belonging to another tool is
    correctly ignored.
    """

    def _load_env_vars(self) -> Mapping[str, str | None]:
        """Return only the keys carrying this settings model's prefix."""
        prefix = self.env_prefix.lower()
        return {
            key: value
            for key, value in super()._load_env_vars().items()
            if key.lower().startswith(prefix)
        }


class PlatformSettings(BaseSettings):
    """Root configuration object. Constructed exactly once per process."""

    model_config = SettingsConfigDict(
        env_prefix="PLATFORM_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        # Unknown PLATFORM_* variables are a typo or a stale setting. Failing at
        # startup surfaces them; ignoring them means a misspelled variable is
        # silently ineffective and the operator never finds out.
        extra="forbid",
        frozen=True,
        validate_default=True,
    )

    app: AppSettings = Field(default_factory=AppSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    telemetry: TelemetrySettings = Field(default_factory=TelemetrySettings)
    features: FeatureFlagSettings = Field(default_factory=FeatureFlagSettings)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Substitute the namespace-filtering dotenv source.

        Source order is precedence, highest first, and matches the hierarchy in
        ``architecture.md`` §71: explicit arguments, then the process
        environment, then the ``.env`` file, then defaults declared on the
        models. Key Vault is inserted ahead of the dotenv source in Milestone 05.
        """
        return (
            init_settings,
            env_settings,
            _NamespacedDotEnvSource(settings_cls),
            file_secret_settings,
        )

    @model_validator(mode="after")
    def enforce_environment_invariants(self) -> Self:
        """Reject configurations that are unsafe for the declared environment.

        These are startup failures by design ("Fail Fast"). Each one is a
        mistake that is silent in testing and damaging in production, so it is
        better to refuse to boot than to serve traffic misconfigured.
        """
        if not self.app.environment.is_production_like:
            return self

        errors: list[str] = []

        if self.app.debug:
            errors.append(
                "app.debug must be false outside development — it exposes API docs "
                "and internal error detail."
            )

        if self.logging.renderer != "json":
            errors.append(
                "logging.renderer must be 'json' outside development — console output "
                "is not machine-parsable and breaks log analytics."
            )

        if "*" in self.server.cors_origins:
            errors.append(
                "server.cors_origins must not contain '*' outside development — "
                "list the permitted origins explicitly."
            )

        if not self.server.cors_origins:
            errors.append(
                "server.cors_origins must not be empty outside development — "
                "the frontend origin must be listed."
            )

        if errors:
            raise ValueError("Invalid configuration:\n  - " + "\n  - ".join(errors))

        return self


@lru_cache(maxsize=1)
def get_settings() -> PlatformSettings:
    """Return the process-wide settings instance.

    Cached so that configuration is read and validated exactly once. Tests that
    need different values must call ``get_settings.cache_clear()`` first —
    exposed deliberately rather than hidden, so the cache is visible to anyone
    who has to work around it.
    """
    return PlatformSettings()
