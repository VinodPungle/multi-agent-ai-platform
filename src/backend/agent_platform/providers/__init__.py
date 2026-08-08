"""Infrastructure implementations of the SDK provider interfaces.

Responsibility
    The **only** package in which a vendor SDK may be imported: Azure AI Foundry,
    Azure OpenAI, Anthropic, Gemini, DeepSeek, OpenRouter, Ollama, vLLM.

Dependency rule
    Provider SDK types must not escape this package. Every adapter translates
    vendor payloads into ``agent_platform_sdk`` contracts at its boundary. That
    translation is what keeps the rest of the platform provider-agnostic.

    Concretely, nothing outside this package may name an Azure SDK class, an
    HTTP response object or a vendor exception. Provider-side detail that is
    worth keeping travels as strings in ``CompletionResponse.provider_metadata``.

Scope of a provider
    Translation, transport, authentication, tokenisation, and mapping vendor
    failures onto the platform exception hierarchy. Nothing else. Retry,
    timeout, telemetry, cost estimation and provider selection belong to
    ``agent_platform.gateway`` — written once, not once per vendor.

Filled in from Milestone 05 (Azure AI Foundry + Gemma 4).
"""
