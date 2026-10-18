"""Version metadata endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings
from app.schemas.version import VersionResponse
from app.version import VERSION

router = APIRouter(prefix="/api", tags=["version"])


@router.get("/version", response_model=VersionResponse)
def get_version(
    settings: Annotated[Settings, Depends(get_settings)],
) -> VersionResponse:
    """Return application version and runtime environment."""
    return VersionResponse(
        name="ai-travel-concierge-backend",
        version=VERSION,
        environment=settings.APP_ENV,
    )
