"""Integration tests for backend CORS configuration and header validation."""

from fastapi.testclient import TestClient


def test_cors_allowed_origin_returns_header(client: TestClient) -> None:
    """Configured origin must receive matching access-control-allow-origin."""
    response = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert response.status_code == 200
    assert (
        response.headers.get("access-control-allow-origin") == "http://localhost:3000"
    )
    assert response.headers.get("access-control-allow-origin") != "*"


def test_cors_preflight_options_allowed_origin_succeeds(client: TestClient) -> None:
    """Preflight OPTIONS request from an allowed origin must succeed."""
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert (
        response.headers.get("access-control-allow-origin") == "http://localhost:3000"
    )
    assert response.headers.get("access-control-allow-origin") != "*"
    allowed_methods = response.headers.get("access-control-allow-methods", "")
    assert "GET" in allowed_methods


def test_cors_unlisted_origin_omits_allow_origin_header(client: TestClient) -> None:
    """Unlisted origin must not receive an access-control-allow-origin header."""
    response = client.get("/health", headers={"Origin": "http://evil.example"})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
    assert response.headers.get("access-control-allow-origin") != "*"


def test_cors_wildcard_origin_never_returned(client: TestClient) -> None:
    """Verify wildcard '*' is never returned on any origin header probe."""
    for origin in ["http://localhost:3000", "http://evil.example", "null"]:
        response = client.get("/health", headers={"Origin": origin})
        assert response.headers.get("access-control-allow-origin") != "*"
