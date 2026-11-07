"""Health check endpoints for basic probes and database readiness."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.schemas.health import DatabaseHealthResponse, HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """Return 200 status ok for basic health probes."""
    return HealthResponse(status="ok")


@router.get("/health/db", response_model=DatabaseHealthResponse)
def database_health_check(
    session: Annotated[Session | None, Depends(get_session)],
) -> DatabaseHealthResponse:
    """Check relational database connectivity via SELECT 1."""
    if session is None:
        raise HTTPException(
            status_code=503,
            detail="Database service is unavailable",
        )

    try:
        session.execute(text("SELECT 1"))
        return DatabaseHealthResponse(status="ok", database="reachable")
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Database service is unavailable",
        ) from None
