"""Typed exception hierarchy for external provider interactions."""

from typing import Any


class ProviderError(Exception):
    """Base exception for all external provider errors."""

    def __init__(
        self,
        message: str,
        provider: str = "Open-Meteo",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.details = details or {}


class TimeoutError(ProviderError):
    """Raised when an external provider request times out."""


class NetworkUnavailableError(ProviderError):
    """Raised on socket connection refusal or DNS resolution failure."""


class HttpError(ProviderError):
    """Raised when provider returns unexpected 4xx or 5xx status codes."""

    def __init__(
        self,
        status_code: int,
        message: str,
        reason: str | None = None,
        provider: str = "Open-Meteo",
    ) -> None:
        super().__init__(
            message=message,
            provider=provider,
            details={"status_code": status_code, "reason": reason},
        )
        self.status_code = status_code
        self.reason = reason


class RateLimitExceededError(ProviderError):
    """Raised when HTTP 429 Too Many Requests is received from the provider."""

    def __init__(
        self,
        retry_after: float | None = None,
        message: str = "Open-Meteo rate limit exceeded. Please retry later.",
        provider: str = "Open-Meteo",
    ) -> None:
        super().__init__(
            message=message,
            provider=provider,
            details={"retry_after": retry_after},
        )
        self.retry_after = retry_after


class MalformedResponseError(ProviderError):
    """Raised when provider response violates expected JSON structure."""
