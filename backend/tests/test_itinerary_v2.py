"""Tests for Structured Itinerary Schema v2 and non-destructive v1 upgrader.

Verifies Schema v2 Pydantic models, duration bounds, source attribution rules,
stable activity IDs, in-memory v1 upgrade compatibility, round-trip serialization,
deterministic generator output, and API response integration.
"""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.itinerary_v2 import (
    Activity,
    ActivityLocation,
    CostStatus,
    DurationBasis,
    DurationEstimate,
    Itinerary,
    ItineraryActivity,
    ItineraryActivityV2,
    ItineraryDay,
    ItineraryDayV2,
    ItineraryV2,
    Location,
    parse_itinerary_payload,
)
from app.schemas.provider import (
    GeocodeResult,
    Provenance,
    SourceInfo,
    WeatherDay,
    WeatherSummary,
)
from app.schemas.trip import PacePreference, TripRequest, TripResponse
from app.services.itinerary import generate_itinerary

FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "itinerary" / "itinerary_v1_sample.json"
)


# ==============================================================================
# 1. Schema v2 Model Validation & Field Contracts
# ==============================================================================


def test_valid_v2_itinerary_construction() -> None:
    """ItineraryV2 validates a complete conforming schema v2 object."""
    source = SourceInfo(
        provider="Open-Meteo",
        url="https://api.open-meteo.com/v1/forecast",
        attribution="Weather data by Open-Meteo.com",
        fetched_at=datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC),
        data_origin="live",
    )
    location = ActivityLocation(
        name="Eiffel Tower",
        latitude=48.8584,
        longitude=2.2945,
        source_ref="https://api.open-meteo.com/v1/forecast",
    )
    duration = DurationEstimate(
        min_minutes=60,
        max_minutes=120,
        basis=DurationBasis.HEURISTIC,
    )
    activity = ItineraryActivityV2(
        id="day_1_act_1",
        title="Ascend Eiffel Tower",
        description="Visit the iconic iron lattice tower.",
        time_of_day="morning",
        interest_tags=["sightseeing", "architecture"],
        location=location,
        duration_estimate=duration,
        source_refs=["https://api.open-meteo.com/v1/forecast"],
        provenance=Provenance.GENERATED_SUGGESTION,
        cost_status=CostStatus.ESTIMATE,
        cost_note="€25 estimated admission",
        uncertainty_notes=["Subject to weather conditions"],
    )
    day = ItineraryDayV2(
        day_number=1,
        date=date(2026, 6, 10),
        activities=[activity],
        uncertainty_notes=["Day 1 plan"],
    )
    itinerary = ItineraryV2(
        schema_version=2,
        summary="A magnificent 1-day exploration of Paris.",
        sources=[source],
        warnings=["Check ticket availability"],
        days=[day],
    )

    assert itinerary.schema_version == 2
    assert len(itinerary.days) == 1
    assert itinerary.days[0].day_number == 1
    assert len(itinerary.days[0].activities) == 1
    act = itinerary.days[0].activities[0]
    assert act.id == "day_1_act_1"
    assert act.title == "Ascend Eiffel Tower"
    assert act.duration_estimate is not None
    assert act.duration_estimate.basis == DurationBasis.HEURISTIC
    assert act.cost_status == CostStatus.ESTIMATE


def test_schema_aliases_match_canonical_classes() -> None:
    """Convenience aliases point to identical Schema v2 classes."""
    assert Activity is ItineraryActivityV2
    assert ItineraryActivity is ItineraryActivityV2
    assert Location is ActivityLocation
    assert ItineraryDay is ItineraryDayV2
    assert Itinerary is ItineraryV2


def test_extra_fields_forbidden_on_all_v2_models() -> None:
    """ConfigDict extra='forbid' rejects arbitrary undocumented fields."""
    with pytest.raises(ValidationError):
        ActivityLocation(name="Paris", unexpected_field="disallowed")

    with pytest.raises(ValidationError):
        DurationEstimate(min_minutes=30, basis=DurationBasis.UNKNOWN, extra="fail")

    with pytest.raises(ValidationError):
        ItineraryActivityV2(
            id="act_1",
            title="Walk",
            unknown_attribute="invalid",
        )

    with pytest.raises(ValidationError):
        ItineraryDayV2(
            day_number=1,
            date=date(2026, 6, 10),
            bogus_key=123,
        )

    with pytest.raises(ValidationError):
        ItineraryV2(
            schema_version=2,
            summary="Summary",
            unsupported_root_field="fail",
        )


def test_duration_estimate_bounds_and_ordering() -> None:
    """DurationEstimate validates bounds and enforces min <= max."""
    valid_dur = DurationEstimate(min_minutes=30, max_minutes=90)
    assert valid_dur.min_minutes == 30
    assert valid_dur.max_minutes == 90
    assert valid_dur.basis == DurationBasis.HEURISTIC

    with pytest.raises(ValidationError) as exc_info:
        DurationEstimate(min_minutes=120, max_minutes=60)
    assert "min_minutes cannot exceed max_minutes" in str(exc_info.value)

    with pytest.raises(ValidationError):
        DurationEstimate(min_minutes=4)  # ge=5 violated

    with pytest.raises(ValidationError):
        DurationEstimate(max_minutes=2000)  # le=1440 violated


def test_location_coordinate_bounds() -> None:
    """ActivityLocation validates geographic coordinate limits."""
    loc = ActivityLocation(name="Point", latitude=45.0, longitude=-93.0)
    assert loc.latitude == 45.0
    assert loc.longitude == -93.0

    with pytest.raises(ValidationError):
        ActivityLocation(name="BadLat", latitude=95.0, longitude=0.0)

    with pytest.raises(ValidationError):
        ActivityLocation(name="BadLon", latitude=0.0, longitude=-185.0)


def test_retrieved_cost_requires_source_refs() -> None:
    """Activities marked cost_status='retrieved' require at least one source_ref."""
    with pytest.raises(ValidationError) as exc_info:
        ItineraryActivityV2(
            id="act_retrieved_cost_no_source",
            title="Paid Attraction",
            cost_status=CostStatus.RETRIEVED,
            source_refs=[],
        )
    assert "cost_status='retrieved' must specify at least one source_ref" in str(
        exc_info.value
    )

    # Valid when source_ref is supplied
    valid_act = ItineraryActivityV2(
        id="act_retrieved_cost_with_source",
        title="Paid Attraction",
        cost_status=CostStatus.RETRIEVED,
        source_refs=["https://provider.example/rates"],
    )
    assert valid_act.cost_status == CostStatus.RETRIEVED


def test_retrieved_provenance_requires_source_refs() -> None:
    """Activities marked provenance='retrieved' require at least one source_ref."""
    with pytest.raises(ValidationError) as exc_info:
        ItineraryActivityV2(
            id="act_retrieved_prov_no_source",
            title="Retrieved Museum Hours",
            provenance=Provenance.RETRIEVED,
            source_refs=[],
        )
    assert "provenance='retrieved' must specify at least one source_ref" in str(
        exc_info.value
    )

    valid_act = ItineraryActivityV2(
        id="act_retrieved_prov_with_source",
        title="Retrieved Museum Hours",
        provenance=Provenance.RETRIEVED,
        source_refs=["https://museum.example/hours"],
    )
    assert valid_act.provenance == Provenance.RETRIEVED


def test_schema_version_strictly_literal_2() -> None:
    """ItineraryV2 enforces schema_version=2."""
    itin = ItineraryV2(summary="Test summary")
    assert itin.schema_version == 2

    with pytest.raises(ValidationError):
        ItineraryV2.model_validate({"schema_version": 1, "summary": "Test"})

    with pytest.raises(ValidationError):
        ItineraryV2.model_validate({"schema_version": 3, "summary": "Test"})


# ==============================================================================
# 2. In-Memory v1 to v2 Upgrader
# ==============================================================================


def test_v1_sample_fixture_upgrades_cleanly() -> None:
    """Stored Phase 2 v1 JSON payload upgrades in-memory to valid Schema v2."""
    assert FIXTURE_PATH.is_file(), f"Fixture file not found: {FIXTURE_PATH}"
    with FIXTURE_PATH.open("r", encoding="utf-8") as f:
        v1_payload = json.load(f)

    # Upgrader reads payload directly
    v2_itinerary = parse_itinerary_payload(v1_payload)

    assert isinstance(v2_itinerary, ItineraryV2)
    assert v2_itinerary.schema_version == 2
    assert "3-day itinerary for Paris" in v2_itinerary.summary
    assert len(v2_itinerary.days) == 2

    # Day 1 inspection
    day_1 = v2_itinerary.days[0]
    assert day_1.day_number == 1
    assert day_1.date == date(2026, 6, 10)
    assert len(day_1.activities) == 4

    # Activity 1: Weather briefing
    act_1 = day_1.activities[0]
    assert act_1.id == "day_1_act_1"
    assert act_1.title == "Weather Briefing: Paris"
    assert act_1.description is not None
    assert "Moderate rain" in act_1.description
    assert act_1.source_refs == ["https://api.open-meteo.com/v1/forecast"]
    assert act_1.location is None
    assert act_1.duration_estimate is not None
    assert act_1.duration_estimate.basis == DurationBasis.HEURISTIC
    assert act_1.cost_status == CostStatus.UNKNOWN
    assert any("Retrieved from Open-Meteo" in note for note in act_1.uncertainty_notes)

    # Activity 2: Museum visit
    act_2 = day_1.activities[1]
    assert act_2.id == "day_1_act_2"
    assert act_2.title == "Major Art & Cultural Gallery Visit in Paris"
    assert act_2.cost_status == CostStatus.ESTIMATE
    assert act_2.cost_note is not None
    assert "€100.00" in act_2.cost_note
    assert act_2.source_refs == ["https://api.open-meteo.com/v1/forecast"]
    assert len(act_2.uncertainty_notes) > 0

    # Activity 3: Food hall
    act_3 = day_1.activities[2]
    assert act_3.id == "day_1_act_3"
    assert act_3.source_refs == []
    assert act_3.cost_status == CostStatus.ESTIMATE

    # Backward compatibility properties
    assert day_1.items == day_1.activities
    assert act_1.source_ref == "https://api.open-meteo.com/v1/forecast"
    assert act_2.cost_estimate == act_2.cost_note
    assert act_1.note is not None and "Retrieved from Open-Meteo" in act_1.note


def test_upgrade_v1_with_explicit_schema_version_1() -> None:
    """Payload explicitly marked schema_version=1 routes through the v1 upgrader."""
    payload_v1 = {
        "schema_version": 1,
        "summary": "1-day Rome trip",
        "days": [
            {
                "day_number": 1,
                "date": "2026-06-15",
                "items": [
                    {
                        "title": "Colosseum Stroll",
                        "time_of_day": "morning",
                        "description": "View ancient amphitheatre facade.",
                        "provenance": "generated_suggestion",
                        "cost_estimate": "Free exterior viewing",
                    }
                ],
            }
        ],
    }
    result = parse_itinerary_payload(payload_v1)
    assert result.schema_version == 2
    assert len(result.days) == 1
    assert result.days[0].activities[0].id == "day_1_act_1"
    assert result.days[0].activities[0].cost_status == CostStatus.ESTIMATE


def test_unknown_schema_version_rejected() -> None:
    """Unknown schema versions raise ValueError with clear explanatory message."""
    invalid_versions = [0, 3, 99, -1, "beta", "2.0-draft"]
    for ver in invalid_versions:
        payload = {
            "schema_version": ver,
            "summary": "Sample itinerary",
            "days": [],
        }
        with pytest.raises(ValueError) as exc_info:
            parse_itinerary_payload(payload)
        assert f"Unsupported itinerary schema version: {ver}" in str(exc_info.value)


def test_parse_itinerary_payload_from_json_string() -> None:
    """parse_itinerary_payload parses JSON-encoded strings directly."""
    v2_json = json.dumps(
        {
            "schema_version": 2,
            "summary": "Valid string payload",
            "sources": [],
            "warnings": [],
            "days": [],
        }
    )
    itin = parse_itinerary_payload(v2_json)
    assert itin.schema_version == 2
    assert itin.summary == "Valid string payload"

    with pytest.raises(ValueError) as exc_info:
        parse_itinerary_payload("not valid json")
    assert "Invalid JSON string payload" in str(exc_info.value)


# ==============================================================================
# 3. Round-Trip Serialization
# ==============================================================================


def test_round_trip_v2_model_dump_and_parse() -> None:
    """A conforming ItineraryV2 round-trips through JSON without information loss."""
    original = ItineraryV2(
        schema_version=2,
        summary="Round-trip Paris itinerary",
        sources=[
            SourceInfo(
                provider="Open-Meteo",
                url="https://api.open-meteo.com/v1/forecast",
                attribution="Weather data by Open-Meteo.com",
                fetched_at=datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC),
                data_origin="live",
            )
        ],
        warnings=["Sample warning"],
        days=[
            ItineraryDayV2(
                day_number=1,
                date=date(2026, 6, 10),
                activities=[
                    ItineraryActivityV2(
                        id="day_1_act_1",
                        title="Louvre Museum",
                        description="Art exhibitions.",
                        time_of_day="morning",
                        interest_tags=["art", "museums"],
                        location=ActivityLocation(
                            name="Louvre Museum",
                            latitude=48.8606,
                            longitude=2.3376,
                        ),
                        duration_estimate=DurationEstimate(
                            min_minutes=90,
                            max_minutes=180,
                            basis=DurationBasis.HEURISTIC,
                        ),
                        source_refs=["https://api.open-meteo.com/v1/forecast"],
                        provenance=Provenance.GENERATED_SUGGESTION,
                        cost_status=CostStatus.ESTIMATE,
                        cost_note="€17 admission",
                        uncertainty_notes=["Reserve timed slot"],
                    )
                ],
                uncertainty_notes=["Expect queues"],
            )
        ],
    )

    dumped = original.model_dump(mode="json")
    restored = parse_itinerary_payload(dumped)

    assert restored.schema_version == original.schema_version
    assert restored.summary == original.summary
    assert len(restored.days) == len(original.days)
    assert restored.days[0].activities[0].id == original.days[0].activities[0].id
    assert restored.days[0].activities[0].title == original.days[0].activities[0].title
    assert (
        restored.days[0].activities[0].cost_status
        == original.days[0].activities[0].cost_status
    )
    assert (
        restored.days[0].activities[0].duration_estimate.basis
        == original.days[0].activities[0].duration_estimate.basis
    )


# ==============================================================================
# 4. Deterministic Generator Emits Schema v2
# ==============================================================================


def test_generator_emits_valid_schema_v2() -> None:
    """generate_itinerary returns an Itinerary conforming strictly to Schema v2."""
    fixed_today = date(2026, 12, 1)
    req = TripRequest(
        origin="London",
        destination="Paris",
        start_date=date(2026, 12, 10),
        end_date=date(2026, 12, 12),
        party_size=2,
        budget_amount=Decimal("600.00"),
        currency="EUR",
        interests=["food", "museums"],
        pace=PacePreference.BALANCED,
    )
    source = SourceInfo(
        provider="Open-Meteo",
        url="https://api.open-meteo.com/v1/forecast",
        attribution="Weather data by Open-Meteo.com",
        fetched_at=datetime(2026, 12, 1, 12, 0, 0, tzinfo=UTC),
        data_origin="live",
    )
    weather = WeatherSummary(
        location="Paris",
        days=[
            WeatherDay(
                date=date(2026, 12, 10),
                temp_min_c=14.0,
                temp_max_c=22.0,
                precipitation_probability_pct=10,
                precipitation_sum_mm=0.0,
                weather_code=1,
                condition_description="Mainly clear",
            ),
            WeatherDay(
                date=date(2026, 12, 11),
                temp_min_c=15.0,
                temp_max_c=24.0,
                precipitation_probability_pct=60,
                precipitation_sum_mm=4.5,
                weather_code=61,
                condition_description="Moderate rain",
            ),
            WeatherDay(
                date=date(2026, 12, 12),
                temp_min_c=13.0,
                temp_max_c=21.0,
                precipitation_probability_pct=20,
                precipitation_sum_mm=0.0,
                weather_code=2,
                condition_description="Partly cloudy",
            ),
        ],
        source=source,
        fetched_at=datetime(2026, 12, 1, 12, 0, 0, tzinfo=UTC),
        data_origin="live",
    )
    geocode = GeocodeResult(
        name="Paris",
        country="France",
        admin_region="Île-de-France",
        latitude=48.8534,
        longitude=2.3488,
        timezone="Europe/Paris",
        source=source,
        fetched_at=datetime(2026, 12, 1, 12, 0, 0, tzinfo=UTC),
    )

    itinerary = generate_itinerary(
        request=req,
        destination=geocode,
        weather=weather,
        today=fixed_today,
    )

    # 1. Root schema v2 verification
    assert itinerary.schema_version == 2
    assert len(itinerary.days) == 3
    assert len(itinerary.sources) >= 1
    assert itinerary.sources[0].provider == "Open-Meteo"

    # 2. Activity fields verification
    for day in itinerary.days:
        assert len(day.activities) > 0
        for idx, act in enumerate(day.activities, start=1):
            assert act.id == f"day_{day.day_number}_act_{idx}"
            assert len(act.interest_tags) > 0
            assert act.duration_estimate is not None
            assert act.duration_estimate.basis == DurationBasis.HEURISTIC
            assert act.cost_status == CostStatus.ESTIMATE
            assert act.cost_note is not None
            assert len(act.uncertainty_notes) > 0
            if act.location is not None:
                assert act.location.latitude == 48.8534
                assert act.location.longitude == 2.3488

    # Day 1 slot 0 has source_refs to weather
    assert itinerary.days[0].activities[0].source_refs == [
        "https://api.open-meteo.com/v1/forecast"
    ]


def test_generator_output_remains_strictly_deterministic() -> None:
    """Repeated executions with identical inputs produce identical v2 itineraries."""
    fixed_today = date(2026, 12, 1)
    req = TripRequest(
        origin="London",
        destination="Paris",
        start_date=date(2026, 12, 10),
        end_date=date(2026, 12, 11),
        interests=["history", "food"],
        pace=PacePreference.BALANCED,
    )

    itin_a = generate_itinerary(request=req, destination="Paris", today=fixed_today)
    itin_b = generate_itinerary(request=req, destination="Paris", today=fixed_today)

    assert itin_a.model_dump(mode="json") == itin_b.model_dump(mode="json")


# ==============================================================================
# 5. API Response Compatibility: Both v1 and v2 Payloads Produce Schema v2
# ==============================================================================


def test_trip_response_upgrades_v1_payload_automatically() -> None:
    """TripResponse automatically upgrades a stored v1 itinerary dict in memory."""
    with FIXTURE_PATH.open("r", encoding="utf-8") as f:
        v1_payload = json.load(f)

    trip_id = uuid4()
    req = TripRequest(
        origin="London",
        destination="Paris",
        start_date=date(2026, 12, 10),
        end_date=date(2026, 12, 12),
        party_size=2,
    )

    response = TripResponse.model_validate(
        {
            "id": trip_id,
            "request": req.model_dump(mode="json"),
            "itinerary": v1_payload,  # Stored v1 payload without schema_version
            "weather": None,
            "sources": [],
            "tool_activity": [],
            "warnings": [],
            "created_at": "2026-12-01T12:00:00Z",
        }
    )

    # API consumer receives upgraded schema v2
    assert response.itinerary.schema_version == 2
    assert len(response.itinerary.days) == 2
    assert len(response.itinerary.days[0].activities) == 4
    assert response.itinerary.days[0].activities[0].id == "day_1_act_1"

    # Serialized API response carries schema_version: 2
    dumped = response.model_dump(mode="json")
    assert dumped["itinerary"]["schema_version"] == 2
    assert "activities" in dumped["itinerary"]["days"][0]


def test_trip_response_accepts_v2_payload_directly() -> None:
    """TripResponse accepts and passes through native Schema v2 itineraries."""
    trip_id = uuid4()
    req = TripRequest(
        origin="London",
        destination="Paris",
        start_date=date(2026, 12, 10),
        end_date=date(2026, 12, 11),
    )
    v2_itinerary = ItineraryV2(
        schema_version=2,
        summary="Native v2 trip",
        days=[
            ItineraryDayV2(
                day_number=1,
                date=date(2026, 12, 10),
                activities=[
                    ItineraryActivityV2(
                        id="day_1_act_1",
                        title="Direct v2 Activity",
                        provenance=Provenance.GENERATED_SUGGESTION,
                    )
                ],
            )
        ],
    )

    response = TripResponse(
        id=trip_id,
        request=req,
        itinerary=v2_itinerary,
        created_at=datetime.now(UTC),
    )

    assert response.itinerary.schema_version == 2
    dumped = response.model_dump(mode="json")
    assert dumped["itinerary"]["schema_version"] == 2
    first_act_title = dumped["itinerary"]["days"][0]["activities"][0]["title"]
    assert first_act_title == "Direct v2 Activity"
