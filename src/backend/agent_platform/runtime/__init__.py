"""Agent Runtime — the heart of the platform (``architecture.md`` §9-§25).

Responsibility
    Owns the request lifecycle: validation, configuration resolution, agent
    lookup, workflow execution, tool coordination, memory coordination, model
    selection, policy enforcement, evaluation, telemetry and streaming.

Key constraint
    The runtime must remain independent of every LLM provider. It resolves
    capabilities through registries and never imports a provider implementation.

Filled in from Milestone 03.
"""
