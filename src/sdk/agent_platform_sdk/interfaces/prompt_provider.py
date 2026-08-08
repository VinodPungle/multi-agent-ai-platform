"""Prompt provider contract.

Prompts are loaded through this interface rather than read from disk directly,
so the source can move from the filesystem to a database or a prompt marketplace
without touching a single agent.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent_platform_sdk.dto.prompt import PromptAsset
from agent_platform_sdk.interfaces.provider import Provider

__all__ = ["PromptProvider"]


@runtime_checkable
class PromptProvider(Provider, Protocol):
    """Loading and versioning of prompt assets."""

    async def get(self, prompt_id: str, version: str | None = None) -> PromptAsset:
        """Return a prompt asset.

        ``version=None`` selects the current version. Agents that need
        reproducible behaviour pin an explicit version.

        Raises:
            NotFoundError: when the prompt or the requested version is unknown.
        """
        ...

    async def list_versions(self, prompt_id: str) -> tuple[str, ...]:
        """Return the available versions of a prompt, newest first.

        Required for rollback: an operator must be able to see what they can
        roll back to without inspecting storage directly.
        """
        ...
