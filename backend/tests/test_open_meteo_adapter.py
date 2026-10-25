"""Unit tests for Open-Meteo geocoding and weather forecast provider adapter."""

import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.core.config import Settings
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
from app.schemas.provider import GeocodeResult, WeatherSummary

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "open_meteo"


def load_fixture_json(filename: str) -> dict[str, Any]:
    """Load JSON test fixture from test fixtures directory."""
    with open(FIXTURES_DIR / filename, encoding="utf-8") as f:
        return json.load(f)


def test_no_real_socket_asserted() -> None:
    """Verify test suite utilizes httpx.MockTransport with no socket connections."""
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json={}))
    client = OpenMeteoClient(transport=transport)
    assert isinstance(client.transport, httpx.MockTransport)
    assert not isinstance(client.transport, httpx.AsyncHTTPTransport)


def test_geocoding_success_normalization() -> None:
    """Test geocoding search normalizes response into GeocodeResult domain models."""
    paris_payload = load_fixture_json("geocode_paris.json")
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        assert "geocoding-api.open-meteo.com" in str(request.url)
        assert request.url.params["name"] == "Paris"
        assert request.url.params["count"] == "5"
        return httpx.Response(200, json=paris_payload)

    transport = httpx.MockTransport(handler)
    client = OpenMeteoClient(transport=transport)

    results = asyncio.run(client.search_destination("Paris", count=5))

    assert call_count == 1
    assert len(results) == 1
    item = results[0]
    assert isinstance(item, GeocodeResult)
    assert item.name == "Paris"
    assert item.country == "France"
    assert item.admin_region == "Île-de-France"
    assert item.latitude == 48.85341
    assert item.longitude == 2.3488
    assert item.timezone == "Europe/Paris"
    assert item.source.provider == "Open-Meteo"
    assert "CC-BY 4.0" in item.source.attribution
    assert item.source.data_origin == "live"
    assert isinstance(item.fetched_at, datetime)
    assert item.fetched_at.tzinfo == UTC


def test_geocoding_empty_results_returns_empty_list() -> None:
    """Test empty search result is treated as empty list rather than an error."""
    empty_payload = load_fixture_json("geocode_empty.json")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=empty_payload)

    transport = httpx.MockTransport(handler)
    client = OpenMeteoClient(transport=transport)

    results = asyncio.run(client.search_destination("NowhereLandXYZ"))
    assert results == []


def test_forecast_success_normalization() -> None:
    """Test daily weather forecast normalization into WeatherSummary."""
    forecast_payload = load_fixture_json("forecast_paris_7day.json")
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        assert "api.open-meteo.com" in str(request.url)
        assert request.url.params["latitude"] == "48.85341"
        assert request.url.params["longitude"] == "2.3488"
        assert request.url.params["start_date"] == "2026-06-10"
        assert request.url.params["end_date"] == "2026-06-12"
        return httpx.Response(200, json=forecast_payload)

    transport = httpx.MockTransport(handler)
    client = OpenMeteoClient(transport=transport)

    summary = asyncio.run(
        client.get_daily_forecast(
            latitude=48.85341,
            longitude=2.3488,
            start=date(2026, 6, 10),
            end=date(2026, 6, 12),
            location_name="Paris, France",
        )
    )

    assert call_count == 1
    assert isinstance(summary, WeatherSummary)
    assert summary.location == "Paris, France"
    assert summary.data_origin == "live"
    assert summary.source.provider == "Open-Meteo"
    assert "CC-BY 4.0" in summary.source.attribution
    assert summary.horizon_note is None
    assert len(summary.days) == 3

    d1 = summary.days[0]
    assert d1.date == date(2026, 6, 10)
    assert d1.temp_max_c == 22.4
    assert d1.temp_min_c == 12.1
    assert d1.precipitation_probability_pct == 10
    assert d1.precipitation_sum_mm == 0.0
    assert d1.weather_code == 1
    assert d1.condition_description == "Mainly clear"

    d3 = summary.days[2]
    assert d3.date == date(2026, 6, 12)
    assert d3.temp_max_c == 21.8
    assert d3.temp_min_c == 14.0
    assert d3.precipitation_probability_pct == 70
    assert d3.precipitation_sum_mm == 6.2
    assert d3.weather_code == 61
    assert d3.condition_description == "Slight rain"


def test_forecast_out_of_horizon_dates_returns_empty_days_with_note() -> None:
    """Test dates beyond 16-day horizon return empty days list and informative note."""
    beyond_payload = load_fixture_json("forecast_beyond_horizon.json")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=beyond_payload)

    transport = httpx.MockTransport(handler)
    client = OpenMeteoClient(transport=transport)

    summary = asyncio.run(
        client.get_daily_forecast(
            latitude=48.85341,
            longitude=2.3488,
            start=date(2027, 8, 1),
            end=date(2027, 8, 7),
            location_name="Paris, France",
        )
    )

    assert isinstance(summary, WeatherSummary)
    assert len(summary.days) == 0
    assert summary.horizon_note is not None
    assert "16-day" in summary.horizon_note


def test_forecast_partial_horizon_returns_available_days_with_note() -> None:
    """Test trip spanning past horizon returns partial horizon note."""
    forecast_payload = load_fixture_json("forecast_paris_7day.json")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=forecast_payload)

    transport = httpx.MockTransport(handler)
    client = OpenMeteoClient(transport=transport)

    # Fixture contains 2026-06-10 through 2026-06-16 (7 days).
    # Request 2026-06-15 to 2026-06-18 (4 days, only 2 exist in fixture: 15th, 16th).
    summary = asyncio.run(
        client.get_daily_forecast(
            latitude=48.85341,
            longitude=2.3488,
            start=date(2026, 6, 15),
            end=date(2026, 6, 18),
            location_name="Paris",
        )
    )

    assert len(summary.days) == 2
    assert summary.days[0].date == date(2026, 6, 15)
    assert summary.days[1].date == date(2026, 6, 16)
    assert summary.horizon_note is not None
    assert "2 of 4 trip days" in summary.horizon_note


def test_http_400_never_retried() -> None:
    """Test HTTP 400 client error raises HttpError and is NEVER retried."""
    error_400 = load_fixture_json("error_400_invalid_var.json")
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(400, json=error_400)

    transport = httpx.MockTransport(handler)
    client = OpenMeteoClient(transport=transport)

    with pytest.raises(HttpError) as exc_info:
        asyncio.run(client.search_destination("Berlin"))

    assert call_count == 1
    assert exc_info.value.status_code == 400
    assert "WeatherVariable" in (exc_info.value.reason or "")
    # Must not leak secret parameters or raw URLs into message
    assert "Open-Meteo request error: HTTP 400" in exc_info.value.message


def test_http_404_never_retried() -> None:
    """Test HTTP 404 client error raises HttpError and is not retried."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(404, text="Not Found")

    transport = httpx.MockTransport(handler)
    client = OpenMeteoClient(transport=transport)

    with pytest.raises(HttpError) as exc_info:
        asyncio.run(client.search_destination("Somewhere"))

    assert call_count == 1
    assert exc_info.value.status_code == 404


def test_http_500_retries_and_exhausts() -> None:
    """Test HTTP 5xx error retries up to configured max retries."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(500, text="Internal Server Error")

    transport = httpx.MockTransport(handler)
    settings = Settings(OPEN_METEO_MAX_RETRIES=1)
    client = OpenMeteoClient(settings=settings, transport=transport)

    with pytest.raises(HttpError) as exc_info:
        asyncio.run(client.search_destination("Munich"))

    # Initial attempt + 1 retry = 2 attempts
    assert call_count == 2
    assert exc_info.value.status_code == 500


def test_http_429_surfaces_retry_after_and_never_retries() -> None:
    """Test HTTP 429 raises RateLimitExceededError and never retries."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(429, headers={"Retry-After": "45.5"})

    transport = httpx.MockTransport(handler)
    client = OpenMeteoClient(transport=transport)

    with pytest.raises(RateLimitExceededError) as exc_info:
        asyncio.run(client.search_destination("Vienna"))

    assert call_count == 1
    assert exc_info.value.retry_after == 45.5
    assert "rate limit exceeded" in str(exc_info.value).lower()


def test_http_429_without_retry_after_header() -> None:
    """Test HTTP 429 without Retry-After header leaves retry_after as None."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429)

    transport = httpx.MockTransport(handler)
    client = OpenMeteoClient(transport=transport)

    with pytest.raises(RateLimitExceededError) as exc_info:
        asyncio.run(client.search_destination("Vienna"))

    assert exc_info.value.retry_after is None


def test_timeout_retry_then_success() -> None:
    """Test request timeout on first attempt succeeds on bounded retry."""
    call_count = 0
    paris_payload = load_fixture_json("geocode_paris.json")

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise httpx.ReadTimeout("Read timed out")
        return httpx.Response(200, json=paris_payload)

    transport = httpx.MockTransport(handler)
    settings = Settings(OPEN_METEO_MAX_RETRIES=1)
    client = OpenMeteoClient(settings=settings, transport=transport)

    results = asyncio.run(client.search_destination("Paris"))
    assert call_count == 2
    assert len(results) == 1
    assert results[0].name == "Paris"


def test_timeout_exhausting_retries_raises_timeout_error() -> None:
    """Test timeout across all retry attempts raises typed TimeoutError."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        raise httpx.ConnectTimeout("Connection timed out")

    transport = httpx.MockTransport(handler)
    settings = Settings(OPEN_METEO_MAX_RETRIES=1)
    client = OpenMeteoClient(settings=settings, transport=transport)

    with pytest.raises(TimeoutError) as exc_info:
        asyncio.run(client.search_destination("Paris"))

    assert call_count == 2
    assert "timed out" in str(exc_info.value).lower()


def test_network_unavailable_error() -> None:
    """Test connection error across all retries raises NetworkUnavailableError."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        raise httpx.ConnectError("Connection refused")

    transport = httpx.MockTransport(handler)
    settings = Settings(OPEN_METEO_MAX_RETRIES=1)
    client = OpenMeteoClient(settings=settings, transport=transport)

    with pytest.raises(NetworkUnavailableError) as exc_info:
        asyncio.run(client.search_destination("Paris"))

    assert call_count == 2
    assert "unavailable" in str(exc_info.value).lower()


def test_malformed_json_response() -> None:
    """Test non-JSON response raises MalformedResponseError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>502 Bad Gateway</html>")

    transport = httpx.MockTransport(handler)
    client = OpenMeteoClient(transport=transport)

    with pytest.raises(MalformedResponseError):
        asyncio.run(client.search_destination("Paris"))


def test_malformed_json_missing_required_fields() -> None:
    """Test payload failing Pydantic schema validation raises MalformedResponseError."""

    def handler(request: httpx.Request) -> httpx.Response:
        # Invalid schema for geocoding item (name is integer, missing country)
        return httpx.Response(200, json={"results": [{"name": 123}]})

    transport = httpx.MockTransport(handler)
    client = OpenMeteoClient(transport=transport)

    with pytest.raises(MalformedResponseError) as exc_info:
        asyncio.run(client.search_destination("Paris"))

    assert "validate geocoding response" in str(exc_info.value)


def test_malformed_forecast_inconsistent_array_lengths() -> None:
    """Test daily metrics with mismatched array lengths raise MalformedResponseError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "latitude": 48.85,
                "longitude": 2.35,
                "daily": {
                    "time": ["2026-06-10", "2026-06-11"],
                    "temperature_2m_max": [25.0],  # Mismatch: length 1 vs length 2
                    "temperature_2m_min": [15.0, 16.0],
                    "precipitation_probability_max": [0, 10],
                    "precipitation_sum": [0.0, 0.0],
                    "weather_code": [0, 1],
                },
            },
        )

    transport = httpx.MockTransport(handler)
    client = OpenMeteoClient(transport=transport)

    with pytest.raises(MalformedResponseError) as exc_info:
        asyncio.run(
            client.get_daily_forecast(
                48.85, 2.35, start=date(2026, 6, 10), end=date(2026, 6, 11)
            )
        )

    assert "inconsistent daily array lengths" in str(exc_info.value)


def test_input_validation_before_request_made() -> None:
    """Test validation catches invalid inputs BEFORE initiating any HTTP request."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    client = OpenMeteoClient(transport=transport)

    # Empty name
    with pytest.raises(ValueError, match="Location name cannot be empty"):
        asyncio.run(client.search_destination("   "))

    # Bad count bounds
    with pytest.raises(ValueError, match="Count must be between"):
        asyncio.run(client.search_destination("Paris", count=0))
    with pytest.raises(ValueError, match="Count must be between"):
        asyncio.run(client.search_destination("Paris", count=101))

    # Bad latitude
    with pytest.raises(ValueError, match="Latitude must be between"):
        asyncio.run(
            client.get_daily_forecast(
                latitude=91.0,
                longitude=0.0,
                start=date(2026, 6, 1),
                end=date(2026, 6, 2),
            )
        )

    # Bad longitude
    with pytest.raises(ValueError, match="Longitude must be between"):
        asyncio.run(
            client.get_daily_forecast(
                latitude=0.0,
                longitude=-181.0,
                start=date(2026, 6, 1),
                end=date(2026, 6, 2),
            )
        )

    # Inverted date range
    with pytest.raises(ValueError, match="End date must be on or after"):
        asyncio.run(
            client.get_daily_forecast(
                latitude=0.0,
                longitude=0.0,
                start=date(2026, 6, 10),
                end=date(2026, 6, 5),
            )
        )

    # Verify that handler was NEVER called
    assert call_count == 0


def test_mock_mode_labelled_mock_and_opens_no_socket() -> None:
    """Test PROVIDER_MODE=mock returns deterministic mock data without network."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        raise RuntimeError("Transport should never be contacted in mock mode")

    transport = httpx.MockTransport(handler)
    mock_settings = Settings(PROVIDER_MODE="mock")
    client = OpenMeteoClient(settings=mock_settings, transport=transport)

    # 1. Geocoding search in mock mode
    tokyo_results = asyncio.run(client.search_destination("Tokyo"))
    assert call_count == 0
    assert len(tokyo_results) >= 1
    assert tokyo_results[0].name == "Tokyo"
    assert tokyo_results[0].source.data_origin == "mock"

    # 2. Weather forecast in mock mode (near term)
    near_start = date.today() + timedelta(days=2)
    near_end = near_start + timedelta(days=2)
    forecast = asyncio.run(
        client.get_daily_forecast(
            latitude=35.6895,
            longitude=139.6917,
            start=near_start,
            end=near_end,
            location_name="Tokyo, Japan",
        )
    )
    assert call_count == 0
    assert forecast.data_origin == "mock"
    assert forecast.source.data_origin == "mock"
    assert len(forecast.days) == 3

    # 3. Weather forecast beyond horizon in mock mode
    far_start = date.today() + timedelta(days=30)
    far_end = far_start + timedelta(days=3)
    far_forecast = asyncio.run(
        client.get_daily_forecast(
            latitude=35.6895,
            longitude=139.6917,
            start=far_start,
            end=far_end,
            location_name="Tokyo, Japan",
        )
    )
    assert call_count == 0
    assert far_forecast.data_origin == "mock"
    assert len(far_forecast.days) == 0
    assert far_forecast.horizon_note is not None


def test_module_level_convenience_functions() -> None:
    """Test top-level search_destination and get_daily_forecast functions."""
    tokyo_payload = load_fixture_json("geocode_tokyo.json")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=tokyo_payload)

    transport = httpx.MockTransport(handler)
    custom_client = OpenMeteoClient(transport=transport)

    results = asyncio.run(search_destination("Tokyo", count=3, client=custom_client))
    assert len(results) == 1
    assert results[0].name == "Tokyo"

    forecast_payload = load_fixture_json("forecast_paris_7day.json")

    def forecast_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=forecast_payload)

    custom_forecast_client = OpenMeteoClient(
        transport=httpx.MockTransport(forecast_handler)
    )
    summary = asyncio.run(
        get_daily_forecast(
            latitude=48.85,
            longitude=2.35,
            start=date(2026, 6, 10),
            end=date(2026, 6, 11),
            client=custom_forecast_client,
        )
    )
    assert len(summary.days) == 2


def test_integrations_alias_backward_compatibility() -> None:
    """Verify app.integrations.open_meteo exports identical symbols."""
    from app.integrations.open_meteo import (
        HttpError as AliasHttpError,
    )
    from app.integrations.open_meteo import (
        OpenMeteoClient as AliasOpenMeteoClient,
    )
    from app.integrations.open_meteo import (
        ProviderError as AliasProviderError,
    )
    from app.integrations.open_meteo import (
        RateLimitExceededError as AliasRateLimitExceededError,
    )
    from app.integrations.open_meteo import (
        TimeoutError as AliasTimeoutError,
    )
    from app.integrations.open_meteo import (
        get_daily_forecast as alias_get_forecast,
    )
    from app.integrations.open_meteo import (
        search_destination as alias_search_dest,
    )

    assert AliasOpenMeteoClient is OpenMeteoClient
    assert AliasProviderError is ProviderError
    assert AliasTimeoutError is TimeoutError
    assert AliasHttpError is HttpError
    assert AliasRateLimitExceededError is RateLimitExceededError
    assert alias_search_dest is search_destination
    assert alias_get_forecast is get_daily_forecast
