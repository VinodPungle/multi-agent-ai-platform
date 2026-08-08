"""LLM Gateway — the platform's single path to model inference.

Responsibility
    Everything that is identical for every provider: request normalisation,
    response normalisation, provider selection, retry policy, timeout policy,
    telemetry and cost estimation (``architecture.md`` §30).

Dependency rule
    Provider independent. This package imports the SDK contracts and nothing
    from ``agent_platform.providers``. A provider arrives injected, resolved
    through :class:`~agent_platform_sdk.interfaces.llm_provider_resolver.LLMProviderResolver`.

    ``import azure`` here would be as much a violation as it would be in the
    runtime — the gateway exists precisely so that no such import is ever needed
    outside a provider package.

Consumers depend on
    :class:`~agent_platform_sdk.interfaces.llm_gateway.LLMGateway`, never on
    :class:`DefaultLLMGateway`.
"""

from agent_platform.gateway.llm_gateway import DefaultLLMGateway
from agent_platform.gateway.provider_resolver import ConfiguredProviderResolver

__all__ = ["ConfiguredProviderResolver", "DefaultLLMGateway"]
