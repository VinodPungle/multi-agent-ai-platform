"""Retrieval-augmented generation.

Responsibility
    Turning documents into retrievable passages, and finding the passages that
    answer a question. Chunking, indexing and retrieval — not embedding and not
    storage, which are provider concerns behind
    :class:`~agent_platform_sdk.interfaces.embedding_provider.EmbeddingProvider`
    and
    :class:`~agent_platform_sdk.interfaces.vector_store_provider.VectorStoreProvider`.

Design rule
    Nothing here names an embedding model or a vector database. Swapping a local
    embedder for Azure AI Foundry, or an in-process index for Azure AI Search,
    is a configuration change — the same property the memory and search
    subsystems already demonstrate.

Why retrieval is a tool
    Agents do not retrieve. They call a tool, and the runtime executes it —
    which means retrieval gets the same authorisation, timeout, retry, telemetry
    and budget handling as every other tool, and an agent that should not have
    knowledge access simply does not list it.

    The alternative, stuffing retrieved passages into every prompt before the
    model sees it, spends context on every turn including the many that need no
    documents at all, and gives the model no way to say what it actually
    searched for.

Added in Milestone 09.
"""
