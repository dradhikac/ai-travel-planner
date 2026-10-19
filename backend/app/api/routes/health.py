"""Health check endpoint without external dependencies."""

from fastapi import APIRouter

from app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """Return 200 status ok for basic health probes."""
    return HealthResponse(status="ok")
