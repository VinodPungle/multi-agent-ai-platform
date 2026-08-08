"""Registries — the authoritative catalogues the runtime resolves through.

Responsibility
    Registration, discovery, validation and metadata lookup for agents, models,
    providers, tools, prompts and memory (``architecture.md`` §26-§27).

Design rule
    Registries never execute business logic. They answer "what exists and what
    can it do"; factories turn those answers into instances.

Why the aliases below rather than six classes
    All six registries have identical behaviour and differ only in what they
    hold, so they are one generic implementation at six type parameters. The
    aliases exist to make signatures read as intent — ``AgentRegistry`` rather
    than ``KeyedRegistry[Agent]`` — and to give mypy something to check a
    misuse against.
"""

from agent_platform.registries.keyed_registry import KeyedRegistry
from agent_platform_sdk.dto.model import ModelDescriptor
from agent_platform_sdk.dto.tool import ToolDescriptor
from agent_platform_sdk.interfaces.agent import Agent
from agent_platform_sdk.interfaces.llm_provider import LLMProvider
from agent_platform_sdk.interfaces.memory_provider import MemoryProvider

#: Agents available for execution, keyed by ``agent_id``.
type AgentRegistry = KeyedRegistry[Agent]

#: Inference providers, keyed by ``provider_id``.
type ProviderRegistry = KeyedRegistry[LLMProvider]

#: The authoritative model catalogue, keyed by ``model_id``
#: (``architecture.md`` §30). The runtime obtains model information from here
#: and nowhere else, so repricing or withdrawing a model is a data change.
type ModelRegistry = KeyedRegistry[ModelDescriptor]

#: Memory backends, keyed by ``provider_id``.
type MemoryRegistry = KeyedRegistry[MemoryProvider]

#: Tool metadata, keyed by ``tool_id``. Registered from Milestone 04; the
#: registry exists now so the runtime's tool-resolution path is present and
#: empty rather than absent and later inserted.
type ToolRegistry = KeyedRegistry[ToolDescriptor]

__all__ = [
    "AgentRegistry",
    "KeyedRegistry",
    "MemoryRegistry",
    "ModelRegistry",
    "ProviderRegistry",
    "ToolRegistry",
]
