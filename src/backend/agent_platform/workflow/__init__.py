"""Workflow engine — coordination of execution across one or more agents.

Responsibility
    Sequential execution, conditional branching, retries, workflow state,
    cancellation and timeouts (``architecture.md`` §12).

Initial implementation
    LangGraph. Graph *construction* is kept separate from graph *execution* so
    that swapping the engine — Semantic Kernel, Durable Functions, a custom
    engine — replaces one module rather than the runtime.

Filled in from Milestone 03.
"""
