"""Factories — creation of implementations resolved through registries.

Responsibility
    ``ProviderFactory``, ``AgentFactory``, ``ToolFactory``, ``MemoryFactory``,
    ``WorkflowFactory``, ``EvaluationFactory`` (``architecture.md`` §43).

Why this is separate from the container
    The container wires the *fixed* object graph known at startup. Factories
    create objects whose concrete type is only known per request — the provider
    a given agent needs, the tools a given call may use.

Filled in from Milestone 03.
"""
