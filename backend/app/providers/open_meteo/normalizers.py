"""Normalizers for transforming raw Open-Meteo API payloads to domain models."""

from datetime import UTC, date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.providers.open_meteo.errors import MalformedResponseError
from app.schemas.provider import (
    GeocodeResult,
    SourceInfo,
    WeatherDay,
    WeatherSummary,
)

OPEN_METEO_URL = "https://open-meteo.com/"
GEOCODING_ATTRIBUTION = "Location data by Open-Meteo and GeoNames (CC-BY 4.0)"
WEATHER_ATTRIBUTION = "Weather data by Open-Meteo.com (CC-BY 4.0)"

WMO_CODE_DESCRIPTIONS: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snowfall",
    73: "Moderate snowfall",
    75: "Heavy snowfall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


def get_weather_description(code: int) -> str:
    """Return human-readable description for a WMO weather code."""
    return WMO_CODE_DESCRIPTIONS.get(code, f"Weather code {code}")


class RawGeocodingLocation(BaseModel):
    """Raw geocoding location item from Open-Meteo search API."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(..., min_length=1)
    country: str = Field(..., min_length=1)
    admin1: str | None = None
    latitude: float
    longitude: float
    timezone: str = "UTC"


class RawGeocodingResponse(BaseModel):
    """Raw response envelope from Open-Meteo search API."""

    model_config = ConfigDict(extra="ignore")

    results: list[RawGeocodingLocation] = Field(default_factory=list)
    generationtime_ms: float | None = None


class RawDailyData(BaseModel):
    """Raw daily metrics array from Open-Meteo forecast API."""

    model_config = ConfigDict(extra="ignore")

    time: list[str] = Field(default_factory=list)
    temperature_2m_max: list[float] = Field(default_factory=list)
    temperature_2m_min: list[float] = Field(default_factory=list)
    precipitation_probability_max: list[int] = Field(default_factory=list)
    precipitation_sum: list[float] = Field(default_factory=list)
    weather_code: list[int] = Field(default_factory=list)


class RawForecastResponse(BaseModel):
    """Raw forecast response envelope from Open-Meteo forecast API."""

    model_config = ConfigDict(extra="ignore")

    latitude: float
    longitude: float
    utc_offset_seconds: int = 0
    timezone: str = "UTC"
    daily: RawDailyData = Field(default_factory=RawDailyData)


def normalize_geocoding_response(
    raw_json: dict[str, Any],
    data_origin: Literal["live", "mock"] = "live",
    fetched_at: datetime | None = None,
) -> list[GeocodeResult]:
    """Validate and normalize raw Open-Meteo geocoding search response."""
    if not isinstance(raw_json, dict):
        raise MalformedResponseError("Geocoding response must be a JSON object")

    try:
        parsed = RawGeocodingResponse.model_validate(raw_json)
    except ValidationError as err:
        raise MalformedResponseError(
            f"Failed to validate geocoding response structure: {err}"
        ) from err

    # Empty geocoding results are not an error; return empty list
    if not parsed.results:
        return []

    fetch_time = fetched_at or datetime.now(UTC)
    source_info = SourceInfo(
        provider="Open-Meteo",
        url=OPEN_METEO_URL,
        attribution=GEOCODING_ATTRIBUTION,
        fetched_at=fetch_time,
        data_origin=data_origin,
    )

    results: list[GeocodeResult] = []
    for loc in parsed.results:
        results.append(
            GeocodeResult(
                name=loc.name,
                country=loc.country,
                admin_region=loc.admin1,
                latitude=loc.latitude,
                longitude=loc.longitude,
                timezone=loc.timezone or "UTC",
                source=source_info,
                fetched_at=fetch_time,
            )
        )
    return results


def normalize_forecast_response(
    raw_json: dict[str, Any],
    location_name: str,
    start: date,
    end: date,
    data_origin: Literal["live", "mock"] = "live",
    fetched_at: datetime | None = None,
) -> WeatherSummary:
    """Validate and normalize raw Open-Meteo forecast response into WeatherSummary."""
    if not isinstance(raw_json, dict):
        raise MalformedResponseError("Forecast response must be a JSON object")

    try:
        parsed = RawForecastResponse.model_validate(raw_json)
    except ValidationError as err:
        raise MalformedResponseError(
            f"Failed to validate forecast response structure: {err}"
        ) from err

    daily = parsed.daily
    array_lengths = [
        len(daily.time),
        len(daily.temperature_2m_max),
        len(daily.temperature_2m_min),
        len(daily.precipitation_probability_max),
        len(daily.precipitation_sum),
        len(daily.weather_code),
    ]
    if len(set(array_lengths)) > 1:
        raise MalformedResponseError(
            "Forecast response contains inconsistent daily array lengths"
        )

    fetch_time = fetched_at or datetime.now(UTC)
    source_info = SourceInfo(
        provider="Open-Meteo",
        url=OPEN_METEO_URL,
        attribution=WEATHER_ATTRIBUTION,
        fetched_at=fetch_time,
        data_origin=data_origin,
    )

    # Build lookup table of date -> WeatherDay
    days_by_date: dict[date, WeatherDay] = {}
    for i, time_str in enumerate(daily.time):
        try:
            day_date = date.fromisoformat(time_str)
        except ValueError as err:
            raise MalformedResponseError(
                f"Invalid date format in daily forecast: {time_str}"
            ) from err

        w_code = daily.weather_code[i]
        days_by_date[day_date] = WeatherDay(
            date=day_date,
            temp_min_c=daily.temperature_2m_min[i],
            temp_max_c=daily.temperature_2m_max[i],
            precipitation_probability_pct=daily.precipitation_probability_max[i],
            precipitation_sum_mm=daily.precipitation_sum[i],
            weather_code=w_code,
            condition_description=get_weather_description(w_code),
        )

    # Match requested trip dates against available forecast days
    requested_days: list[date] = []
    curr = start
    while curr <= end:
        requested_days.append(curr)
        curr = date.fromordinal(curr.toordinal() + 1)

    matched_days = [days_by_date[d] for d in requested_days if d in days_by_date]

    total_requested = len(requested_days)
    horizon_note: str | None = None

    if not matched_days:
        horizon_note = (
            "Weather forecast is unavailable for dates beyond the 16-day "
            "forecast horizon. Check back closer to your departure date."
        )
    elif len(matched_days) < total_requested:
        horizon_note = (
            f"Forecast is only available for {len(matched_days)} of "
            f"{total_requested} trip days (16-day forecast horizon limit). "
            "Later dates are omitted."
        )

    return WeatherSummary(
        location=location_name,
        days=matched_days,
        units={"temperature": "celsius", "precipitation": "mm"},
        source=source_info,
        fetched_at=fetch_time,
        data_origin=data_origin,
        horizon_note=horizon_note,
    )
