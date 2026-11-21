"""Backwards-compatible Open-Meteo exceptions mapped to shared ProviderError."""

from typing import Any

from app.providers.errors import ErrorCode, ProviderError, classify_http_error


class TimeoutError(ProviderError):
    """Raised when an external Open-Meteo request times out."""

    def __init__(
        self,
        message: str = "Open-Meteo request timed out. Please try again shortly.",
        provider: str = "Open-Meteo",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code=ErrorCode.TIMEOUT,
            provider=provider,
            retryable=True,
            safe_message=message,
            details=details,
        )


class NetworkUnavailableError(ProviderError):
    """Raised on socket connection refusal or DNS resolution failure."""

    def __init__(
        self,
        message: str = "Open-Meteo network is unreachable.",
        provider: str = "Open-Meteo",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code=ErrorCode.TIMEOUT,
            provider=provider,
            retryable=True,
            safe_message=message,
            details=details,
        )


class HttpError(ProviderError):
    """Raised when provider returns unexpected 4xx or 5xx status codes."""

    def __init__(
        self,
        status_code: int,
        message: str,
        reason: str | None = None,
        provider: str = "Open-Meteo",
        details: dict[str, Any] | None = None,
    ) -> None:
        classified = classify_http_error(
            status=status_code, body_hint=reason, provider=provider
        )
        combined_details = {"status_code": status_code, "reason": reason}
        if details:
            combined_details.update(details)

        super().__init__(
            message=message,
            code=classified.code,
            provider=provider,
            retryable=classified.retryable,
            safe_message=classified.safe_message,
            http_status=status_code,
            retry_after_seconds=classified.retry_after_seconds,
            details=combined_details,
        )
        self.status_code = status_code
        self.reason = reason


class RateLimitExceededError(ProviderError):
    """Raised when HTTP 429 Too Many Requests is received from the provider."""

    def __init__(
        self,
        retry_after: float | str | None = None,
        message: str = "Open-Meteo rate limit exceeded. Please retry later.",
        provider: str = "Open-Meteo",
        details: dict[str, Any] | None = None,
    ) -> None:
        retry_after_val: float | None = None
        msg = message
        if isinstance(retry_after, str):
            try:
                retry_after_val = float(retry_after)
            except ValueError:
                msg = retry_after
                retry_after_val = None
        elif isinstance(retry_after, (int, float)):
            retry_after_val = float(retry_after)

        is_retryable = retry_after_val is not None and retry_after_val <= 4.0
        combined_details = {"retry_after": retry_after_val}
        if details:
            combined_details.update(details)

        super().__init__(
            message=msg,
            code=ErrorCode.RATE_LIMITED,
            provider=provider,
            retryable=is_retryable,
            safe_message=msg,
            http_status=429,
            retry_after_seconds=retry_after_val,
            details=combined_details,
        )
        self.retry_after = retry_after_val


class MalformedResponseError(ProviderError):
    """Raised when provider response violates expected JSON structure."""

    def __init__(
        self,
        message: str = "Open-Meteo response format was malformed or unexpected.",
        provider: str = "Open-Meteo",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code=ErrorCode.INVALID_RESPONSE,
            provider=provider,
            retryable=False,
            safe_message=message,
            details=details,
        )


__all__ = [
    "HttpError",
    "MalformedResponseError",
    "NetworkUnavailableError",
    "ProviderError",
    "RateLimitExceededError",
    "TimeoutError",
]
