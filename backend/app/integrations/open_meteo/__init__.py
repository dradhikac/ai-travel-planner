"""Integration alias for Open-Meteo provider adapter."""

from app.providers.open_meteo import (
    HttpError,
    MalformedResponseError,
    NetworkUnavailableError,
    OpenMeteoClient,
    ProviderError,
    RateLimitExceededError,
    TimeoutError,
    get_daily_forecast,
    normalize_forecast_response,
    normalize_geocoding_response,
    search_destination,
)

__all__ = [
    "HttpError",
    "MalformedResponseError",
    "NetworkUnavailableError",
    "OpenMeteoClient",
    "ProviderError",
    "RateLimitExceededError",
    "TimeoutError",
    "get_daily_forecast",
    "normalize_forecast_response",
    "normalize_geocoding_response",
    "search_destination",
]
