"""Infrastructure implementations of the SDK provider interfaces.

Responsibility
    The **only** package in which a vendor SDK may be imported: Azure AI Foundry,
    Azure OpenAI, Anthropic, Gemini, DeepSeek, OpenRouter, Ollama, vLLM.

Dependency rule
    Provider SDK types must not escape this package. Every adapter translates
    vendor payloads into ``agent_platform_sdk`` contracts at its boundary. That
    translation is what keeps the rest of the platform provider-agnostic.

Filled in from Milestone 05 (Azure AI Foundry + Gemma 4).
"""
