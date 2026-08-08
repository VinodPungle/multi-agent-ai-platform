"""Model catalogue contract.

``architecture.md`` §30 makes the model registry the *only* source of model
information. Endpoint, deployment name, limits and pricing live here as data so
that adding or repricing a model is a configuration change, never a code change.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from agent_platform_sdk.types.enums import Capability

__all__ = ["ModelDescriptor", "ModelPricing"]


class ModelPricing(BaseModel):
    """Pricing metadata used to estimate cost per call.

    Expressed per million tokens because that is how providers publish rates;
    storing the published unit avoids a conversion error at configuration time.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    input_cost_per_million_tokens: Decimal = Field(default=Decimal(0), ge=0)
    output_cost_per_million_tokens: Decimal = Field(default=Decimal(0), ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)


class ModelDescriptor(BaseModel):
    """Everything the runtime needs to know about one model.

    Note that neither an endpoint nor a deployment name is ever hardcoded: both
    arrive here from configuration.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_id: str = Field(description="Stable platform-wide identifier, e.g. 'gemma-4'.")
    provider_id: str = Field(description="Provider that serves this model.")
    display_name: str = Field(description="Human-readable name for operator surfaces.")
    version: str | None = Field(default=None, description="Provider model version.")
    deployment_name: str | None = Field(
        default=None,
        description="Provider-side deployment identifier, where the provider uses one.",
    )
    endpoint: str | None = Field(
        default=None,
        description="Override endpoint. None means the provider's configured default.",
    )

    capabilities: frozenset[Capability] = Field(
        default=frozenset(),
        description="Declared capabilities. Routing checks these, not the provider name.",
    )
    max_context_tokens: int = Field(gt=0, description="Maximum combined prompt + output tokens.")
    max_output_tokens: int = Field(gt=0, description="Maximum tokens the model may generate.")
    default_temperature: float = Field(default=0.2, ge=0.0, le=2.0)

    pricing: ModelPricing = Field(default_factory=ModelPricing)
    recommended_use_cases: tuple[str, ...] = Field(default=())
    is_available: bool = Field(
        default=True,
        description="Set false to withdraw a model from routing without deleting its config.",
    )

    def supports(self, capability: Capability) -> bool:
        """Return whether this model declares ``capability``."""
        return capability in self.capabilities
