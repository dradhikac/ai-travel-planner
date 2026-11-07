"""Tests for version endpoint."""

from fastapi.testclient import TestClient

from app.version import VERSION


def test_version_endpoint_returns_200(client: TestClient) -> None:
    """GET /api/version must return 200 with name, version, and environment."""
    response = client.get("/api/version")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "ai-travel-concierge-backend"
    assert data["version"] == VERSION
    assert data["version"] == "0.1.0"
    assert data["environment"] == "test"
