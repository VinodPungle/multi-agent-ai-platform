"""Mock inference provider.

A real :class:`~agent_platform_sdk.interfaces.llm_provider.LLMProvider` that
generates its answers locally instead of calling a model. It exists so the chat
experience, the streaming pipeline, session memory and the LLM Gateway can be
built and tested before Azure AI Foundry arrives in Milestone 05.

It is a *provider*, not a stub bolted onto the service layer. That distinction
matters: routing it through the gateway like any other provider is what proves
the gateway works, and it means Milestone 05 adds a provider rather than
replacing a special case.

Never registered outside development and testing — see
``MockProviderSettings.enabled`` and the environment guard in the composition
root.
"""

from agent_platform.providers.mock.mock_llm_provider import MockLLMProvider

__all__ = ["MockLLMProvider"]
