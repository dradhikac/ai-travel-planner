"""Database session management with lazy engine creation and FastAPI dependencies."""

from collections.abc import Generator
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings


@lru_cache
def get_engine(settings: Settings | None = None) -> Engine | None:
    """Lazily create and cache SQLAlchemy engine from settings.

    Returns None if DATABASE_URL is unset.
    """
    if settings is None:
        settings = get_settings()

    if not settings.DATABASE_URL:
        return None

    connect_args: dict[str, Any] = {}
    if settings.DATABASE_URL.startswith("postgresql"):
        connect_args["connect_timeout"] = 5

    return create_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


@lru_cache
def get_session_factory(
    settings: Settings | None = None,
) -> sessionmaker[Session] | None:
    """Lazily create and cache SQLAlchemy sessionmaker."""
    engine = get_engine(settings)
    if engine is None:
        return None

    return sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )


def get_session() -> Generator[Session | None, Any, None]:
    """FastAPI dependency yielding an active database session or None if unconfigured.

    Closes the session after request handling.
    """
    factory = get_session_factory()
    if factory is None:
        yield None
        return

    session = factory()
    try:
        yield session
    finally:
        session.close()
