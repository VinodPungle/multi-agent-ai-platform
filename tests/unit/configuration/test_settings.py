"""Configuration validation.

Milestone 01 acceptance criteria: "Configuration validates at startup" and
"Configuration fails for invalid required values".

These tests are the executable form of the Fail Fast principle. Each one pins a
misconfiguration that is silent in development and damaging in production.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest
from pydantic import ValidationError as PydanticValidationError

from agent_platform.configuration.settings import (
    AppSettings,
    Environment,
    LoggingSettings,
    PlatformSettings,
    ServerSettings,
    TelemetrySettings,
    get_settings,
)

pytestmark = pytest.mark.unit


class TestDefaults:
    """A bare configuration must be valid and safe."""

    def test_defaults_are_valid(self) -> None:
        settings = PlatformSettings()

        assert settings.app.environment is Environment.DEVELOPMENT
        assert settings.app.debug is False
        assert settings.server.port == 8000

    def test_all_feature_flags_default_to_off(self) -> None:
        """No capability may switch itself on. Milestone 01 registers none."""
        assert PlatformSettings().features.as_dict() == {
            "streaming": False,
            "memory": False,
            "search": False,
            "evaluation": False,
            "cost_tracking": False,
        }

    def test_settings_are_immutable(self) -> None:
        """Configuration must not change after startup.

        A value that can be mutated at runtime cannot be trusted from a log line
        that recorded it earlier.
        """
        settings = PlatformSettings()

        with pytest.raises(PydanticValidationError):
            settings.app = AppSettings()


class TestFieldValidation:
    """Individual fields reject values that cannot work."""

    @pytest.mark.parametrize("port", [0, -1, 65536, 99999])
    def test_port_outside_valid_range_is_rejected(self, port: int) -> None:
        with pytest.raises(PydanticValidationError):
            ServerSettings(port=port)

    @pytest.mark.parametrize("ratio", [-0.1, 1.1, 2.0])
    def test_sample_ratio_outside_zero_to_one_is_rejected(self, ratio: float) -> None:
        with pytest.raises(PydanticValidationError):
            TelemetrySettings(sample_ratio=ratio)

    def test_unknown_log_level_is_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            LoggingSettings(level="TRACE")  # type: ignore[arg-type]  # invalid on purpose

    def test_log_level_is_case_insensitive(self) -> None:
        """Operators type lowercase levels; rejecting them helps nobody."""
        assert LoggingSettings(level="debug").level == "DEBUG"  # type: ignore[arg-type]

    def test_unknown_environment_is_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            AppSettings(environment="prod")  # type: ignore[arg-type]  # not a member

    def test_unknown_setting_is_rejected(self) -> None:
        """A typo must fail loudly rather than be silently ignored."""
        with pytest.raises(PydanticValidationError):
            ServerSettings(prot=8080)  # type: ignore[call-arg]  # deliberate typo


class TestCorsOriginParsing:
    """CORS origins arrive as a single string from every deployment surface."""

    def test_comma_separated_string_becomes_a_tuple(self) -> None:
        settings = ServerSettings(
            cors_origins="http://localhost:5173,https://app.example.com"  # type: ignore[arg-type]
        )

        assert settings.cors_origins == (
            "http://localhost:5173",
            "https://app.example.com",
        )

    def test_whitespace_and_empty_entries_are_dropped(self) -> None:
        settings = ServerSettings(
            cors_origins=" http://a.test , , https://b.test "  # type: ignore[arg-type]
        )

        assert settings.cors_origins == ("http://a.test", "https://b.test")


class TestApiPrefixNormalisation:
    """The prefix is concatenated with a version segment, so its shape matters."""

    @pytest.mark.parametrize(
        ("supplied", "expected"),
        [("api", "/api"), ("/api/", "/api"), ("/api", "/api"), (" /api ", "/api")],
    )
    def test_prefix_is_normalised(self, supplied: str, expected: str) -> None:
        assert ServerSettings(api_prefix=supplied).api_prefix == expected


class TestProductionInvariants:
    """Configurations that are unsafe in production must prevent startup."""

    @pytest.mark.parametrize(
        "environment",
        [Environment.STAGING, Environment.PRODUCTION],
    )
    def test_debug_is_rejected_in_production_like_environments(
        self, environment: Environment
    ) -> None:
        """Debug exposes API docs and internal error detail."""
        with pytest.raises(PydanticValidationError, match=r"app\.debug must be false"):
            PlatformSettings(
                app=AppSettings(environment=environment, debug=True),
                logging=LoggingSettings(renderer="json"),
            )

    def test_console_logging_is_rejected_in_production(self) -> None:
        """Console output is not machine-parsable and breaks log analytics."""
        with pytest.raises(PydanticValidationError, match=r"logging\.renderer must be 'json'"):
            PlatformSettings(
                app=AppSettings(environment=Environment.PRODUCTION),
                logging=LoggingSettings(renderer="console"),
            )

    def test_wildcard_cors_origin_is_rejected_in_production(self) -> None:
        with pytest.raises(PydanticValidationError, match=r"must not contain '\*'"):
            PlatformSettings(
                app=AppSettings(environment=Environment.PRODUCTION),
                server=ServerSettings(cors_origins=("*",)),
            )

    def test_empty_cors_origins_are_rejected_in_production(self) -> None:
        with pytest.raises(PydanticValidationError, match="must not be empty"):
            PlatformSettings(
                app=AppSettings(environment=Environment.PRODUCTION),
                server=ServerSettings(cors_origins=()),
            )

    def test_every_violation_is_reported_at_once(self) -> None:
        """All problems surface together, so a fix is one cycle rather than four."""
        with pytest.raises(PydanticValidationError) as exc_info:
            PlatformSettings(
                app=AppSettings(environment=Environment.PRODUCTION, debug=True),
                server=ServerSettings(cors_origins=("*",)),
                logging=LoggingSettings(renderer="console"),
            )

        message = str(exc_info.value)
        assert "app.debug" in message
        assert "logging.renderer" in message
        assert "cors_origins" in message

    def test_valid_production_configuration_is_accepted(self) -> None:
        settings = PlatformSettings(
            app=AppSettings(environment=Environment.PRODUCTION, debug=False),
            server=ServerSettings(cors_origins=("https://app.example.com",)),
            logging=LoggingSettings(renderer="json"),
        )

        assert settings.app.environment.is_production_like is True

    def test_development_is_not_production_like(self) -> None:
        """Development keeps debug and console logging available."""
        settings = PlatformSettings(
            app=AppSettings(environment=Environment.DEVELOPMENT, debug=True),
            logging=LoggingSettings(renderer="console"),
        )

        assert settings.app.environment.is_production_like is False


class TestEnvironmentVariableBinding:
    """Values must actually arrive from the environment in the documented form."""

    def test_nested_values_bind_through_the_double_underscore_delimiter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PLATFORM_SERVER__PORT", "9001")
        monkeypatch.setenv("PLATFORM_APP__ENVIRONMENT", "staging")
        monkeypatch.setenv("PLATFORM_LOGGING__LEVEL", "warning")

        settings = PlatformSettings()

        assert settings.server.port == 9001
        assert settings.app.environment is Environment.STAGING
        assert settings.logging.level == "WARNING"

    def test_cors_origins_bind_from_a_comma_separated_environment_variable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The form every deployment surface actually supplies.

        Regression test. `pydantic-settings` attempts `json.loads` on a
        collection-typed field before any validator runs, so without `NoDecode`
        this raises `SettingsError` at startup and no validator ever sees the
        value. Constructing `ServerSettings` directly does not exercise that
        path — only binding through the environment does.
        """
        monkeypatch.setenv(
            "PLATFORM_SERVER__CORS_ORIGINS",
            "http://localhost:5173,https://app.example.com",
        )

        assert PlatformSettings().server.cors_origins == (
            "http://localhost:5173",
            "https://app.example.com",
        )

    def test_a_single_cors_origin_binds_from_the_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PLATFORM_SERVER__CORS_ORIGINS", "https://app.example.com")

        assert PlatformSettings().server.cors_origins == ("https://app.example.com",)

    def test_empty_optional_endpoint_is_treated_as_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Container platforms represent 'not configured' as an empty string."""
        monkeypatch.setenv("PLATFORM_TELEMETRY__OTLP_ENDPOINT", "")

        assert PlatformSettings().telemetry.otlp_endpoint is None

    def test_invalid_environment_variable_prevents_construction(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PLATFORM_SERVER__PORT", "not-a-port")

        with pytest.raises(PydanticValidationError):
            PlatformSettings()

    def test_connection_string_is_excluded_from_repr(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A secret must not leak into a stack trace or a debug print."""
        secret = "InstrumentationKey=00000000-0000-0000-0000-000000000000"  # noqa: S105
        monkeypatch.setenv("PLATFORM_TELEMETRY__AZURE_MONITOR_CONNECTION_STRING", secret)

        settings = PlatformSettings()

        assert settings.telemetry.azure_monitor_connection_string == secret
        assert secret not in repr(settings.telemetry)


class TestSharedDotEnvFile:
    """One `.env` at the repository root serves backend, frontend and Compose.

    Regression tests. The default dotenv source hands every key in the file to
    the model, and `extra="forbid"` then rejects the `VITE_*` and port variables
    that legitimately share it — so the application refused to start the moment
    a developer followed the setup guide and copied `.env.example` to `.env`.

    The unit suite missed this entirely because it constructs settings from
    keyword arguments and the environment, never from a file on disk. These
    tests write a real file.
    """

    @staticmethod
    def _write_env_file(directory: Path, contents: str) -> None:
        (directory / ".env").write_text(dedent(contents).lstrip(), encoding="utf-8")

    def test_variables_belonging_to_other_tools_are_ignored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`.env.example` copied verbatim must start the application."""
        self._write_env_file(
            tmp_path,
            """
            PLATFORM_APP__ENVIRONMENT=development
            PLATFORM_SERVER__PORT=8000
            BACKEND_PORT=18000
            FRONTEND_PORT=5173
            VITE_API_BASE_URL=http://localhost:8000
            VITE_APP_NAME=Multi-Agent AI Platform
            """,
        )
        monkeypatch.chdir(tmp_path)

        settings = PlatformSettings()

        assert settings.server.port == 8000
        assert settings.app.environment is Environment.DEVELOPMENT

    def test_platform_values_are_read_from_the_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._write_env_file(
            tmp_path,
            """
            PLATFORM_SERVER__PORT=9100
            PLATFORM_LOGGING__LEVEL=warning
            PLATFORM_SERVER__CORS_ORIGINS=http://a.test,http://b.test
            VITE_APP_NAME=irrelevant
            """,
        )
        monkeypatch.chdir(tmp_path)

        settings = PlatformSettings()

        assert settings.server.port == 9100
        assert settings.logging.level == "WARNING"
        assert settings.server.cors_origins == ("http://a.test", "http://b.test")

    def test_a_misspelled_platform_variable_is_still_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Filtering must not weaken typo detection, which is why `extra` stays forbid."""
        self._write_env_file(tmp_path, "PLATFORM_SERVER__PROT=8080\n")
        monkeypatch.chdir(tmp_path)

        with pytest.raises(PydanticValidationError):
            PlatformSettings()

    def test_the_process_environment_overrides_the_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Precedence per architecture.md §71: environment beats the .env file."""
        self._write_env_file(tmp_path, "PLATFORM_SERVER__PORT=9100\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("PLATFORM_SERVER__PORT", "9200")

        assert PlatformSettings().server.port == 9200


class TestSettingsCache:
    """`get_settings` is memoised, and that must be observable."""

    def test_settings_are_cached_across_calls(self) -> None:
        assert get_settings() is get_settings()

    def test_cache_can_be_cleared(self, monkeypatch: pytest.MonkeyPatch) -> None:
        first = get_settings()
        monkeypatch.setenv("PLATFORM_SERVER__PORT", "9999")

        assert get_settings() is first, "cached value should survive an env change"

        get_settings.cache_clear()

        assert get_settings().server.port == 9999
