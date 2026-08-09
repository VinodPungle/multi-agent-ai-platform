"""Aggregates every v1 feature router.

Feature routers are collected here rather than registered directly on the app,
so that adding a feature in a later milestone is a single line in this file and
the application factory never changes.
"""

from __future__ import annotations

from fastapi import APIRouter

from agent_platform.api.v1 import analytics, chat, meta

__all__ = ["api_v1_router"]

api_v1_router = APIRouter(prefix="/v1")

api_v1_router.include_router(meta.router)
api_v1_router.include_router(chat.router, prefix="/chat")
api_v1_router.include_router(analytics.router, prefix="/analytics")

# Later milestones add:
#   api_v1_router.include_router(agents.router, prefix="/agents")  # Milestone 03
#   api_v1_router.include_router(tools.router,  prefix="/tools")   # Milestone 04
#   api_v1_router.include_router(models.router, prefix="/models")  # Milestone 05
