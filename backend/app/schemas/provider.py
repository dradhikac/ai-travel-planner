"""Provider schemas for external geocoding and weather services."""

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Provenance(StrEnum):
    """Provenance classification enforcing truthfulness of data points."""

    RETRIEVED = "retrieved"
    GENERATED_SUGGESTION = "generated_suggestion"
    ESTIMATE = "estimate"
    UNKNOWN = "unknown"


class SourceInfo(BaseModel):
    """Attribution and metadata for third-party external data sources."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(..., description="Provider name (e.g. 'Open-Meteo')")
    url: str = Field(..., description="Official provider URL")
    attribution: str = Field(..., description="Required attribution notice")
    fetched_at: datetime = Field(..., description="UTC timestamp of API request")
    data_origin: Literal["live", "mock"] = Field(
        ..., description="Indicates live API vs fixture data"
    )

    @field_validator("fetched_at", mode="after")
    @classmethod
    def ensure_utc_timezone(cls, v: datetime) -> datetime:
        """Ensure fetched_at timestamp is timezone-aware UTC."""
        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v.astimezone(UTC)


class GeocodeResult(BaseModel):
    """Normalized geocoding result."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, description="Resolved location name")
    country: str = Field(..., min_length=1, description="Country name")
    admin_region: str | None = Field(
        default=None, description="State, province, or region"
    )
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    timezone: str = Field(default="UTC", description="IANA timezone name")
    source: SourceInfo
    fetched_at: datetime

    @field_validator("fetched_at", mode="after")
    @classmethod
    def ensure_utc_timezone(cls, v: datetime) -> datetime:
        """Ensure fetched_at timestamp is timezone-aware UTC."""
        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v.astimezone(UTC)


class WeatherDay(BaseModel):
    """Daily forecast metrics."""

    model_config = ConfigDict(extra="forbid")

    date: date
    temp_min_c: float
    temp_max_c: float
    precipitation_probability_pct: int = Field(..., ge=0, le=100)
    precipitation_sum_mm: float = Field(..., ge=0.0)
    weather_code: int = Field(..., description="WMO weather interpretation code")
    condition_description: str = Field(
        ..., description="Human-readable summary (e.g. 'Partly cloudy')"
    )


class WeatherSummary(BaseModel):
    """Aggregated weather forecast for a trip destination."""

    model_config = ConfigDict(extra="forbid")

    location: str = Field(..., min_length=1)
    days: list[WeatherDay] = Field(default_factory=list)
    units: dict[str, str] = Field(
        default_factory=lambda: {"temperature": "celsius", "precipitation": "mm"}
    )
    source: SourceInfo
    fetched_at: datetime
    data_origin: Literal["live", "mock"]
    horizon_note: str | None = Field(
        default=None,
        description="Notice if trip dates fall outside the 16-day forecast horizon",
    )

    @field_validator("fetched_at", mode="after")
    @classmethod
    def ensure_utc_timezone(cls, v: datetime) -> datetime:
        """Ensure fetched_at timestamp is timezone-aware UTC."""
        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v.astimezone(UTC)
