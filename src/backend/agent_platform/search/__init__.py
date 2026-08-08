"""Search provider implementations.

Responsibility
    Concrete ``SearchProvider`` implementations: internet search first, then
    Azure AI Search, SharePoint and enterprise sources.

Design rule
    Tools and agents depend on the ``SearchProvider`` interface. Which backend
    answers is a configuration choice, so replacing DuckDuckGo with a keyed
    provider is a new adapter here plus a settings change — the internet search
    tool, the runtime and every agent are unaffected.

Two implementations, on purpose
    :class:`MockSearchProvider` answers offline and deterministically, which is
    what CI and a laptop without connectivity need.
    :class:`DuckDuckGoSearchProvider` performs a real, keyless internet search.
    Having both is what demonstrates the abstraction is real rather than shaped
    around one backend.
"""

from agent_platform.search.duckduckgo_search_provider import DuckDuckGoSearchProvider
from agent_platform.search.mock_search_provider import MockSearchProvider

__all__ = ["DuckDuckGoSearchProvider", "MockSearchProvider"]
