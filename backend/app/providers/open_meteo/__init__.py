"""Open-Meteo external provider adapter package."""

from app.providers.open_meteo.client import (
    OpenMeteoClient,
    get_daily_forecast,
    search_destination,
)
from app.providers.open_meteo.errors import (
    HttpError,
    MalformedResponseError,
    NetworkUnavailableError,
    ProviderError,
    RateLimitExceededError,
    TimeoutError,
)
from app.providers.open_meteo.normalizers import (
    normalize_forecast_response,
    normalize_geocoding_response,
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
