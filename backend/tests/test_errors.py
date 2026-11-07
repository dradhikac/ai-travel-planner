"""Tests for centralized error handling and response shapes."""

from fastapi.testclient import TestClient


def test_404_error_shape(client: TestClient) -> None:
    """GET to a non-existent path must return uniform 404 error shape."""
    response = client.get("/non-existent-endpoint")
    assert response.status_code == 404
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "not_found"
    assert "message" in data["error"]


def test_405_error_shape(client: TestClient) -> None:
    """POST to GET-only /health endpoint must return uniform 405 error shape."""
    response = client.post("/health")
    assert response.status_code == 405
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "method_not_allowed"
    assert "message" in data["error"]


def test_422_validation_error_shape(client: TestClient) -> None:
    """Sending invalid parameter types must return uniform 422 error shape."""
    response = client.get("/test/validation?item_id=not-an-integer")
    assert response.status_code == 422
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "validation_error"
    assert data["error"]["message"] == "Request validation failed"
    assert isinstance(data["error"]["details"], list)
    assert len(data["error"]["details"]) > 0
    assert "loc" in data["error"]["details"][0]
    assert "msg" in data["error"]["details"][0]
    assert "type" in data["error"]["details"][0]


def test_500_internal_error_shape_and_leak_prevention(client: TestClient) -> None:
    """Unhandled exceptions must return uniform 500 without leaking stack traces."""
    response = client.get("/test/induced-500")
    assert response.status_code == 500
    data = response.json()
    assert data == {
        "error": {
            "code": "internal_server_error",
            "message": "An internal server error occurred",
        }
    }
    # Verify no internals, stack traces, or exception messages leaked
    raw_text = response.text.lower()
    assert "traceback" not in raw_text
    assert "induced unexpected internal server failure" not in raw_text
