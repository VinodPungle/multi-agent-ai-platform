"""Registries — the authoritative catalogues the runtime resolves through.

Responsibility
    Registration, discovery, validation and metadata lookup for agents, models,
    providers, tools, prompts and memory (``architecture.md`` §26-§27).

Design rule
    Registries never execute business logic. They answer "what exists and what
    can it do"; factories turn those answers into instances.

Filled in from Milestone 03.
"""
