"""Persistence adapters.

Responsibility
    Repository implementations backed by Cosmos DB, PostgreSQL, Redis or blob
    storage. Containers stay stateless; all state lives behind this package
    (``architecture.md`` §53).

Dependency rule
    ``application`` and ``domain`` depend on repository interfaces, never on
    anything defined here.

Filled in from Milestone 08.
"""
