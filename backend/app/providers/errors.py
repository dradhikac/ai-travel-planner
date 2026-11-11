"""Unified ProviderError model and error classification for external services."""

import email.utils
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

# Regular expressions for stripping credentials and secrets from safe messages
_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"sk-[A-Za-z0-9_-]{10,}", re.IGNORECASE),
    re.compile(r"ghp_[A-Za-z0-9]{20,}", re.IGNORECASE),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/-]+", re.IGNORECASE),
    re.compile(
        r"(api[-_]?key|token|secret|password|authorization)[\s:=]+([^\s,;]+)",
        re.IGNORECASE,
    ),
]

_URL_QUERY_PATTERN: re.Pattern[str] = re.compile(r"(https?://[^\s?#]+)\?[^\s#]*")


class ErrorCode(StrEnum):
    """Standardized error codes across all external providers."""

    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    AUTHENTICATION_FAILED = "authentication_failed"
    INVALID_RESPONSE = "invalid_response"
    INVALID_REQUEST = "invalid_request"
    UNKNOWN_FAILURE = "unknown_failure"


# Alias for backwards compatibility with specifications
ProviderErrorCode = ErrorCode


def sanitize_safe_message(message: str) -> str:
    """Sanitize diagnostic message to ensure zero credential or query string leakage.

    Strips query parameters from URLs, redacts API tokens and secrets, and removes
    multi-line stack traces or raw response bodies.
    """
    if not message:
        return "An unknown error occurred."

    # Strip stack trace markers if accidentally passed
    if "Traceback (most recent call last)" in message:
        message = message.split("Traceback (most recent call last)")[0].strip()
        if not message:
            message = "An internal exception occurred."

    # Strip query parameters from any URLs (e.g. https://api.com/v1?key=secret -> https://api.com/v1)
    sanitized = _URL_QUERY_PATTERN.sub(r"\1", message)

    # Redact secret patterns
    for pat in _SECRET_PATTERNS:
        if pat.pattern.startswith("(api"):
            sanitized = pat.sub(r"\1: [REDACTED]", sanitized)
        else:
            sanitized = pat.sub("[REDACTED]", sanitized)

    # Enforce safe length limit
    trimmed = " ".join(sanitized.strip().split())
    if len(trimmed) > 400:
        return trimmed[:397] + "..."
    return trimmed or "An unknown error occurred."


def parse_retry_after(
    header_value: str | None,
    now: datetime | None = None,
) -> float | None:
    """Parse HTTP Retry-After header safely.

    Handles:
    1. Integer or float seconds (e.g. "30", "2.5").
    2. HTTP date formats (e.g. "Wed, 21 Oct 2026 07:28:00 GMT").
    3. Garbage or negative values -> returns None.
    """
    if not header_value or not isinstance(header_value, str):
        return None

    cleaned = header_value.strip()
    if not cleaned:
        return None

    # 1. Try parsing numeric seconds
    try:
        val = float(cleaned)
        if val >= 0.0:
            return val
        return None
    except ValueError:
        pass

    # 2. Try parsing HTTP-date
    try:
        dt = email.utils.parsedate_to_datetime(cleaned)
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            ref_now = now or datetime.now(UTC)
            delta = (dt - ref_now).total_seconds()
            return max(0.0, delta)
    except Exception:
        pass

    return None


class ProviderError(Exception):
    """Unified exception class for all external service provider errors."""

    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.UNKNOWN_FAILURE,
        provider: str = "Unknown",
        retryable: bool | None = None,
        safe_message: str | None = None,
        http_status: int | None = None,
        retry_after_seconds: float | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.provider = provider
        self.http_status = http_status
        self.retry_after_seconds = retry_after_seconds
        self.details = details or {}

        # Derive retryable if not explicitly provided
        if retryable is not None:
            self.retryable = retryable
        else:
            self.retryable = self._derive_retryable()

        # Derive and sanitize safe message
        if safe_message is not None:
            self.safe_message = sanitize_safe_message(safe_message)
        else:
            self.safe_message = self._default_safe_message()

    def _derive_retryable(self) -> bool:
        """Derive retryable flag from error code, status, and retry-after bounds."""
        match self.code:
            case ErrorCode.TIMEOUT:
                return True
            case ErrorCode.RATE_LIMITED:
                # Retryable only if Retry-After is specified and <= 4.0 seconds
                return (
                    self.retry_after_seconds is not None
                    and self.retry_after_seconds <= 4.0
                )
            case ErrorCode.AUTHENTICATION_FAILED:
                return False
            case ErrorCode.INVALID_RESPONSE:
                return False
            case ErrorCode.INVALID_REQUEST:
                return False
            case ErrorCode.UNKNOWN_FAILURE:
                # Server-side 5xx errors are retryable
                if self.http_status is not None and 500 <= self.http_status < 600:
                    return True
                return False
            case _:
                return False

    def _default_safe_message(self) -> str:
        """Generate human-readable safe message free of credentials and traces."""
        match self.code:
            case ErrorCode.TIMEOUT:
                return f"{self.provider} request timed out. Please try again shortly."
            case ErrorCode.RATE_LIMITED:
                return f"{self.provider} rate limit exceeded. Please try again later."
            case ErrorCode.AUTHENTICATION_FAILED:
                return (
                    f"{self.provider} service is unauthorized "
                    "or credentials are invalid."
                )
            case ErrorCode.INVALID_RESPONSE:
                return f"{self.provider} returned an unreadable or malformed response."
            case ErrorCode.INVALID_REQUEST:
                return f"{self.provider} rejected the request parameters as invalid."
            case ErrorCode.UNKNOWN_FAILURE:
                if self.http_status is not None and 500 <= self.http_status < 600:
                    return (
                        f"{self.provider} service is temporarily "
                        "experiencing upstream outages."
                    )
                return (
                    f"An unexpected failure occurred while contacting {self.provider}."
                )
            case _:
                return f"An unexpected error occurred with {self.provider}."


def classify_http_error(
    status: int,
    body_hint: str | None = None,
    headers: Mapping[str, str] | None = None,
    provider: str = "Unknown",
) -> ProviderError:
    """Classify an HTTP status response into a standardized ProviderError.

    Mapping rules:
    - 401 / 403 -> authentication_failed (retryable: False)
    - 429 -> rate_limited (parses Retry-After; retryable if <= 4.0s)
    - 400 <= status < 500 -> invalid_request (retryable: False)
    - 500 <= status < 600 -> unknown_failure (retryable: True)
    - Other -> unknown_failure (retryable: False)
    """
    retry_after: float | None = None
    if headers:
        # Case-insensitive header lookup
        header_val = next(
            (v for k, v in headers.items() if k.lower() == "retry-after"),
            None,
        )
        retry_after = parse_retry_after(header_val)

    if status in (401, 403):
        return ProviderError(
            message=f"{provider} authentication failed (HTTP {status}).",
            code=ErrorCode.AUTHENTICATION_FAILED,
            provider=provider,
            http_status=status,
            retryable=False,
            details={"status_code": status, "body_hint": body_hint},
        )

    if status == 429:
        is_retryable = retry_after is not None and retry_after <= 4.0
        return ProviderError(
            message=f"{provider} rate limit exceeded (HTTP 429).",
            code=ErrorCode.RATE_LIMITED,
            provider=provider,
            http_status=429,
            retry_after_seconds=retry_after,
            retryable=is_retryable,
            details={
                "status_code": 429,
                "retry_after": retry_after,
                "body_hint": body_hint,
            },
        )

    if 400 <= status < 500:
        return ProviderError(
            message=f"{provider} client error (HTTP {status}).",
            code=ErrorCode.INVALID_REQUEST,
            provider=provider,
            http_status=status,
            retryable=False,
            details={"status_code": status, "body_hint": body_hint},
        )

    if 500 <= status < 600:
        return ProviderError(
            message=f"{provider} server error (status code {status}).",
            code=ErrorCode.UNKNOWN_FAILURE,
            provider=provider,
            http_status=status,
            retryable=True,
            safe_message=(
                f"{provider} service is temporarily experiencing upstream outages."
            ),
            details={"status_code": status, "body_hint": body_hint},
        )

    return ProviderError(
        message=f"{provider} unexpected HTTP response (HTTP {status}).",
        code=ErrorCode.UNKNOWN_FAILURE,
        provider=provider,
        http_status=status,
        retryable=False,
        details={"status_code": status, "body_hint": body_hint},
    )


def classify_exception(
    exc: Exception,
    provider: str = "Unknown",
) -> ProviderError:
    """Classify a Python exception into a standardized ProviderError.

    Mapping rules:
    - ProviderError -> returned directly.
    - Timeout errors (httpx.TimeoutException, etc.) -> timeout (retryable: True).
    - Network/connection errors (httpx.NetworkError) -> timeout (retryable: True).
    - HTTP status errors (httpx.HTTPStatusError) -> routed through classify_http_error.
    - JSON / schema validation errors -> invalid_response (retryable: False).
    - Other exceptions -> unknown_failure (retryable: False).
    """
    if isinstance(exc, ProviderError):
        return exc

    exc_name = type(exc).__name__
    exc_msg = str(exc)

    # 1. Timeout exceptions
    if "Timeout" in exc_name or isinstance(exc, TimeoutError):
        return ProviderError(
            message=f"{provider} request timed out: {exc_msg}",
            code=ErrorCode.TIMEOUT,
            provider=provider,
            retryable=True,
            details={"exception_type": exc_name},
        )

    # 2. Connection / Network errors (timeouts and network errors -> timeout)
    if (
        "ConnectError" in exc_name
        or "NetworkError" in exc_name
        or "ConnectionRefused" in exc_name
        or "gaierror" in exc_name
    ):
        return ProviderError(
            message=f"{provider} network connection error: {exc_msg}",
            code=ErrorCode.TIMEOUT,
            provider=provider,
            retryable=True,
            details={"exception_type": exc_name},
        )

    # 3. HTTP status errors (e.g. from httpx.HTTPStatusError)
    if hasattr(exc, "response") and hasattr(exc.response, "status_code"):
        resp = exc.response
        headers = getattr(resp, "headers", None)
        return classify_http_error(
            status=resp.status_code,
            headers=headers,
            provider=provider,
        )

    # 4. JSON / Parse / Schema validation errors
    if "JSONDecodeError" in exc_name or "ValidationError" in exc_name:
        return ProviderError(
            message=f"{provider} response validation failed: {exc_msg}",
            code=ErrorCode.INVALID_RESPONSE,
            provider=provider,
            retryable=False,
            details={"exception_type": exc_name},
        )

    # 5. Fallback for unclassified exceptions
    return ProviderError(
        message=f"{provider} unexpected exception ({exc_name}): {exc_msg}",
        code=ErrorCode.UNKNOWN_FAILURE,
        provider=provider,
        retryable=False,
        details={"exception_type": exc_name},
    )
