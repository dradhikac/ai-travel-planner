"""Unit and integration tests for database health check endpoint."""

import os
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.session import get_session
from app.main import create_app


def test_db_health_success_with_mocked_session(app: FastAPI) -> None:
    """When SELECT 1 succeeds, /health/db must return 200 with status ok."""
    mock_session = MagicMock()
    mock_session.execute.return_value = None

    app.dependency_overrides[get_session] = lambda: mock_session
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/health/db")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "reachable"}


def test_db_health_unreachable_returns_503(app: FastAPI) -> None:
    """When query fails, /health/db must return 503 without leaking driver details."""
    mock_session = MagicMock()
    mock_session.execute.side_effect = RuntimeError(
        "Connection refused to postgresql://secret:pass@private-db:5432/db"
    )

    app.dependency_overrides[get_session] = lambda: mock_session
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/health/db")
    assert response.status_code == 503
    data = response.json()
    assert data == {
        "error": {
            "code": "service_unavailable",
            "message": "Database service is unavailable",
        }
    }
    # Verify no credentials, hosts, or driver internals are leaked in response
    lower_text = response.text.lower()
    assert "private-db" not in lower_text
    assert "pass" not in lower_text
    assert "connection refused" not in lower_text


def test_db_health_not_configured_returns_503(app: FastAPI) -> None:
    """When session is None (DATABASE_URL unset), /health/db must return 503."""
    app.dependency_overrides[get_session] = lambda: None
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/health/db")
    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "service_unavailable",
            "message": "Database service is unavailable",
        }
    }


def test_base_health_endpoint_still_ok_without_database(client: TestClient) -> None:
    """Basic /health probe must remain 200 OK regardless of database availability."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.integration
@pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL environment variable is not set",
)
def test_live_db_health_integration(client: TestClient) -> None:
    """Optional live integration test against an active PostgreSQL instance."""
    live_app = create_app()
    live_client = TestClient(live_app, raise_server_exceptions=False)
    response = live_client.get("/health/db")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "reachable"}
