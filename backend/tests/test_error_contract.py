"""Contract tests verifying uniform error response shapes and no tracebacks."""

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize(
    ("path", "method", "expected_status", "expected_code"),
    [
        ("/does-not-exist", "get", 404, "not_found"),
        ("/health", "post", 405, "method_not_allowed"),
        ("/test/validation?item_id=invalid", "get", 422, "validation_error"),
        ("/test/induced-500", "get", 500, "internal_server_error"),
    ],
)
def test_error_response_contract_and_no_traceback(
    client: TestClient,
    path: str,
    method: str,
    expected_status: int,
    expected_code: str,
) -> None:
    """Error responses for 404/405/422/500 must adhere to uniform error contract."""
    client_func = getattr(client, method)
    response = client_func(path)

    assert response.status_code == expected_status

    body = response.json()
    assert "error" in body, f"Response missing 'error' key: {body}"
    assert isinstance(body["error"], dict)
    assert "code" in body["error"]
    assert "message" in body["error"]
    assert body["error"]["code"] == expected_code
    assert isinstance(body["error"]["message"], str)
    assert len(body["error"]["message"].strip()) > 0

    # Ensure no internal execution details or stack traces are ever leaked
    lower_text = response.text.lower()
    assert "traceback" not in lower_text
