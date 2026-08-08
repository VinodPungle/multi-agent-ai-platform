"""Agent Runtime — the heart of the platform (``architecture.md`` §9-§25).

Responsibility
    Owns the request lifecycle: validation, configuration resolution, agent
    lookup, workflow execution, tool coordination, memory coordination, model
    selection, policy enforcement, evaluation, telemetry and streaming.

Key constraint
    The runtime must remain independent of every LLM provider. It resolves
    capabilities through registries and never imports a provider implementation.

    Concretely, for model calls that means depending on
    :class:`~agent_platform_sdk.interfaces.llm_gateway.LLMGateway` and never on
    :class:`~agent_platform_sdk.interfaces.llm_provider.LLMProvider`. Holding a
    provider directly would put retry, timeout and cost handling back into
    orchestration, one copy per call site — which is what the gateway exists to
    prevent (``architecture.md`` §30).

Filled in from Milestone 03.
"""
