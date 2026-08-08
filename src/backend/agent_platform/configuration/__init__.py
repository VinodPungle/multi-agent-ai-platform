"""Configuration layer.

Responsibility
    Own every configuration value the platform reads, expose it as strongly
    typed immutable models, and validate it once at startup.

Design rule
    Nothing outside this package reads the environment. Modules receive a
    :class:`PlatformSettings` instance through dependency injection, which makes
    configuration a declared dependency instead of a hidden one.
"""

from agent_platform.configuration.settings import (
    AppSettings,
    Environment,
    FeatureFlagSettings,
    LoggingSettings,
    PlatformSettings,
    ServerSettings,
    TelemetrySettings,
    get_settings,
)

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
