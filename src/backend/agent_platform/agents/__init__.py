"""Specialised agents.

Responsibility
    Reasoning within one domain, and nothing else. An agent does not open
    connections, choose providers, call tools directly or know that other agents
    exist — the runtime does all of that on its behalf (``architecture.md`` §18).

Design rule
    Agents stay small and specialised. A "God Agent" that handles every task is
    the anti-pattern this package exists to prevent.

Filled in from Milestone 03 (chat agent).
"""
