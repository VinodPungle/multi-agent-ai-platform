"""Discovery endpoints for agents, tools and models.

Read-only views of the three registries the platform builds at startup. They
answer the question an operator asks before anything else — *what is actually
registered in this deployment?* — without shelling into a container or reading
the configuration that was supposed to produce it.

That distinction matters: these report what the registries **hold**, not what
configuration asked for. A tool disabled by a feature flag is absent here, and
that absence is the answer.

What is deliberately not exposed
    Endpoints, deployment names and prompt file locations. They are
    infrastructure detail: knowing a model is served from a particular Foundry
    resource helps an attacker enumerate and helps an operator not at all, and
    ``CLAUDE.md`` is explicit that internal implementation details stay off the
    public API.

    Prices *are* exposed. They are published rates rather than secrets, and
    without them the cost figures elsewhere cannot be checked.

No mutation, and not because it was rushed
    Registering an agent at runtime would make the running platform differ from
    its configuration, which is the property that makes a deployment
    reproducible. Agents, tools and models arrive from configuration and
    providers; this surface reports them.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from agent_platform.dependencies.providers import (
    AgentRegistryDep,
    ModelRegistryDep,
    ToolRegistryDep,
)

__all__ = ["AgentSummary", "ModelSummary", "ToolSummary", "router"]

router = APIRouter(tags=["catalogue"])


class AgentSummary(BaseModel):
    """One registered agent, as an operator needs to see it."""

    model_config = ConfigDict(frozen=True)

    agent_id: str
    name: str
    description: str
    version: str
    owner: str | None = None
    provider_id: str = Field(description="Provider the agent is configured to use.")
    model_id: str = Field(
        description=(
            "Model the agent asks for. A *preference*: routing policy may choose "
            "another, and the model that actually answered is on each response."
        ),
    )
    tool_ids: tuple[str, ...] = Field(
        default=(),
        description="Tools this agent may call. Absent from the tool list means unavailable.",
    )
    temperature: float | None = None
    max_output_tokens: int | None = None
    is_enabled: bool


class ToolSummary(BaseModel):
    """One registered tool."""

    model_config = ConfigDict(frozen=True)

    tool_id: str
    description: str = Field(
        description="The text sent to models. It is prompt material, not documentation."
    )
    version: str
    owner: str | None = None
    parameters: tuple[str, ...] = Field(
        default=(),
        description="Argument names, from the tool's input schema.",
    )
    required_parameters: tuple[str, ...] = Field(default=())
    timeout_seconds: float
    max_attempts: int = Field(
        description=(
            "Retries the runtime allows. One means none: a tool that may have "
            "side effects is never retried automatically."
        ),
    )
    is_available: bool


class ModelSummary(BaseModel):
    """One model in the catalogue."""

    model_config = ConfigDict(frozen=True)

    model_id: str
    provider_id: str
    display_name: str
    version: str | None = None
    capabilities: tuple[str, ...] = Field(
        default=(),
        description="What the model declares. Routing filters on these, never on provider name.",
    )
    max_context_tokens: int
    max_output_tokens: int
    input_cost_per_million_tokens: Decimal
    output_cost_per_million_tokens: Decimal
    currency: str
    is_available: bool = Field(
        description="False withdraws a model from routing without deleting its configuration.",
    )


@router.get(
    "/agents",
    response_model=tuple[AgentSummary, ...],
    summary="Registered agents",
    description=(
        "Every agent this deployment can run, in registration order. Reports what the "
        "registry holds rather than what configuration requested."
    ),
)
async def list_agents(agents: AgentRegistryDep) -> tuple[AgentSummary, ...]:
    """Return the registered agents."""
    return tuple(
        AgentSummary(
            agent_id=descriptor.agent_id,
            name=descriptor.name,
            description=descriptor.description,
            version=descriptor.version,
            owner=descriptor.owner,
            provider_id=descriptor.provider_id,
            model_id=descriptor.model_id,
            tool_ids=descriptor.tool_ids,
            temperature=descriptor.temperature,
            max_output_tokens=descriptor.max_output_tokens,
            is_enabled=descriptor.is_enabled,
        )
        for _, agent in agents.items()
        if (descriptor := agent.descriptor)
    )


@router.get(
    "/tools",
    response_model=tuple[ToolSummary, ...],
    summary="Registered tools",
    description=(
        "Every tool the runtime can execute, local or remote. A tool disabled by a "
        "feature flag is absent rather than listed as unavailable."
    ),
)
async def list_tools(tools: ToolRegistryDep) -> tuple[ToolSummary, ...]:
    """Return the registered tools."""
    summaries: list[ToolSummary] = []

    for _, tool in tools.items():
        descriptor = tool.descriptor
        schema = descriptor.input_schema
        properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
        required = schema.get("required", []) if isinstance(schema, dict) else []

        summaries.append(
            ToolSummary(
                tool_id=descriptor.tool_id,
                description=descriptor.description,
                version=descriptor.version,
                owner=descriptor.owner,
                # Read defensively: an MCP server supplies its own schema and
                # may not shape it the way a local tool does.
                parameters=tuple(properties) if isinstance(properties, dict) else (),
                required_parameters=tuple(required) if isinstance(required, list) else (),
                timeout_seconds=descriptor.timeout_seconds,
                max_attempts=descriptor.retry_policy.max_attempts,
                is_available=descriptor.is_available,
            )
        )

    return tuple(summaries)


@router.get(
    "/models",
    response_model=tuple[ModelSummary, ...],
    summary="Model catalogue",
    description=(
        "Every model a registered provider advertises, with the published prices cost "
        "estimates are computed from. Populated at startup from each provider, so it "
        "cannot list a model nothing can serve."
    ),
)
async def list_models(models: ModelRegistryDep) -> tuple[ModelSummary, ...]:
    """Return the model catalogue."""
    return tuple(
        ModelSummary(
            model_id=model.model_id,
            provider_id=model.provider_id,
            display_name=model.display_name,
            version=model.version,
            capabilities=tuple(sorted(capability.value for capability in model.capabilities)),
            max_context_tokens=model.max_context_tokens,
            max_output_tokens=model.max_output_tokens,
            input_cost_per_million_tokens=model.pricing.input_cost_per_million_tokens,
            output_cost_per_million_tokens=model.pricing.output_cost_per_million_tokens,
            currency=model.pricing.currency,
            is_available=model.is_available,
        )
        for _, model in models.items()
    )
