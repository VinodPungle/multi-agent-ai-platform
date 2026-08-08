"""Agent descriptor contract.

``architecture.md`` §17 requires agent descriptors to be *external configuration,
not code*. Changing an agent's model, tools or budget must never require editing
a Python file, so everything an agent needs is expressed here as data.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from agent_platform_sdk.policies.budget import BudgetPolicy
from agent_platform_sdk.policies.retry import RetryPolicy
from agent_platform_sdk.policies.timeout import TimeoutPolicy

__all__ = ["AgentDescriptor"]


class AgentDescriptor(BaseModel):
    """Declarative definition of one agent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # --- Identity -----------------------------------------------------------
    agent_id: str = Field(description="Stable identifier, e.g. 'chat-agent'.")
    name: str = Field(description="Human-readable name.")
    description: str = Field(description="What this agent is for.")
    version: str = Field(default="1.0")
    owner: str | None = Field(default=None, description="Team accountable for the agent.")

    # --- Routing ------------------------------------------------------------
    # Provider and model are identifiers resolved through the registries. The
    # agent never imports a provider, so it cannot become coupled to one.
    provider_id: str = Field(description="Default provider, resolved via the provider registry.")
    model_id: str = Field(description="Default model, resolved via the model registry.")
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_output_tokens: int | None = Field(default=None, gt=0)

    # --- Capabilities -------------------------------------------------------
    prompt_id: str = Field(description="Prompt asset id, resolved via the prompt registry.")
    prompt_version: str | None = Field(
        default=None,
        description="Pinned prompt version. None selects the current version.",
    )
    tool_ids: tuple[str, ...] = Field(default=(), description="Tools this agent may use.")
    memory_provider_id: str | None = Field(default=None)
    search_provider_id: str | None = Field(default=None)
    embedding_provider_id: str | None = Field(default=None, description="Future.")
    vector_store_id: str | None = Field(default=None, description="Future.")

    # --- Policies -----------------------------------------------------------
    budget: BudgetPolicy = Field(default_factory=BudgetPolicy)
    timeout: TimeoutPolicy = Field(default_factory=TimeoutPolicy)
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    guardrails: tuple[str, ...] = Field(
        default=(),
        description="Guardrail identifiers applied by the runtime. Future.",
    )

    is_enabled: bool = Field(
        default=True,
        description="Set false to disable an agent by configuration alone.",
    )
