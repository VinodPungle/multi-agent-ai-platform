"""Memory provider implementations.

Responsibility
    Concrete ``MemoryProvider`` implementations: in-memory first, then Redis,
    PostgreSQL, Cosmos DB, Azure AI Search and vector stores.

Design rule
    Agents never import anything from here. They depend on the interface and
    receive an implementation chosen by configuration.

Filled in from Milestone 02 (in-memory session memory).
"""
