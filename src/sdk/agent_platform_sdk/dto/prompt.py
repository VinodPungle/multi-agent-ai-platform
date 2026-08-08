"""Prompt asset contracts.

Prompts are versioned assets, never string literals in Python (``CLAUDE.md``).
Treating them as data is what later enables prompt evaluation, A/B testing and
rollback without a code deployment.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["PromptAsset", "PromptVariable"]


class PromptVariable(BaseModel):
    """A placeholder a prompt template expects to be filled."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(description="Variable name as it appears in the template.")
    description: str = Field(default="", description="What the caller should supply.")
    required: bool = Field(default=True)


class PromptAsset(BaseModel):
    """A versioned prompt loaded from ``/prompts``.

    ``template`` holds the raw text. Rendering is deliberately not part of this
    contract: the registry owns loading and versioning, and the rendering
    strategy can change without altering the asset shape.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt_id: str = Field(description="Stable identifier, e.g. 'chat-agent-system'.")
    version: str = Field(description="Asset version. Pinned by agents for reproducibility.")
    owner: str | None = Field(default=None, description="Team accountable for the prompt.")
    description: str = Field(default="")
    template: str = Field(description="Raw prompt text, including variable placeholders.")
    variables: tuple[PromptVariable, ...] = Field(default=())
    compatible_models: tuple[str, ...] = Field(
        default=(),
        description="Models this prompt is validated against. Empty means unrestricted.",
    )
    updated_at: datetime | None = Field(default=None)
