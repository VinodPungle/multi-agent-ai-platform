"""Aggregates every v1 feature router.

Feature routers are collected here rather than registered directly on the app,
so that adding a feature in a later milestone is a single line in this file and
the application factory never changes.
"""

from __future__ import annotations

from fastapi import APIRouter

from agent_platform.api.v1 import analytics, catalogue, chat, meta

__all__ = ["api_v1_router"]

api_v1_router = APIRouter(prefix="/v1")

api_v1_router.include_router(meta.router)
api_v1_router.include_router(chat.router, prefix="/chat")
api_v1_router.include_router(analytics.router, prefix="/analytics")
# Discovery. No prefix: the paths are /agents, /tools and /models, which read
# better as top-level collections than nested under a shared segment.
api_v1_router.include_router(catalogue.router)
