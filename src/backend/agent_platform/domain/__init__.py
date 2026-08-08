"""Domain layer — models and rules that express the platform's business meaning.

Responsibility
    Concepts that would still be true if the platform were rewritten in another
    language on another cloud: conversations, agents, executions, budgets.

Dependency rule
    This package imports **nothing** outside the standard library and
    ``agent_platform_sdk`` contracts. No FastAPI, no vendor SDK, no provider, no
    storage. If a change here requires importing infrastructure, the design is
    wrong, not the rule.

Filled in from Milestone 02 (conversations) and Milestone 03 (agent runtime domain).
"""
