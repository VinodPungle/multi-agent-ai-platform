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
from decimal import Decimal
from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from pydantic_settings.sources import DotEnvSettingsSource, PydanticBaseSettingsSource

from agent_platform_sdk.policies.retry import RetryPolicy
from agent_platform_sdk.policies.timeout import TimeoutPolicy

__all__ = [
    "AgentSettings",
    "AppSettings",
    "AzureFoundrySettings",
    "ChatSettings",
    "Environment",
    "FeatureFlagSettings",
    "LLMGatewaySettings",
    "LoggingSettings",
    "MemorySettings",
    "MockProviderSettings",
    "PlatformSettings",
    "SearchSettings",
    "ServerSettings",
    "TelemetrySettings",
    "WorkflowSettings",
    "get_settings",
]

# The system prompt used to live here as a constant. It now lives in
# `prompts/agents/chat/system.md` as a versioned asset, which is what
# `CLAUDE.md` requires of every prompt — a prompt in a Python file can only be
# changed by shipping a release.


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


class LLMGatewaySettings(BaseModel):
    """Policy the LLM Gateway applies to every model call.

    Externalised here rather than defaulted in the gateway so that a deployment
    can tighten a timeout or widen a retry budget without a code change
    (``CLAUDE.md``, "Never hardcode"). The policy models themselves live in the
    SDK, so a future service that talks to providers applies the same shapes.

    Nothing here names a provider or a vendor: these are platform policies, and
    they read identically for Azure AI Foundry and for any OpenAI-compatible
    endpoint added later.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    default_provider_id: str | None = Field(
        default=None,
        description=(
            "Provider used when a request does not pin one. Optional while a single "
            "provider is registered; required once there is more than one, because "
            "guessing between them is a routing decision the platform must not make."
        ),
    )
    retry: RetryPolicy = Field(
        default_factory=RetryPolicy,
        description="Attempts and backoff for non-streaming model calls.",
    )
    timeout: TimeoutPolicy = Field(
        default_factory=TimeoutPolicy,
        description="Per-hop wall-clock budgets.",
    )


class MemorySettings(BaseModel):
    """Conversation memory configuration.

    ``provider`` is a literal with one member today. Declared as a choice rather
    than assumed, so adding Redis is a new member plus a factory branch — not a
    new configuration shape that every deployment has to learn.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: Literal["in-memory"] = Field(
        default="in-memory",
        description="Memory backend. Redis, PostgreSQL and Cosmos DB join this list later.",
    )
    max_conversations: int = Field(
        default=500,
        gt=0,
        description=(
            "Conversations held before the least recently used is evicted. A cap is "
            "mandatory, not tuning: an unbounded store fed by an HTTP endpoint lets "
            "anyone who can send requests exhaust the process's memory."
        ),
    )
    max_messages_per_conversation: int = Field(
        default=200,
        gt=0,
        description="Messages kept per conversation. Oldest are dropped first.",
    )


class MockProviderSettings(BaseModel):
    """The development provider that answers without calling a model.

    Rejected in staging and production by
    :meth:`PlatformSettings.enforce_environment_invariants`. A deployment that
    silently served templated answers to real users would be far worse than one
    that refuses to start.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = Field(
        default=False,
        description=(
            "Register the mock provider. Development and testing only. Defaults to false "
            "so that the unsafe state is always the one someone chose explicitly — the "
            "same posture as `app.debug`. Enabled in `.env.example` and in Compose, so "
            "every documented local path still works with no manual step."
        ),
    )
    provider_id: str = Field(default="mock", min_length=1)
    model_id: str = Field(default="mock-echo", min_length=1)
    chunk_delay_seconds: float = Field(
        default=0.02,
        ge=0.0,
        le=5.0,
        description=(
            "Pause between streamed chunks. Non-zero by default because a stream that "
            "arrives instantly hides every bug that only appears when tokens trickle."
        ),
    )


class AzureFoundrySettings(BaseModel):
    """Azure AI Foundry connection and model metadata.

    No API key appears here, and none is accepted. Authentication is
    `DefaultAzureCredential` — Azure CLI locally, Managed Identity in Azure —
    which is what `CLAUDE.md` requires and what removes the whole class of
    "secret committed to the repository" incidents.

    Model identity is configuration end to end: `deployment` selects what
    answers, and nothing in the source names a model. Pointing the platform at
    Gemma 4, GPT, DeepSeek or Cohere is an environment variable.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = Field(
        default=False,
        description=(
            "Register the Azure AI Foundry provider. Defaults to false so a clone "
            "with no Azure access starts cleanly; the deployment that needs it "
            "turns it on, in the same posture as `app.debug`."
        ),
    )
    endpoint: str = Field(
        default="",
        description=(
            "Foundry inference endpoint, e.g. "
            "https://<resource>.services.ai.azure.com/models — copied from the "
            "Foundry portal. A resource identifier, not a secret."
        ),
    )
    deployment: str = Field(
        default="",
        description=(
            "Deployment name to invoke. This is the *deployment* name from the "
            "portal, which is frequently not the model name — the single most "
            "common cause of a 404 here."
        ),
    )
    model_id: str = Field(
        default="gemma-4",
        min_length=1,
        description="Platform-wide model id this deployment serves.",
    )
    provider_id: str = Field(default="azure-foundry", min_length=1)

    max_context_tokens: int = Field(default=128_000, gt=0)
    max_output_tokens: int = Field(default=4_096, gt=0)

    supports_tools: bool = Field(
        default=True,
        description=(
            "Whether the deployed model can call tools. Varies by model, not by "
            "provider: claiming it for a model that ignores tool definitions "
            "would route tool work into silence."
        ),
    )

    output_token_parameter: Literal["max_tokens", "max_completion_tokens"] = Field(
        default="max_tokens",
        description=(
            "Which parameter caps generated tokens. Reasoning models reject "
            "`max_tokens` outright and require `max_completion_tokens` — a live "
            "call returned HTTP 400 where every mock had accepted it."
        ),
    )

    input_cost_per_million_tokens: Decimal = Field(
        default=Decimal(0),
        ge=0,
        description=(
            "Published input rate. Defaults to zero so an unconfigured deployment "
            "reports zero cost rather than a fabricated number that would reach "
            "cost dashboards looking real."
        ),
    )
    output_cost_per_million_tokens: Decimal = Field(default=Decimal(0), ge=0)

    cold_start_timeout_seconds: float = Field(
        default=120.0,
        gt=0,
        description=(
            "Budget for the first request to a Managed Compute deployment that has "
            "scaled to zero. Generous on purpose: an instance start takes tens of "
            "seconds, and a tight timeout makes every cold start look like an outage."
        ),
    )

    @model_validator(mode="after")
    def _require_connection_details_when_enabled(self) -> Self:
        """Fail at startup when the provider is on but unconfigured.

        The alternative is a platform that starts happily and fails every chat
        request with a connection error that names nothing useful.
        """
        if not self.enabled:
            return self

        missing = [
            name
            for name, value in (("endpoint", self.endpoint), ("deployment", self.deployment))
            if not value.strip()
        ]
        if missing:
            fields = ", ".join(f"azure_foundry.{name}" for name in missing)
            message = f"Azure AI Foundry is enabled but {fields} is not set."
            raise ValueError(message)

        return self


class SearchSettings(BaseModel):
    """Which search backend answers the internet-search tool.

    `mock` returns fabricated results with no network call, which is what CI and
    an offline laptop need. `duckduckgo` performs a real, keyless search.

    Chosen as a literal rather than assumed, so adding a keyed provider (Brave,
    Tavily, Bing) is a new member plus a factory branch — not a new configuration
    shape every deployment has to learn.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: Literal["mock", "duckduckgo"] = Field(
        default="duckduckgo",
        description=(
            "Search backend. `duckduckgo` needs no API key, so the documented local "
            "setup performs real searches with no signup."
        ),
    )
    timeout_seconds: float = Field(
        default=10.0,
        gt=0,
        le=120,
        description=(
            "Whole-request budget for one search. Bounded deliberately: an unbounded "
            "search holds a chat turn open for as long as the upstream cares to take."
        ),
    )
    max_results: int = Field(
        default=5,
        gt=0,
        le=10,
        description=(
            "Default results per search. Every result is spent context in the next "
            "prompt, so this is a cost setting as much as a quality one."
        ),
    )


class WorkflowSettings(BaseModel):
    """Which engine orchestrates agent execution.

    Two implementations of one protocol. `direct` runs an agent with no graph
    library involved, which is both a reference implementation and a way to rule
    orchestration out when diagnosing a problem.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    engine: Literal["langgraph", "direct"] = Field(
        default="langgraph",
        description="Workflow engine. Both satisfy the same contract.",
    )


class AgentSettings(BaseModel):
    """The chat agent's descriptor, as configuration.

    ``architecture.md`` §17 requires agent definitions to be data rather than
    code: changing an agent's model, prompt or budget must never mean editing a
    Python file. This is the first agent, so its descriptor is assembled from
    these fields. A registry loaded from YAML descriptors replaces it once there
    is more than one agent to declare.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_id: str = Field(default="chat-agent", min_length=1)
    provider_id: str = Field(
        default="mock",
        min_length=1,
        description="Default provider, resolved through the provider registry.",
    )
    model_id: str = Field(
        default="mock-echo",
        min_length=1,
        description=(
            "Model requested for every turn. Changing provider or model is a "
            "configuration change; no source file names a model."
        ),
    )
    prompt_id: str = Field(
        default="chat-agent-system",
        min_length=1,
        description="Prompt asset id, resolved through the prompt provider.",
    )
    prompt_version: str | None = Field(
        default=None,
        description=(
            "Pinned prompt version. None selects the newest. Pin one for "
            "reproducible behaviour across a prompt change."
        ),
    )
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_output_tokens: int | None = Field(default=None, gt=0)
    # `NoDecode` for the same reason as `ServerSettings.cors_origins`, and this
    # is the third time the trap has been hit: for a collection field,
    # `pydantic-settings` runs `json.loads` on the raw environment value *before*
    # any validator, so a comma-separated list raises `SettingsError` at startup
    # and never reaches the validator below.
    tool_ids: Annotated[tuple[str, ...], NoDecode] = Field(
        default=("internet-search",),
        description=(
            "Tools this agent may call. A tool the deployment has not registered "
            "is skipped with a warning rather than failing the agent, so one "
            "descriptor works across environments that register different tools."
        ),
    )

    @field_validator("tool_ids", mode="before")
    @classmethod
    def _split_comma_separated(cls, value: object) -> object:
        """Accept a comma-separated string as well as a list."""
        if isinstance(value, str):
            return tuple(part.strip() for part in value.split(",") if part.strip())
        return value

    max_tool_invocations: int | None = Field(
        default=4,
        gt=0,
        description=(
            "Tool calls allowed in one turn. Enforced between iterations of the "
            "tool loop, where stopping still saves the next call."
        ),
    )
    max_model_calls: int | None = Field(
        default=4,
        gt=0,
        description="Model calls allowed in one turn, bounding the tool loop.",
    )


class ChatSettings(BaseModel):
    """Chat behaviour that is a deployment decision rather than a code one."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_id: str = Field(
        default="chat-agent",
        min_length=1,
        description=(
            "Agent that answers chat turns. Pointing chat at a different agent "
            "is a configuration change."
        ),
    )
    max_prompt_characters: int = Field(
        default=32_000,
        gt=0,
        description=(
            "Rejection threshold for one message. Characters rather than tokens because "
            "no tokeniser is available before a provider is chosen; the model registry "
            "enforces the real context window."
        ),
    )
    prompts_directory: str = Field(
        default="prompts",
        min_length=1,
        description=(
            "Root of the versioned prompt assets, relative to the working directory "
            "or absolute. Prompts are deployed artefacts, loaded once at startup."
        ),
    )


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
    llm_gateway: LLMGatewaySettings = Field(default_factory=LLMGatewaySettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    workflow: WorkflowSettings = Field(default_factory=WorkflowSettings)
    search: SearchSettings = Field(default_factory=SearchSettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    mock_provider: MockProviderSettings = Field(default_factory=MockProviderSettings)
    azure_foundry: AzureFoundrySettings = Field(default_factory=AzureFoundrySettings)
    chat: ChatSettings = Field(default_factory=ChatSettings)
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

        if self.mock_provider.enabled:
            errors.append(
                "mock_provider.enabled must be false outside development — it answers "
                "with templated text instead of calling a model, and a deployment that "
                "served those answers to real users would look like a working system."
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
