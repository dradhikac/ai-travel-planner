"""Unit tests for Phase 2 trip, provider, and itinerary Pydantic schemas."""

from collections.abc import Generator
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.errors import pydantic_validation_error_to_error_response
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

FIXED_TODAY = date(2026, 6, 1)


@pytest.fixture(autouse=True)
def setup_test_today() -> Generator[None, None, None]:
    """Inject a fixed reference today date for all schema tests."""
    TripRequest.set_test_today(FIXED_TODAY)
    yield
    TripRequest.set_test_today(None)


# ---------------------------------------------------------------------------
# 1. Valid Request Tests
# ---------------------------------------------------------------------------


def test_valid_minimal_trip_request() -> None:
    """Valid minimal request with defaults."""
    req = TripRequest(
        origin="London",
        destination="Paris",
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 15),
    )
    assert req.origin == "London"
    assert req.destination == "Paris"
    assert req.start_date == date(2026, 6, 10)
    assert req.end_date == date(2026, 6, 15)
    assert req.party_size == 1
    assert req.budget_amount is None
    assert req.currency is None
    assert req.interests == []
    assert req.pace == PacePreference.BALANCED


def test_valid_full_trip_request() -> None:
    """Valid fully-populated trip request."""
    req = TripRequest(
        origin="New York",
        destination="Tokyo",
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 14),
        party_size=4,
        budget_amount=Decimal("5000.00"),
        currency="USD",
        interests=["temples", "food", "technology"],
        pace=PacePreference.PACKED,
    )
    assert req.origin == "New York"
    assert req.destination == "Tokyo"
    assert req.party_size == 4
    assert req.budget_amount == Decimal("5000.00")
    assert req.currency == "USD"
    assert req.interests == ["temples", "food", "technology"]
    assert req.pace == PacePreference.PACKED


# ---------------------------------------------------------------------------
# 2. Missing Fields Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "missing_field",
    ["origin", "destination", "start_date", "end_date"],
)
def test_missing_required_fields(missing_field: str) -> None:
    """Missing any required field must raise a ValidationError with that field name."""
    valid_payload = {
        "origin": "London",
        "destination": "Paris",
        "start_date": "2026-06-10",
        "end_date": "2026-06-15",
    }
    valid_payload.pop(missing_field)
    with pytest.raises(ValidationError) as exc_info:
        TripRequest.model_validate(valid_payload)

    errors = exc_info.value.errors()
    locs = [err["loc"][-1] for err in errors]
    assert missing_field in locs


# ---------------------------------------------------------------------------
# 3. Blank & Whitespace-Only Strings
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("blank_val", ["", "   ", "\t\n  \r"])
def test_blank_origin_rejected(blank_val: str) -> None:
    """Blank or whitespace-only origin is rejected."""
    with pytest.raises(ValidationError) as exc_info:
        TripRequest(
            origin=blank_val,
            destination="Paris",
            start_date=date(2026, 6, 10),
            end_date=date(2026, 6, 15),
        )
    errors = exc_info.value.errors()
    assert any(err["loc"][-1] == "origin" for err in errors)


@pytest.mark.parametrize("blank_val", ["", "   ", "\t\n  \r"])
def test_blank_destination_rejected(blank_val: str) -> None:
    """Blank or whitespace-only destination is rejected."""
    with pytest.raises(ValidationError) as exc_info:
        TripRequest(
            origin="London",
            destination=blank_val,
            start_date=date(2026, 6, 10),
            end_date=date(2026, 6, 15),
        )
    errors = exc_info.value.errors()
    assert any(err["loc"][-1] == "destination" for err in errors)


def test_location_whitespace_trimming_and_collapsing() -> None:
    """Whitespace is trimmed and internal consecutive spaces collapsed."""
    req = TripRequest(
        origin="  San   Francisco  \t",
        destination="   New   \n  York  ",
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 15),
    )
    assert req.origin == "San Francisco"
    assert req.destination == "New York"


# ---------------------------------------------------------------------------
# 4. Date Validation: Reversed, Past, Same-Day, Over-long
# ---------------------------------------------------------------------------


def test_reversed_dates_rejected() -> None:
    """End date before start date must be rejected."""
    with pytest.raises(ValidationError) as exc_info:
        TripRequest(
            origin="London",
            destination="Paris",
            start_date=date(2026, 6, 15),
            end_date=date(2026, 6, 10),
        )
    msg = str(exc_info.value)
    assert "End date must be on or after start date" in msg


def test_past_start_date_rejected_via_injected_today() -> None:
    """Start date before today must be rejected."""
    # FIXED_TODAY is 2026-06-01
    with pytest.raises(ValidationError) as exc_info:
        TripRequest(
            origin="London",
            destination="Paris",
            start_date=date(2026, 5, 31),
            end_date=date(2026, 6, 5),
        )
    msg = str(exc_info.value)
    assert "Start date cannot be in the past" in msg
    locs = [err["loc"][-1] for err in exc_info.value.errors()]
    assert "start_date" in locs


def test_past_start_date_rejected_via_validation_context() -> None:
    """Start date before today in context must be rejected."""
    payload = {
        "origin": "London",
        "destination": "Paris",
        "start_date": "2026-06-14",
        "end_date": "2026-06-20",
    }
    # Context today is 2026-06-15, so start_date (2026-06-14) is in the past
    with pytest.raises(ValidationError) as exc_info:
        TripRequest.model_validate(payload, context={"today": date(2026, 6, 15)})
    assert "Start date cannot be in the past" in str(exc_info.value)


def test_same_day_trip_is_valid() -> None:
    """Same-day trip (start_date == end_date == today) is valid with duration 1 day."""
    req = TripRequest(
        origin="London",
        destination="Oxford",
        start_date=FIXED_TODAY,
        end_date=FIXED_TODAY,
    )
    assert req.start_date == FIXED_TODAY
    assert req.end_date == FIXED_TODAY


def test_trip_length_bounds() -> None:
    """Trips up to 30 days are valid; trips exceeding 30 days are rejected."""
    # 30-day trip: June 1 to June 30 = (30 - 1) + 1 = 30 days
    valid_30 = TripRequest(
        origin="London",
        destination="Paris",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 30),
    )
    assert (valid_30.end_date - valid_30.start_date).days + 1 == 30

    # 31-day trip: June 1 to July 1 = 31 days -> rejected
    with pytest.raises(ValidationError) as exc_info:
        TripRequest(
            origin="London",
            destination="Paris",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 7, 1),
        )
    msg = str(exc_info.value)
    assert "exceeds maximum limit of 30 days" in msg


# ---------------------------------------------------------------------------
# 5. Party Size Bounds: 0, 1, 20, 21
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("party_size", [0, 21, -1, 100])
def test_party_size_out_of_bounds(party_size: int) -> None:
    """Party size outside [1, 20] must fail validation."""
    with pytest.raises(ValidationError) as exc_info:
        TripRequest(
            origin="London",
            destination="Paris",
            start_date=date(2026, 6, 10),
            end_date=date(2026, 6, 15),
            party_size=party_size,
        )
    locs = [err["loc"][-1] for err in exc_info.value.errors()]
    assert "party_size" in locs


@pytest.mark.parametrize("party_size", [1, 20])
def test_party_size_boundary_valid(party_size: int) -> None:
    """Party size boundary values 1 and 20 are valid."""
    req = TripRequest(
        origin="London",
        destination="Paris",
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 15),
        party_size=party_size,
    )
    assert req.party_size == party_size


# ---------------------------------------------------------------------------
# 6. Budget & Currency Bounds and Coupling
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_budget", [Decimal("0"), Decimal("-10.00"), Decimal("10000001")]
)
def test_budget_out_of_bounds(bad_budget: Decimal) -> None:
    """Budget must be > 0 and <= 10,000,000."""
    with pytest.raises(ValidationError) as exc_info:
        TripRequest(
            origin="London",
            destination="Paris",
            start_date=date(2026, 6, 10),
            end_date=date(2026, 6, 15),
            budget_amount=bad_budget,
            currency="USD",
        )
    locs = [err["loc"][-1] for err in exc_info.value.errors()]
    assert "budget_amount" in locs


def test_budget_without_currency_rejected() -> None:
    """Budget provided without currency must be rejected."""
    with pytest.raises(ValidationError) as exc_info:
        TripRequest(
            origin="London",
            destination="Paris",
            start_date=date(2026, 6, 10),
            end_date=date(2026, 6, 15),
            budget_amount=Decimal("1500.00"),
            currency=None,
        )
    assert "Currency must be specified when budget_amount is provided" in str(
        exc_info.value
    )


def test_currency_without_budget_rejected() -> None:
    """Currency provided without budget must be rejected."""
    with pytest.raises(ValidationError) as exc_info:
        TripRequest(
            origin="London",
            destination="Paris",
            start_date=date(2026, 6, 10),
            end_date=date(2026, 6, 15),
            budget_amount=None,
            currency="USD",
        )
    assert "Currency cannot be specified without budget_amount" in str(exc_info.value)


def test_unsupported_currency_rejected() -> None:
    """Unsupported currency code must be rejected."""
    with pytest.raises(ValidationError) as exc_info:
        TripRequest(
            origin="London",
            destination="Paris",
            start_date=date(2026, 6, 10),
            end_date=date(2026, 6, 15),
            budget_amount=Decimal("1000.00"),
            currency="XYZ",
        )
    assert "Currency 'XYZ' is not supported" in str(exc_info.value)
    locs = [err["loc"][-1] for err in exc_info.value.errors()]
    assert "currency" in locs


@pytest.mark.parametrize("valid_curr", list(ALLOWED_CURRENCIES))
def test_all_allowed_currencies_accepted(valid_curr: str) -> None:
    """All currencies in allow-list are accepted and normalized to uppercase."""
    req = TripRequest(
        origin="London",
        destination="Paris",
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 15),
        budget_amount=Decimal("1000.00"),
        currency=valid_curr.lower(),
    )
    assert req.currency == valid_curr


# ---------------------------------------------------------------------------
# 7. Interests Normalization and Limits
# ---------------------------------------------------------------------------


def test_interests_normalization_and_deduplication() -> None:
    """Interests are trimmed, lowercased, deduplicated, and empty items dropped."""
    raw_interests = [
        "  MUSEUMS  ",
        "art   galleries",
        "museums",
        "  ",
        "",
        "FINE DINING",
        "A" * 45,  # Exceeds 40 chars -> dropped
    ]
    req = TripRequest(
        origin="London",
        destination="Paris",
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 15),
        interests=raw_interests,
    )
    assert req.interests == ["museums", "art galleries", "fine dining"]


def test_interests_capped_at_maximum_10() -> None:
    """More than 10 unique interests are capped at the first 10."""
    fifteen_interests = [f"interest_{i}" for i in range(15)]
    req = TripRequest(
        origin="London",
        destination="Paris",
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 15),
        interests=fifteen_interests,
    )
    assert len(req.interests) == 10
    assert req.interests == [f"interest_{i}" for i in range(10)]


# ---------------------------------------------------------------------------
# 8. Pace Default and Enum Values
# ---------------------------------------------------------------------------


def test_pace_defaults_to_balanced() -> None:
    """When pace is not specified, it defaults to BALANCED."""
    req = TripRequest(
        origin="London",
        destination="Paris",
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 15),
    )
    assert req.pace == PacePreference.BALANCED


@pytest.mark.parametrize(
    ("pace_input", "expected_enum"),
    [
        ("relaxed", PacePreference.RELAXED),
        ("balanced", PacePreference.BALANCED),
        ("packed", PacePreference.PACKED),
    ],
)
def test_pace_explicit_values(pace_input: str, expected_enum: PacePreference) -> None:
    """Explicit pace preferences are properly validated."""
    req = TripRequest(
        origin="London",
        destination="Paris",
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 15),
        pace=pace_input,  # type: ignore[arg-type]
    )
    assert req.pace == expected_enum


def test_invalid_pace_rejected() -> None:
    """Invalid pace preference raises ValidationError."""
    with pytest.raises(ValidationError):
        TripRequest(
            origin="London",
            destination="Paris",
            start_date=date(2026, 6, 10),
            end_date=date(2026, 6, 15),
            pace="super_fast",  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# 9. Origin Equals Destination (Case-Insensitive)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("origin", "dest"),
    [
        ("Paris", "Paris"),
        ("Paris", "paris"),
        ("  New   York  ", "NEW YORK"),
        ("London", "london"),
    ],
)
def test_origin_equals_destination_rejected(origin: str, dest: str) -> None:
    """Identical origin and destination must be rejected case-insensitively."""
    with pytest.raises(ValidationError) as exc_info:
        TripRequest(
            origin=origin,
            destination=dest,
            start_date=date(2026, 6, 10),
            end_date=date(2026, 6, 15),
        )
    assert "Origin and destination cannot be identical" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 10. Round-Trip Serialization of Every Model
# ---------------------------------------------------------------------------


def test_round_trip_trip_request() -> None:
    """TripRequest round-trips through JSON without data loss."""
    original = TripRequest(
        origin="London",
        destination="Paris",
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 15),
        party_size=2,
        budget_amount=Decimal("1234.56"),
        currency="EUR",
        interests=["museums", "architecture"],
        pace=PacePreference.RELAXED,
    )
    dumped = original.model_dump(mode="json")
    assert dumped["start_date"] == "2026-06-10"
    assert dumped["end_date"] == "2026-06-15"
    assert dumped["budget_amount"] == "1234.56"
    assert isinstance(dumped["budget_amount"], str)

    restored = TripRequest.model_validate(dumped)
    assert restored == original
    assert restored.budget_amount == Decimal("1234.56")


def test_round_trip_source_info() -> None:
    """SourceInfo round-trips with UTC timezone normalization."""
    now_utc = datetime(2026, 6, 10, 12, 0, 0, tzinfo=UTC)
    original = SourceInfo(
        provider="Open-Meteo",
        url="https://open-meteo.com/",
        attribution="Weather data by Open-Meteo.com",
        fetched_at=now_utc,
        data_origin="live",
    )
    dumped = original.model_dump(mode="json")
    assert dumped["fetched_at"] == "2026-06-10T12:00:00Z"

    restored = SourceInfo.model_validate(dumped)
    assert restored == original
    assert restored.fetched_at.tzinfo == UTC


def test_round_trip_geocode_result() -> None:
    """GeocodeResult round-trips correctly."""
    now_utc = datetime(2026, 6, 10, 12, 0, 0, tzinfo=UTC)
    source = SourceInfo(
        provider="Open-Meteo",
        url="https://open-meteo.com/",
        attribution="Weather data by Open-Meteo.com",
        fetched_at=now_utc,
        data_origin="mock",
    )
    original = GeocodeResult(
        name="Berlin",
        country="Germany",
        admin_region="Berlin",
        latitude=52.52,
        longitude=13.41,
        timezone="Europe/Berlin",
        source=source,
        fetched_at=now_utc,
    )
    dumped = original.model_dump(mode="json")
    restored = GeocodeResult.model_validate(dumped)
    assert restored == original


def test_round_trip_weather_summary_and_day() -> None:
    """WeatherSummary and WeatherDay round-trip correctly."""
    now_utc = datetime(2026, 6, 10, 12, 0, 0, tzinfo=UTC)
    source = SourceInfo(
        provider="Open-Meteo",
        url="https://open-meteo.com/",
        attribution="Weather data by Open-Meteo.com",
        fetched_at=now_utc,
        data_origin="live",
    )
    day = WeatherDay(
        date=date(2026, 6, 10),
        temp_min_c=12.5,
        temp_max_c=22.0,
        precipitation_probability_pct=20,
        precipitation_sum_mm=0.0,
        weather_code=1,
        condition_description="Mainly clear",
    )
    summary = WeatherSummary(
        location="Paris",
        days=[day],
        source=source,
        fetched_at=now_utc,
        data_origin="live",
        horizon_note=None,
    )
    dumped = summary.model_dump(mode="json")
    restored = WeatherSummary.model_validate(dumped)
    assert restored == summary


def test_round_trip_itinerary_and_items() -> None:
    """Itinerary, ItineraryDay, and ItineraryItem round-trip correctly."""
    item = ItineraryItem(
        title="Visit Louvre Museum",
        time_of_day=TimeOfDay.MORNING,
        description="Explore the classical art galleries.",
        provenance=Provenance.GENERATED_SUGGESTION,
        source_ref="https://louvre.fr",
        note="Pre-booking advised",
        cost_estimate="~€17 per person",
    )
    day = ItineraryDay(day_number=1, date=date(2026, 6, 10), items=[item])
    itinerary = Itinerary(days=[day], summary="A cultural week in Paris.")

    dumped = itinerary.model_dump(mode="json")
    restored = Itinerary.model_validate(dumped)
    assert restored == itinerary


def test_round_trip_trip_response() -> None:
    """Complete TripResponse round-trips correctly."""
    trip_id = uuid4()
    req = TripRequest(
        origin="London",
        destination="Paris",
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 12),
    )
    item = ItineraryItem(
        title="Walk along Seine",
        time_of_day=TimeOfDay.EVENING,
        description="Relaxing evening stroll.",
        provenance=Provenance.GENERATED_SUGGESTION,
    )
    itinerary = Itinerary(
        days=[ItineraryDay(day_number=1, date=date(2026, 6, 10), items=[item])],
        summary="Short getaway.",
    )
    now_utc = datetime(2026, 6, 10, 10, 0, 0, tzinfo=UTC)
    response = TripResponse(
        id=trip_id,
        request=req,
        itinerary=itinerary,
        weather=None,
        sources=[],
        warnings=["Test warning"],
        created_at=now_utc,
    )
    dumped = response.model_dump(mode="json")
    assert dumped["id"] == str(trip_id)
    assert dumped["created_at"] == "2026-06-10T10:00:00Z"

    restored = TripResponse.model_validate(dumped)
    assert restored == response


# ---------------------------------------------------------------------------
# 11. Itinerary Rejects Items Without Provenance
# ---------------------------------------------------------------------------


def test_itinerary_item_rejects_missing_or_none_provenance() -> None:
    """ItineraryItem rejects None provenance."""
    with pytest.raises(ValidationError):
        ItineraryItem(
            title="Activity",
            time_of_day=TimeOfDay.MORNING,
            description="Details",
            provenance=None,  # type: ignore[arg-type]
        )


def test_itinerary_item_rejects_invalid_provenance_string() -> None:
    """ItineraryItem rejects invalid provenance enum string."""
    with pytest.raises(ValidationError):
        ItineraryItem(
            title="Activity",
            time_of_day=TimeOfDay.MORNING,
            description="Details",
            provenance="hallucinated",  # type: ignore[arg-type]
        )


def test_itinerary_rejects_item_without_provenance() -> None:
    """Itinerary and ItineraryDay reject items missing provenance."""
    invalid_item_dict = {
        "title": "Activity",
        "time_of_day": "morning",
        "description": "Details",
        "provenance": None,
    }
    with pytest.raises(ValidationError):
        ItineraryDay.model_validate(
            {"day_number": 1, "date": "2026-06-10", "items": [invalid_item_dict]}
        )

    with pytest.raises(ValidationError):
        Itinerary.model_validate(
            {
                "days": [
                    {
                        "day_number": 1,
                        "date": "2026-06-10",
                        "items": [invalid_item_dict],
                    }
                ],
                "summary": "Summary",
            }
        )


# ---------------------------------------------------------------------------
# 12. 422 Error Shape Mapping
# ---------------------------------------------------------------------------


def test_validation_errors_map_onto_422_error_shape_with_field_names() -> None:
    """Validation errors map to uniform 422 shape with field names."""
    with pytest.raises(ValidationError) as exc_info:
        TripRequest(
            origin="",
            destination="",
            start_date=date(2026, 5, 1),  # In past
            end_date=date(2026, 4, 1),  # Reversed
            party_size=0,  # Out of bounds
            budget_amount=Decimal("1000"),  # Missing currency
        )

    error_resp = pydantic_validation_error_to_error_response(exc_info.value)
    data = error_resp.model_dump()
    assert "error" in data
    assert data["error"]["code"] == "validation_error"
    assert data["error"]["message"] == "Request validation failed"
    details = data["error"]["details"]
    assert isinstance(details, list)
    assert len(details) > 0

    loc_fields = [d["loc"][-1] for d in details if d["loc"]]
    assert "origin" in loc_fields
    assert "destination" in loc_fields
    assert "party_size" in loc_fields
    assert "start_date" in loc_fields
