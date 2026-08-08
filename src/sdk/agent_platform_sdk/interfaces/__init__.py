"""Provider and registry contracts.

Every abstraction named in ``CLAUDE.md`` under "Always use interfaces" lives
here. Implementations live in ``agent_platform.providers`` and are wired in the
composition root — business logic depends on these names and nothing else.

All contracts are :class:`typing.Protocol` declarations. See
``docs/adr/0004-provider-abstraction-via-protocols.md`` for why.
"""

from agent_platform_sdk.interfaces.embedding_provider import EmbeddingProvider
from agent_platform_sdk.interfaces.evaluation_provider import EvaluationProvider
from agent_platform_sdk.interfaces.llm_gateway import LLMGateway
from agent_platform_sdk.interfaces.llm_provider import LLMProvider
from agent_platform_sdk.interfaces.llm_provider_resolver import LLMProviderResolver
from agent_platform_sdk.interfaces.memory_provider import MemoryProvider
from agent_platform_sdk.interfaces.prompt_provider import PromptProvider
from agent_platform_sdk.interfaces.provider import Provider
from agent_platform_sdk.interfaces.registry import Registry
from agent_platform_sdk.interfaces.search_provider import SearchProvider
from agent_platform_sdk.interfaces.tool_provider import ToolProvider
from agent_platform_sdk.interfaces.vector_store_provider import (
    VectorRecord,
    VectorStoreProvider,
)

__all__ = [
    "EmbeddingProvider",
    "EvaluationProvider",
    "LLMGateway",
    "LLMProvider",
    "LLMProviderResolver",
    "MemoryProvider",
    "PromptProvider",
    "Provider",
    "Registry",
    "SearchProvider",
    "ToolProvider",
    "VectorRecord",
    "VectorStoreProvider",
]
