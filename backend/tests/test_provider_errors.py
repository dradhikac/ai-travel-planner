"""Unit tests for ProviderError model, classification, and ToolResult mapping."""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import BaseModel, ValidationError

from app.agent.errors import ToolErrorCode
from app.agent.tools.contracts import (
    ToolResult,
    ToolStatus,
    provider_error_to_tool_result,
)
from app.providers.errors import (
    ErrorCode,
    ProviderError,
    classify_exception,
    classify_http_error,
    parse_retry_after,
    sanitize_safe_message,
)
from app.providers.open_meteo.errors import (
    HttpError,
    MalformedResponseError,
    NetworkUnavailableError,
    RateLimitExceededError,
    TimeoutError,
)

# ==============================================================================
# 1. ErrorCode & ProviderError Taxonomy Tests
# ==============================================================================


def test_error_code_values() -> None:
    """Standardized ErrorCode values match reliability contract specification."""
    assert ErrorCode.TIMEOUT.value == "timeout"
    assert ErrorCode.RATE_LIMITED.value == "rate_limited"
    assert ErrorCode.AUTHENTICATION_FAILED.value == "authentication_failed"
    assert ErrorCode.INVALID_RESPONSE.value == "invalid_response"
    assert ErrorCode.INVALID_REQUEST.value == "invalid_request"
    assert ErrorCode.UNKNOWN_FAILURE.value == "unknown_failure"


def test_provider_error_fields_and_inheritance() -> None:
    """ProviderError carries required structured attributes and inherits Exception."""
    err = ProviderError(
        message="Upstream failure",
        code=ErrorCode.TIMEOUT,
        provider="TestProvider",
        retryable=True,
        safe_message="TestProvider timed out.",
        http_status=504,
        retry_after_seconds=2.5,
        details={"path": "/v1/test"},
    )
    assert isinstance(err, Exception)
    assert err.message == "Upstream failure"
    assert err.code == ErrorCode.TIMEOUT
    assert err.provider == "TestProvider"
    assert err.retryable is True
    assert err.safe_message == "TestProvider timed out."
    assert err.http_status == 504
    assert err.retry_after_seconds == 2.5
    assert err.details == {"path": "/v1/test"}


@pytest.mark.parametrize(
    ("code", "http_status", "retry_after", "expected_retryable"),
    [
        (ErrorCode.TIMEOUT, None, None, True),
        (ErrorCode.RATE_LIMITED, 429, 2.0, True),  # <= 4.0s cap
        (ErrorCode.RATE_LIMITED, 429, 4.0, True),  # Exactly at cap
        (ErrorCode.RATE_LIMITED, 429, 4.1, False),  # > 4.0s cap
        (ErrorCode.RATE_LIMITED, 429, None, False),  # Unspecified Retry-After
        (ErrorCode.AUTHENTICATION_FAILED, 401, None, False),
        (ErrorCode.AUTHENTICATION_FAILED, 403, None, False),
        (ErrorCode.INVALID_RESPONSE, 200, None, False),
        (ErrorCode.INVALID_REQUEST, 400, None, False),
        (ErrorCode.INVALID_REQUEST, 422, None, False),
        (ErrorCode.UNKNOWN_FAILURE, 500, None, True),  # 5xx server errors
        (ErrorCode.UNKNOWN_FAILURE, 503, None, True),
        (ErrorCode.UNKNOWN_FAILURE, None, None, False),  # Unclassified client failure
        (ErrorCode.UNKNOWN_FAILURE, 400, None, False),
    ],
)
def test_retryable_flag_derivation(
    code: ErrorCode,
    http_status: int | None,
    retry_after: float | None,
    expected_retryable: bool,
) -> None:
    """Retryable flag derived deterministically from code, status, and retry-after."""
    err = ProviderError(
        message="Derivation check",
        code=code,
        provider="TestService",
        http_status=http_status,
        retry_after_seconds=retry_after,
    )
    assert err.retryable is expected_retryable


def test_explicit_retryable_override() -> None:
    """Explicitly passing retryable overrides the default derivation logic."""
    err_forced_true = ProviderError(
        message="Forced retry",
        code=ErrorCode.AUTHENTICATION_FAILED,
        retryable=True,
    )
    assert err_forced_true.retryable is True

    err_forced_false = ProviderError(
        message="Forced non-retry",
        code=ErrorCode.TIMEOUT,
        retryable=False,
    )
    assert err_forced_false.retryable is False


# ==============================================================================
# 2. Table-Driven HTTP Error Classification Tests
# ==============================================================================


@pytest.mark.parametrize(
    ("status", "headers", "expected_code", "expected_retryable"),
    [
        (401, None, ErrorCode.AUTHENTICATION_FAILED, False),
        (403, None, ErrorCode.AUTHENTICATION_FAILED, False),
        (429, None, ErrorCode.RATE_LIMITED, False),
        (429, {"Retry-After": "2"}, ErrorCode.RATE_LIMITED, True),
        (429, {"Retry-After": "30"}, ErrorCode.RATE_LIMITED, False),
        (429, {"retry-after": "1.5"}, ErrorCode.RATE_LIMITED, True),  # Case-insensitive
        (400, None, ErrorCode.INVALID_REQUEST, False),
        (404, None, ErrorCode.INVALID_REQUEST, False),
        (422, None, ErrorCode.INVALID_REQUEST, False),
        (500, None, ErrorCode.UNKNOWN_FAILURE, True),
        (502, None, ErrorCode.UNKNOWN_FAILURE, True),
        (503, None, ErrorCode.UNKNOWN_FAILURE, True),
        (504, None, ErrorCode.UNKNOWN_FAILURE, True),
        (301, None, ErrorCode.UNKNOWN_FAILURE, False),
    ],
)
def test_table_driven_classify_http_error(
    status: int,
    headers: dict[str, str] | None,
    expected_code: ErrorCode,
    expected_retryable: bool,
) -> None:
    """classify_http_error accurately classifies all HTTP status codes per contract."""
    err = classify_http_error(
        status=status,
        body_hint="Error body preview",
        headers=headers,
        provider="MockService",
    )
    assert err.code == expected_code
    assert err.http_status == status
    assert err.retryable is expected_retryable
    assert err.provider == "MockService"
    assert "MockService" in err.safe_message


# ==============================================================================
# 3. Retry-After Header Parsing Tests
# ==============================================================================


def test_parse_retry_after_integer_seconds() -> None:
    """Numeric integer and float string seconds parse to float."""
    assert parse_retry_after("30") == 30.0
    assert parse_retry_after(" 120 ") == 120.0
    assert parse_retry_after("2.5") == 2.5
    assert parse_retry_after("0") == 0.0


def test_parse_retry_after_http_date() -> None:
    """Standard HTTP dates parse to relative seconds delta from reference time."""
    ref_time = datetime(2026, 11, 9, 12, 0, 0, tzinfo=UTC)
    future_time = ref_time + timedelta(seconds=45)
    # RFC 7231 / IMF-fixdate format: "Mon, 09 Nov 2026 12:00:45 GMT"
    date_header = future_time.strftime("%a, %d %b %Y %H:%M:%S GMT")

    parsed = parse_retry_after(date_header, now=ref_time)
    assert parsed is not None
    assert round(parsed) == 45


def test_parse_retry_after_past_http_date() -> None:
    """HTTP date in the past returns 0.0 seconds."""
    ref_time = datetime(2026, 11, 9, 12, 0, 0, tzinfo=UTC)
    past_time = ref_time - timedelta(seconds=10)
    date_header = past_time.strftime("%a, %d %b %Y %H:%M:%S GMT")

    parsed = parse_retry_after(date_header, now=ref_time)
    assert parsed == 0.0


@pytest.mark.parametrize(
    "invalid_val",
    [None, "", "   ", "garbage", "-5", "-12.5", "invalid-date-string"],
)
def test_parse_retry_after_garbage_returns_none(invalid_val: str | None) -> None:
    """Garbage strings, negative numbers, or empty headers safely return None."""
    assert parse_retry_after(invalid_val) is None


# ==============================================================================
# 4. Table-Driven Exception Classification Tests
# ==============================================================================


class _SampleModel(BaseModel):
    name: str


def _make_validation_error() -> ValidationError:
    try:
        _SampleModel.model_validate({})
    except ValidationError as err:
        return err
    raise RuntimeError("Unreachable")


@pytest.mark.parametrize(
    ("exc", "expected_code", "expected_retryable"),
    [
        (httpx.TimeoutException("Read timeout"), ErrorCode.TIMEOUT, True),
        (httpx.ConnectTimeout("Connect timed out"), ErrorCode.TIMEOUT, True),
        (httpx.ReadTimeout("Read timed out"), ErrorCode.TIMEOUT, True),
        (httpx.ConnectError("Connection refused"), ErrorCode.TIMEOUT, True),
        (httpx.NetworkError("Network down"), ErrorCode.TIMEOUT, True),
        (ConnectionRefusedError("Port closed"), ErrorCode.TIMEOUT, True),
        (
            json.JSONDecodeError("Expecting value", "bad json", 0),
            ErrorCode.INVALID_RESPONSE,
            False,
        ),
        (_make_validation_error(), ErrorCode.INVALID_RESPONSE, False),
        (KeyError("missing_field"), ErrorCode.UNKNOWN_FAILURE, False),
        (RuntimeError("Unknown crash"), ErrorCode.UNKNOWN_FAILURE, False),
    ],
)
def test_table_driven_classify_exception(
    exc: Exception,
    expected_code: ErrorCode,
    expected_retryable: bool,
) -> None:
    """classify_exception maps Python exception types to standardized ProviderError."""
    err = classify_exception(exc, provider="TestAPI")
    assert err.code == expected_code
    assert err.retryable is expected_retryable
    assert err.provider == "TestAPI"


def test_classify_exception_preserves_existing_provider_error() -> None:
    """Existing ProviderError is passed through without re-wrapping."""
    existing = ProviderError(
        message="Pre-classified error",
        code=ErrorCode.AUTHENTICATION_FAILED,
        provider="AuthService",
        retryable=False,
    )
    result = classify_exception(existing, provider="FallbackService")
    assert result is existing
    assert result.code == ErrorCode.AUTHENTICATION_FAILED


# ==============================================================================
# 5. Safe Message Sanitization & Secret Redaction Tests
# ==============================================================================


def test_safe_message_strips_url_query_parameters() -> None:
    """URLs with embedded query parameters have query strings scrubbed."""
    raw = (
        "Failed request to https://api.open-meteo.com/v1/forecast?"
        "latitude=48.85&api_key=secret_123456789&foo=bar"
    )
    sanitized = sanitize_safe_message(raw)
    assert "?" not in sanitized
    assert "api_key" not in sanitized
    assert "secret_123456789" not in sanitized
    assert "https://api.open-meteo.com/v1/forecast" in sanitized


def test_safe_message_redacts_planted_secrets() -> None:
    """Planted secret tokens are stripped from safe messages."""
    fake_sk = "sk-" + "abcdef1234567890" + "_secret"
    fake_ghp = "ghp_" + "1234567890abcdef" + "12345678901234567890"
    fake_akia = "AK" + "IAIOSFODNN7EXAMPLE"
    bearer_token = "my_jwt_token_here"

    raw = (
        f"Authentication failed using {fake_sk} and "
        f"{fake_ghp} with key {fake_akia} "
        f"and header Bearer {bearer_token}"
    )
    sanitized = sanitize_safe_message(raw)
    assert fake_sk not in sanitized
    assert fake_ghp not in sanitized
    assert fake_akia not in sanitized
    assert bearer_token not in sanitized
    assert "[REDACTED]" in sanitized


def test_safe_message_strips_tracebacks() -> None:
    """Multi-line Python tracebacks are stripped from safe message."""
    raw = (
        "Internal crash Traceback (most recent call last):\n"
        '  File "backend/app/main.py", line 42, in handler\n'
        "ValueError: DB connection secret"
    )
    sanitized = sanitize_safe_message(raw)
    assert "Traceback" not in sanitized
    assert "backend/app/main.py" not in sanitized
    assert "ValueError: DB connection secret" not in sanitized


# ==============================================================================
# 6. Centralized ToolResult Mapping Tests
# ==============================================================================


@pytest.mark.parametrize(
    ("error_code", "expected_tool_status", "expected_tool_error_code"),
    [
        (ErrorCode.TIMEOUT, ToolStatus.TIMEOUT, ToolErrorCode.TIMEOUT),
        (ErrorCode.RATE_LIMITED, ToolStatus.RATE_LIMITED, ToolErrorCode.RATE_LIMITED),
        (
            ErrorCode.AUTHENTICATION_FAILED,
            ToolStatus.ERROR,
            ToolErrorCode.PROVIDER_UNAVAILABLE,
        ),
        (
            ErrorCode.INVALID_RESPONSE,
            ToolStatus.ERROR,
            ToolErrorCode.MALFORMED_RESPONSE,
        ),
        (ErrorCode.INVALID_REQUEST, ToolStatus.ERROR, ToolErrorCode.INVALID_ARGUMENTS),
        (
            ErrorCode.UNKNOWN_FAILURE,
            ToolStatus.ERROR,
            ToolErrorCode.PROVIDER_UNAVAILABLE,
        ),
    ],
)
def test_provider_error_to_tool_result_mapping(
    error_code: ErrorCode,
    expected_tool_status: ToolStatus,
    expected_tool_error_code: ToolErrorCode,
) -> None:
    """provider_error_to_tool_result maps every ErrorCode to the correct ToolResult."""
    err = ProviderError(
        message="Simulated error message",
        code=error_code,
        provider="GeocodingAPI",
        safe_message="Sanitized client message.",
    )
    result = provider_error_to_tool_result(
        err=err,
        tool_name="geocode_destination",
        latency_ms=123.45,
        attempts=2,
    )
    assert isinstance(result, ToolResult)
    assert result.tool_name == "geocode_destination"
    assert result.status == expected_tool_status
    assert result.error_code == expected_tool_error_code
    assert result.safe_message == "Sanitized client message."
    assert result.data is None
    assert result.data_origin == "none"
    assert result.latency_ms == 123.45
    assert result.attempts == 2


# ==============================================================================
# 7. Backwards-Compatible Open-Meteo Exceptions Tests
# ==============================================================================


def test_open_meteo_exceptions_are_provider_errors() -> None:
    """All legacy Open-Meteo exceptions are subclasses of the shared ProviderError."""
    timeout = TimeoutError("Timed out")
    assert isinstance(timeout, ProviderError)
    assert timeout.code == ErrorCode.TIMEOUT
    assert timeout.retryable is True

    rate_limit = RateLimitExceededError(retry_after=2.0)
    assert isinstance(rate_limit, ProviderError)
    assert rate_limit.code == ErrorCode.RATE_LIMITED
    assert rate_limit.retryable is True
    assert rate_limit.retry_after == 2.0

    network = NetworkUnavailableError("DNS error")
    assert isinstance(network, ProviderError)
    assert network.retryable is True

    http_err = HttpError(status_code=502, message="Bad Gateway")
    assert isinstance(http_err, ProviderError)
    assert http_err.status_code == 502
    assert http_err.code == ErrorCode.UNKNOWN_FAILURE
    assert http_err.retryable is True

    malformed = MalformedResponseError("Malformed JSON")
    assert isinstance(malformed, ProviderError)
    assert malformed.code == ErrorCode.INVALID_RESPONSE
    assert malformed.retryable is False
