"""Pydantic schemas for request, response, and domain models."""

from app.schemas.errors import (
    ErrorDetail,
    ErrorResponse,
    pydantic_validation_error_to_error_response,
)
from app.schemas.health import HealthResponse
from app.schemas.provider import (
    GeocodeResult,
    Provenance,
    SourceInfo,
    WeatherDay,
    WeatherSummary,
)
from app.schemas.trip import (
    ALLOWED_CURRENCIES,
    Itinerary,
    ItineraryDay,
    ItineraryItem,
    PacePreference,
    TimeOfDay,
    TripRequest,
    TripResponse,
)
from app.schemas.version import VersionResponse

__all__ = [
    "ALLOWED_CURRENCIES",
    "ErrorDetail",
    "ErrorResponse",
    "GeocodeResult",
    "HealthResponse",
    "Itinerary",
    "ItineraryDay",
    "ItineraryItem",
    "PacePreference",
    "Provenance",
    "SourceInfo",
    "TimeOfDay",
    "TripRequest",
    "TripResponse",
    "VersionResponse",
    "WeatherDay",
    "WeatherSummary",
    "pydantic_validation_error_to_error_response",
]
