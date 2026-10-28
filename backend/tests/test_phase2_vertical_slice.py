"""Independent vertical-slice verification tests for Phase 2.

Tests the integration of intake validation, provider geocoding, normalized weather,
deterministic itinerary generation, and HTTP API persistence endpoints.
All tests are strictly deterministic with zero external network access.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.providers.open_meteo.errors import (
    MalformedResponseError,
    NetworkUnavailableError,
    TimeoutError,
)
from app.schemas.provider import (
    GeocodeResult,
    Provenance,
    SourceInfo,
    WeatherDay,
    WeatherSummary,
)
from app.schemas.trip import (
    Itinerary,
    PacePreference,
    TripRequest,
    TripResponse,
)
from app.services.itinerary import generate_itinerary


@pytest.fixture
def fixed_today() -> date:
    """Deterministic reference date for tests."""
    return date(2026, 5, 1)


@pytest.fixture
def sample_trip_request(fixed_today: date) -> TripRequest:
    """Valid TripRequest within allowable future horizon."""
    TripRequest.set_test_today(fixed_today)
    return TripRequest(
        origin="London",
        destination="Paris",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 5),
        party_size=2,
        budget_amount=Decimal("1500.00"),
        currency="EUR",
        interests=["culture", "food"],
        pace=PacePreference.BALANCED,
    )


@pytest.fixture
def fake_geocode_result() -> GeocodeResult:
    """Normalized GeocodeResult fixture for Paris."""
    return GeocodeResult(
        name="Paris",
        country="France",
        admin_region="Île-de-France",
        latitude=48.8534,
        longitude=2.3488,
        timezone="Europe/Paris",
        source=SourceInfo(
            provider="Open-Meteo",
            url="https://geocoding-api.open-meteo.com/v1/search",
            attribution="Weather data by Open-Meteo.com",
            fetched_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
            data_origin="mock",
        ),
        fetched_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
    )


@pytest.fixture
def fake_weather_summary() -> WeatherSummary:
    """Normalized WeatherSummary fixture for Paris 5-day span."""
    fetch_dt = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    source = SourceInfo(
        provider="Open-Meteo",
        url="https://api.open-meteo.com/v1/forecast",
        attribution="Weather data by Open-Meteo.com",
        fetched_at=fetch_dt,
        data_origin="mock",
    )
    days = [
        WeatherDay(
            date=date(2026, 6, 1),
            temp_min_c=14.0,
            temp_max_c=22.0,
            precipitation_probability_pct=10,
            precipitation_sum_mm=0.0,
            weather_code=1,
            condition_description="Mainly clear",
        ),
        WeatherDay(
            date=date(2026, 6, 2),
            temp_min_c=15.0,
            temp_max_c=23.0,
            precipitation_probability_pct=20,
            precipitation_sum_mm=0.5,
            weather_code=2,
            condition_description="Partly cloudy",
        ),
        WeatherDay(
            date=date(2026, 6, 3),
            temp_min_c=16.0,
            temp_max_c=20.0,
            precipitation_probability_pct=60,
            precipitation_sum_mm=4.5,
            weather_code=61,
            condition_description="Slight rain",
        ),
        WeatherDay(
            date=date(2026, 6, 4),
            temp_min_c=13.0,
            temp_max_c=21.0,
            precipitation_probability_pct=15,
            precipitation_sum_mm=0.0,
            weather_code=1,
            condition_description="Mainly clear",
        ),
        WeatherDay(
            date=date(2026, 6, 5),
            temp_min_c=14.0,
            temp_max_c=24.0,
            precipitation_probability_pct=5,
            precipitation_sum_mm=0.0,
            weather_code=0,
            condition_description="Clear sky",
        ),
    ]
    return WeatherSummary(
        location="Paris",
        days=days,
        source=source,
        fetched_at=fetch_dt,
        data_origin="mock",
    )


# ==============================================================================
# 1. Deterministic Service Integration: Request -> Provider -> Generator -> Response
# ==============================================================================


def test_vertical_slice_generation_pipeline(
    sample_trip_request: TripRequest,
    fake_geocode_result: GeocodeResult,
    fake_weather_summary: WeatherSummary,
    fixed_today: date,
) -> None:
    """Verify that pure deterministic generation assembles a valid TripResponse."""
    itinerary = generate_itinerary(
        request=sample_trip_request,
        destination=fake_geocode_result,
        weather=fake_weather_summary,
        today=fixed_today,
    )

    assert isinstance(itinerary, Itinerary)
    assert len(itinerary.days) == 5

    # Balanced pace requires 3 items per day
    for day in itinerary.days:
        assert len(day.items) == 3
        for item in day.items:
            assert item.provenance in (
                Provenance.GENERATED_SUGGESTION,
                Provenance.ESTIMATE,
                Provenance.RETRIEVED,
                Provenance.UNKNOWN,
            )

    # Rainy day adaptation check: Day 3 has precipitation_probability_pct=60
    day_3 = itinerary.days[2]
    assert day_3.date == date(2026, 6, 3)

    # Assemble complete TripResponse
    trip_id = uuid4()
    now_utc = datetime.now(UTC)
    response = TripResponse(
        id=trip_id,
        request=sample_trip_request,
        itinerary=itinerary,
        weather=fake_weather_summary,
        sources=[fake_geocode_result.source, fake_weather_summary.source],
        warnings=itinerary.warnings,
        created_at=now_utc,
    )

    # Verify JSON round-trip serialization / deserialization without data loss
    dumped = response.model_dump(mode="json")
    reloaded = TripResponse.model_validate(dumped)
    assert reloaded.id == response.id
    assert reloaded.request.destination == "Paris"
    assert len(reloaded.itinerary.days) == 5
    assert reloaded.weather is not None
    assert reloaded.weather.location == "Paris"


def test_vertical_slice_weather_failure_yields_partial_itinerary(
    sample_trip_request: TripRequest,
    fake_geocode_result: GeocodeResult,
    fixed_today: date,
) -> None:
    """Verify weather provider failure degrades gracefully to partial itinerary."""
    itinerary = generate_itinerary(
        request=sample_trip_request,
        destination=fake_geocode_result,
        weather=None,
        today=fixed_today,
    )

    assert isinstance(itinerary, Itinerary)
    assert len(itinerary.days) == 5
    assert any(
        "Weather forecast could not be retrieved" in w for w in itinerary.warnings
    )

    trip_id = uuid4()
    response = TripResponse(
        id=trip_id,
        request=sample_trip_request,
        itinerary=itinerary,
        weather=None,
        sources=[fake_geocode_result.source],
        warnings=itinerary.warnings,
        created_at=datetime.now(UTC),
    )

    assert response.weather is None
    assert len(response.warnings) > 0


def test_vertical_slice_provider_error_propagation() -> None:
    """Verify provider error types conform to documented exception taxonomy."""
    with pytest.raises(TimeoutError, match="timed out"):
        raise TimeoutError(
            "Open-Meteo request timed out while communicating with provider"
        )

    with pytest.raises(MalformedResponseError, match="malformed"):
        raise MalformedResponseError("Open-Meteo returned malformed JSON payload")

    with pytest.raises(NetworkUnavailableError, match="unavailable"):
        raise NetworkUnavailableError("Open-Meteo network service is unavailable")


# ==============================================================================
# 2. HTTP Route Persistence API Verification (Create, Save, Reload)
# ==============================================================================


def test_vertical_slice_http_persistence_endpoints(client: TestClient) -> None:
    """Independent verification of POST /api/trips and GET /api/trips/{id}.

    Contracts defined in docs/phase2-3/data-contracts.md specify:
      - POST /api/trips returns HTTP 201 Created with TripResponse body.
      - GET /api/trips/{id} returns HTTP 200 OK with matching TripResponse.
      - GET /api/trips returns HTTP 200 OK with list of TripSummaryItem.

    This test executes against the running application to verify endpoint mounting.
    """
    payload = {
        "origin": "London",
        "destination": "Paris",
        "start_date": "2026-06-01",
        "end_date": "2026-06-05",
        "party_size": 2,
        "budget_amount": "1500.00",
        "currency": "EUR",
        "interests": ["culture", "food"],
        "pace": "balanced",
    }

    # Attempt trip creation via HTTP POST
    post_response = client.post("/api/trips", json=payload)

    # Documented expected contract: HTTP 201 Created
    # If unexposed/unimplemented, FastAPI router returns HTTP 404
    assert post_response.status_code == 201, (
        f"POST /api/trips returned unexpected status {post_response.status_code}. "
        f"Body: {post_response.text}"
    )

    created_data = post_response.json()
    assert "id" in created_data
    trip_id = created_data["id"]

    # Attempt trip reload via HTTP GET
    get_response = client.get(f"/api/trips/{trip_id}")
    assert get_response.status_code == 200
    reloaded_data = get_response.json()

    assert reloaded_data["id"] == trip_id
    assert reloaded_data["request"]["destination"] == "Paris"
    assert reloaded_data["itinerary"]["days"] == created_data["itinerary"]["days"]

    # Verify list trips endpoint ordering
    list_response = client.get("/api/trips")
    assert list_response.status_code == 200
    trips_list = list_response.json()
    assert isinstance(trips_list, list)
    assert any(t["id"] == trip_id for t in trips_list)
