"""Platform metadata endpoint.

Reports what this build is and which capabilities are enabled. Answers the first
question of any incident — "what is actually deployed here?" — without shelling
into a container.

Only non-sensitive values are exposed. Endpoints, connection strings and
credentials are never surfaced.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from agent_platform.dependencies.providers import SettingsDep

__all__ = ["PlatformInfoResponse", "router"]

router = APIRouter(tags=["platform"])


class PlatformInfoResponse(BaseModel):
    """Identity and enabled capabilities of the running instance."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(description="Platform name.")
    version: str = Field(description="Running application version.")
    environment: str = Field(description="Declared deployment environment.")
    api_version: str = Field(description="Version of this API surface.")
    features: dict[str, bool] = Field(
        description="Effective feature flags. Capabilities are enabled by configuration.",
    )


@router.get(
    "/info",
    response_model=PlatformInfoResponse,
    summary="Platform metadata",
    description="Build identity and effective feature flags. Contains no sensitive values.",
)
async def info(settings: SettingsDep) -> PlatformInfoResponse:
    """Return metadata describing this instance."""
    return PlatformInfoResponse(
        name=settings.app.name,
        version=settings.app.version,
        environment=settings.app.environment.value,
        api_version="v1",
        features=settings.features.as_dict(),
    )
