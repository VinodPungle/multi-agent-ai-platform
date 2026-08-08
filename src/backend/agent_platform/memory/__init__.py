"""Memory provider implementations.

Responsibility
    Concrete ``MemoryProvider`` implementations: in-memory first, then Redis,
    PostgreSQL, Cosmos DB, Azure AI Search and vector stores.

Design rule
    Agents never import anything from here. They depend on the interface and
    receive an implementation chosen by configuration.

Current implementation
    :class:`InMemorySessionMemoryProvider` — process-local, bounded, and
    correct only for a single instance. Replaced by configuration, not by code.
"""

from agent_platform.memory.session_memory import InMemorySessionMemoryProvider

__all__ = ["InMemorySessionMemoryProvider"]
