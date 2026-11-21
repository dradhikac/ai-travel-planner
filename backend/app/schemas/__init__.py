"""Pydantic schemas for request, response, and domain models."""

from app.schemas.errors import (
    ErrorDetail,
    ErrorResponse,
    pydantic_validation_error_to_error_response,
)
from app.schemas.health import HealthResponse
from app.schemas.itinerary_v2 import (
    Activity,
    ActivityLocation,
    CostStatus,
    DurationBasis,
    DurationEstimate,
    ItineraryActivity,
    ItineraryActivityV2,
    ItineraryDayV2,
    ItineraryV2,
    Location,
    parse_itinerary_payload,
    upgrade_itinerary_v1_to_v2,
)
from app.schemas.provider import (
    GeocodeResult,
    Provenance,
    RouteSummary,
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
    ToolActivity,
    TripRequest,
    TripResponse,
)
from app.schemas.version import VersionResponse

__all__ = [
    "ALLOWED_CURRENCIES",
    "Activity",
    "ActivityLocation",
    "CostStatus",
    "DurationBasis",
    "DurationEstimate",
    "ErrorDetail",
    "ErrorResponse",
    "GeocodeResult",
    "HealthResponse",
    "Itinerary",
    "ItineraryActivity",
    "ItineraryActivityV2",
    "ItineraryDay",
    "ItineraryDayV2",
    "ItineraryItem",
    "ItineraryV2",
    "Location",
    "PacePreference",
    "Provenance",
    "RouteSummary",
    "SourceInfo",
    "TimeOfDay",
    "ToolActivity",
    "TripRequest",
    "TripResponse",
    "VersionResponse",
    "WeatherDay",
    "WeatherSummary",
    "parse_itinerary_payload",
    "pydantic_validation_error_to_error_response",
    "upgrade_itinerary_v1_to_v2",
]
