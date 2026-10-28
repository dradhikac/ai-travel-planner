"""Unit and integration tests for database persistence and session lifecycle."""

import os

import pytest
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import get_engine, get_session, get_session_factory


def test_database_engine_unconfigured_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When DATABASE_URL is unset, get_engine and factory must return None."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    assert get_engine() is None
    assert get_session_factory() is None


def test_database_session_unconfigured_yields_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When unconfigured, get_session dependency must yield None."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    gen = get_session()
    session = next(gen)
    assert session is None
    with pytest.raises(StopIteration):
        next(gen)


def test_database_engine_configured_returns_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When DATABASE_URL is configured, get_engine must return an Engine instance."""
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg://test:pass@localhost:5432/testdb"
    )
    get_settings.cache_clear()
    engine = get_engine()
    assert engine is not None
    assert engine.pool is not None

    factory = get_session_factory()
    assert factory is not None


@pytest.mark.integration
@pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL environment variable is not set",
)
def test_live_database_connection_and_session_lifecycle() -> None:
    """Integration test verifying connection, transaction and session closure."""
    gen = get_session()
    session = next(gen)
    assert session is not None

    try:
        result = session.execute(text("SELECT 1")).scalar()
        assert result == 1
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


@pytest.mark.integration
@pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL environment variable is not set",
)
def test_live_database_alembic_version_table_exists() -> None:
    """Integration test verifying Alembic baseline migration applied successfully."""
    gen = get_session()
    session = next(gen)
    assert session is not None

    try:
        # Verify alembic_version table exists and contains current head
        version = session.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar()
        assert version is not None
        assert isinstance(version, str)
    finally:
        try:
            next(gen)
        except StopIteration:
            pass
