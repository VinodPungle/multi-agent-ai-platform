"""Azure AI Foundry provider.

The platform's first production inference provider, and the only package
besides ``agent_platform.security.credentials`` permitted to import ``azure.*``.

Every Azure type is converted at this boundary. What leaves is
``CompletionResponse``, ``CompletionChunk``, ``ComponentHealth`` and
``ProviderError`` — all provider-neutral, so nothing downstream can tell which
provider answered except as data on the response.
"""

from agent_platform.providers.azure_foundry.azure_foundry_provider import (
    AzureFoundryProvider,
)

__all__ = ["AzureFoundryProvider"]
