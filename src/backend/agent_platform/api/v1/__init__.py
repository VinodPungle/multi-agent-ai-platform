"""Version 1 of the public API.

``CLAUDE.md`` requires every public API to be versioned. Routes are mounted
under ``{server.api_prefix}/v1``, so a future v2 can be served alongside v1
rather than breaking existing clients.

One router per feature (handbook, "FastAPI Standards"). Milestone 01 ships
``meta``; ``chat``, ``agents``, ``models`` and ``tools`` arrive in later
milestones.
"""

from agent_platform.api.v1.router import api_v1_router

__all__ = ["api_v1_router"]
