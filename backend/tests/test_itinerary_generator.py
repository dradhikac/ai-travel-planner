"""Unit tests for deterministic itinerary generator service."""

import re
from collections.abc import Generator
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.schemas.provider import (
    GeocodeResult,
    Provenance,
    SourceInfo,
    WeatherDay,
    WeatherSummary,
)
from app.schemas.trip import (
    PacePreference,
    TripRequest,
)
from app.services.itinerary import (
    PACE_ITEM_COUNTS,
    generate_itinerary,
)

FIXED_TODAY = date(2026, 6, 1)

# List of strictly banned words implying an active or confirmed booking transaction
BANNED_BOOKING_PHRASES = [
    "booked",
    "booking",
    "reserved",
    "reservation",
    "confirmed",
    "confirmation",
    "paid",
    "payment",
    "ticketed",
    "purchased",
]


@pytest.fixture(autouse=True)
def set_reference_today() -> Generator[None, None, None]:
    """Inject reference date for TripRequest validation."""
    TripRequest.set_test_today(FIXED_TODAY)
    yield
    TripRequest.set_test_today(None)


def create_sample_weather(
    dates: list[date],
    rain_pct: int = 10,
    data_origin: str = "live",
    horizon_note: str | None = None,
) -> WeatherSummary:
    """Helper to build normalized WeatherSummary test fixture."""
    source = SourceInfo(
        provider="Open-Meteo",
        url="https://open-meteo.com/",
        attribution="Weather data by Open-Meteo.com (CC-BY 4.0)",
        fetched_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
        data_origin=data_origin,  # type: ignore[arg-type]
    )
    days = [
        WeatherDay(
            date=d,
            temp_min_c=14.0,
            temp_max_c=22.5,
            precipitation_probability_pct=rain_pct,
            precipitation_sum_mm=0.0 if rain_pct < 40 else 8.5,
            weather_code=1 if rain_pct < 40 else 61,
            condition_description="Mainly clear" if rain_pct < 40 else "Slight rain",
        )
        for d in dates
    ]
    return WeatherSummary(
        location="Paris, France",
        days=days,
        units={"temperature": "celsius", "precipitation": "mm"},
        source=source,
        fetched_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
        data_origin=data_origin,  # type: ignore[arg-type]
        horizon_note=horizon_note,
    )


def create_sample_geocode() -> GeocodeResult:
    """Helper to build GeocodeResult test fixture."""
    source = SourceInfo(
        provider="Open-Meteo",
        url="https://open-meteo.com/",
        attribution="Location data by Open-Meteo (CC-BY 4.0)",
        fetched_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
        data_origin="live",
    )
    return GeocodeResult(
        name="Paris",
        country="France",
        admin_region="Île-de-France",
        latitude=48.8534,
        longitude=2.3488,
        timezone="Europe/Paris",
        source=source,
        fetched_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
    )


# ---------------------------------------------------------------------------
# 1. Pace Item Counts
# ---------------------------------------------------------------------------


def test_pace_item_counts() -> None:
    """Test that generated daily item counts strictly follow pace constants."""
    for pace, expected_count in PACE_ITEM_COUNTS.items():
        request = TripRequest(
            origin="London",
            destination="Paris",
            start_date=date(2026, 6, 10),
            end_date=date(2026, 6, 12),
            pace=pace,
        )
        itinerary = generate_itinerary(
            request=request,
            destination="Paris",
            today=FIXED_TODAY,
        )

        assert len(itinerary.days) == 3
        for day in itinerary.days:
            assert len(day.items) == expected_count, (
                f"Pace {pace} expected {expected_count} items, got {len(day.items)}"
            )


# ---------------------------------------------------------------------------
# 2. Every Item Has Valid Provenance
# ---------------------------------------------------------------------------


def test_every_item_has_provenance() -> None:
    """Test that all items across all days carry explicit, valid provenance."""
    request = TripRequest(
        origin="London",
        destination="Paris",
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 12),
        pace=PacePreference.BALANCED,
    )
    trip_dates = [date(2026, 6, 10), date(2026, 6, 11), date(2026, 6, 12)]
    weather = create_sample_weather(trip_dates)

    itinerary = generate_itinerary(
        request=request,
        destination="Paris",
        weather=weather,
        today=FIXED_TODAY,
    )

    for day in itinerary.days:
        for item in day.items:
            assert isinstance(item.provenance, Provenance)
            assert item.provenance in {
                Provenance.RETRIEVED,
                Provenance.GENERATED_SUGGESTION,
                Provenance.ESTIMATE,
                Provenance.UNKNOWN,
            }


# ---------------------------------------------------------------------------
# 3. Weather Present vs Absent vs Partial
# ---------------------------------------------------------------------------


def test_weather_present_integrates_normalized_metrics() -> None:
    """Test normalized weather metrics are embedded into day notes and source refs."""
    request = TripRequest(
        origin="London",
        destination="Paris",
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 11),
    )
    trip_dates = [date(2026, 6, 10), date(2026, 6, 11)]
    weather = create_sample_weather(trip_dates, rain_pct=15)

    itinerary = generate_itinerary(
        request=request,
        destination="Paris",
        weather=weather,
        today=FIXED_TODAY,
    )

    assert len(itinerary.days) == 2
    for day in itinerary.days:
        first_item = day.items[0]
        assert first_item.note is not None
        assert "14.0°C to 22.5°C" in first_item.note
        assert "rain chance 15%" in first_item.note
        assert first_item.source_ref == "https://open-meteo.com/"


def test_weather_absent_marked_unknown_with_warning() -> None:
    """Test absent weather marks conditions unknown and adds a warning."""
    request = TripRequest(
        origin="London",
        destination="Paris",
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 11),
    )
    itinerary = generate_itinerary(
        request=request,
        destination="Paris",
        weather=None,
        today=FIXED_TODAY,
    )

    # Note states weather is unknown
    first_item = itinerary.days[0].items[0]
    assert first_item.note is not None
    assert "unknown" in first_item.note.lower()

    # Warning list includes weather unavailable notice
    assert any(
        "weather" in w.lower() and "unknown" in w.lower() for w in itinerary.warnings
    )


def test_weather_partial_horizon() -> None:
    """Test partial weather coverage embeds forecast for covered days."""
    request = TripRequest(
        origin="London",
        destination="Paris",
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 13),  # 4 days
    )
    # Weather only covers first 2 days
    covered_dates = [date(2026, 6, 10), date(2026, 6, 11)]
    weather = create_sample_weather(
        covered_dates,
        horizon_note="Forecast unavailable beyond 16-day limit",
    )

    itinerary = generate_itinerary(
        request=request,
        destination="Paris",
        weather=weather,
        today=FIXED_TODAY,
    )

    # Day 1 and 2 have weather data
    assert "14.0°C" in (itinerary.days[0].items[0].note or "")
    assert "14.0°C" in (itinerary.days[1].items[0].note or "")

    # Day 3 and 4 have unknown weather
    assert "unknown" in (itinerary.days[2].items[0].note or "").lower()
    assert "unknown" in (itinerary.days[3].items[0].note or "").lower()

    # Warnings record partial missing days and horizon note
    assert any("missing for 2 of 4" in w for w in itinerary.warnings)
    assert any("horizon" in w.lower() for w in itinerary.warnings)


# ---------------------------------------------------------------------------
# 4. Rain-Driven Ordering
# ---------------------------------------------------------------------------


def test_rain_driven_ordering() -> None:
    """Test high rain probability prioritizes indoor activities over outdoor ones."""
    request = TripRequest(
        origin="London",
        destination="Paris",
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 11),
        interests=["nature", "museums"],
        pace=PacePreference.BALANCED,
    )

    # Day 1: Dry (10% rain). Day 2: Heavy rain (80% rain)
    d1 = date(2026, 6, 10)
    d2 = date(2026, 6, 11)

    source = SourceInfo(
        provider="Open-Meteo",
        url="https://open-meteo.com/",
        attribution="Weather data by Open-Meteo.com",
        fetched_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
        data_origin="live",
    )
    weather = WeatherSummary(
        location="Paris",
        days=[
            WeatherDay(
                date=d1,
                temp_min_c=15.0,
                temp_max_c=22.0,
                precipitation_probability_pct=10,
                precipitation_sum_mm=0.0,
                weather_code=0,
                condition_description="Clear",
            ),
            WeatherDay(
                date=d2,
                temp_min_c=12.0,
                temp_max_c=16.0,
                precipitation_probability_pct=80,
                precipitation_sum_mm=12.0,
                weather_code=63,
                condition_description="Moderate rain",
            ),
        ],
        units={"temperature": "celsius", "precipitation": "mm"},
        source=source,
        fetched_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
        data_origin="live",
    )

    itinerary = generate_itinerary(
        request=request,
        destination="Paris",
        weather=weather,
        today=FIXED_TODAY,
    )

    day1_items = itinerary.days[0].items
    day2_items = itinerary.days[1].items

    # On rainy day (Day 2), indoor activity (museum/gallery) must be prioritized first
    assert (
        "museum" in day2_items[0].title.lower()
        or "gallery" in day2_items[0].title.lower()
    )
    assert "indoor activities prioritized" in (day2_items[0].note or "").lower()

    # On dry day (Day 1), outdoor parklands or gardens comes first
    assert (
        "gardens" in day1_items[0].title.lower()
        or "park" in day1_items[0].title.lower()
    )


# ---------------------------------------------------------------------------
# 5. Budget Allocation Estimate vs Unknown
# ---------------------------------------------------------------------------


def test_budget_estimate_vs_unknown() -> None:
    """Test budget presence produces per-day estimate; absent marks unknown."""
    # Case A: Budget present
    req_budget = TripRequest(
        origin="London",
        destination="Paris",
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 14),  # 5 days
        party_size=2,
        budget_amount=Decimal("1500.00"),
        currency="EUR",
    )
    itin_budget = generate_itinerary(req_budget, "Paris", today=FIXED_TODAY)
    item_cost = itin_budget.days[0].items[0].cost_estimate
    assert item_cost is not None
    assert "300.00 EUR/day" in item_cost
    assert "150.00 EUR per person/day" in item_cost
    assert "estimate, not a price quote" in item_cost
    assert "Flights and accommodation are unquoted" in item_cost

    # Case B: Budget absent
    req_no_budget = TripRequest(
        origin="London",
        destination="Paris",
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 14),
    )
    itin_no_budget = generate_itinerary(req_no_budget, "Paris", today=FIXED_TODAY)
    assert itin_no_budget.days[0].items[0].cost_estimate is not None
    assert "unknown" in itin_no_budget.days[0].items[0].cost_estimate.lower()


# ---------------------------------------------------------------------------
# 6. Warnings: Low Budget, Mock Data, Packed Long Trip
# ---------------------------------------------------------------------------


def test_low_budget_warning() -> None:
    """Test budget below LOW_BUDGET_THRESHOLD_PER_DAY triggers a planning warning."""
    # 5 days, 2 persons, budget 100 EUR -> 10 EUR/person/day (< 50 threshold)
    request = TripRequest(
        origin="London",
        destination="Paris",
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 14),
        party_size=2,
        budget_amount=Decimal("100.00"),
        currency="EUR",
    )
    itinerary = generate_itinerary(request, "Paris", today=FIXED_TODAY)
    assert any("low budget warning" in w.lower() for w in itinerary.warnings)
    assert any(
        "below the standard planning baseline" in w.lower() for w in itinerary.warnings
    )


def test_mock_data_warning() -> None:
    """Test weather data with data_origin='mock' triggers a mock data warning."""
    request = TripRequest(
        origin="London",
        destination="Paris",
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 11),
    )
    mock_weather = create_sample_weather(
        dates=[date(2026, 6, 10), date(2026, 6, 11)],
        data_origin="mock",
    )
    itinerary = generate_itinerary(
        request, "Paris", weather=mock_weather, today=FIXED_TODAY
    )
    assert any("mock weather data in use" in w.lower() for w in itinerary.warnings)


def test_packed_long_trip_warning() -> None:
    """Test packed pace over 7 days triggers traveler fatigue warning."""
    # 10 days packed pace
    request = TripRequest(
        origin="London",
        destination="Paris",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 10),
        pace=PacePreference.PACKED,
    )
    itinerary = generate_itinerary(request, "Paris", today=FIXED_TODAY)
    assert any(
        "pace warning" in w.lower() and "fatigue" in w.lower()
        for w in itinerary.warnings
    )

    # 5 days packed pace should not trigger warning
    request_short = TripRequest(
        origin="London",
        destination="Paris",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 5),
        pace=PacePreference.PACKED,
    )
    itin_short = generate_itinerary(request_short, "Paris", today=FIXED_TODAY)
    assert not any("fatigue" in w.lower() for w in itin_short.warnings)


# ---------------------------------------------------------------------------
# 7. Strict Banned Phrases Scan (No Booking Terminology)
# ---------------------------------------------------------------------------


def test_banned_booking_phrases_scan() -> None:
    """Verify that no booking, reservation, or payment language exists in text."""
    request = TripRequest(
        origin="London",
        destination="Paris",
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 15),
        budget_amount=Decimal("1200.00"),
        currency="EUR",
        interests=["food", "museums", "nature", "history", "shopping", "nightlife"],
        pace=PacePreference.BALANCED,
    )
    trip_dates = [
        date(2026, 6, 10),
        date(2026, 6, 11),
        date(2026, 6, 12),
        date(2026, 6, 13),
        date(2026, 6, 14),
        date(2026, 6, 15),
    ]
    weather = create_sample_weather(trip_dates)
    itinerary = generate_itinerary(request, "Paris", weather=weather, today=FIXED_TODAY)

    # Collect all strings produced across all fields
    collected_strings: list[str] = [itinerary.summary]
    collected_strings.extend(itinerary.warnings)

    for day in itinerary.days:
        for item in day.items:
            collected_strings.append(item.title)
            collected_strings.append(item.description)
            if item.note:
                collected_strings.append(item.note)
            if item.cost_estimate:
                collected_strings.append(item.cost_estimate)

    # Check for banned booking terms using word boundaries
    for text in collected_strings:
        lower_text = text.lower()
        for banned in BANNED_BOOKING_PHRASES:
            match = re.search(rf"\b{re.escape(banned)}\b", lower_text)
            assert match is None, (
                f"Banned booking phrase '{banned}' detected in generated text: '{text}'"
            )


# ---------------------------------------------------------------------------
# 8. Determinism (Two Identical Runs Equal)
# ---------------------------------------------------------------------------


def test_determinism_identical_runs_produce_identical_output() -> None:
    """Verify generator is purely deterministic without time drift."""
    request = TripRequest(
        origin="London",
        destination="Paris",
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 13),
        interests=["food", "history"],
        pace=PacePreference.BALANCED,
    )
    trip_dates = [
        date(2026, 6, 10),
        date(2026, 6, 11),
        date(2026, 6, 12),
        date(2026, 6, 13),
    ]
    weather = create_sample_weather(trip_dates)

    itin1 = generate_itinerary(request, "Paris", weather=weather, today=FIXED_TODAY)
    itin2 = generate_itinerary(request, "Paris", weather=weather, today=FIXED_TODAY)

    assert itin1 == itin2
    assert itin1.model_dump() == itin2.model_dump()


# ---------------------------------------------------------------------------
# 9. Single-Day and 30-Day Trips
# ---------------------------------------------------------------------------


def test_single_day_trip() -> None:
    """Test single-day trip boundary produces exactly 1 day."""
    request = TripRequest(
        origin="London",
        destination="Paris",
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 10),
        pace=PacePreference.RELAXED,
    )
    itinerary = generate_itinerary(request, "Paris", today=FIXED_TODAY)
    assert len(itinerary.days) == 1
    assert itinerary.days[0].day_number == 1
    assert itinerary.days[0].date == date(2026, 6, 10)
    assert len(itinerary.days[0].items) == 2


def test_30_day_trip() -> None:
    """Test maximum allowed 30-day trip boundary produces exactly 30 days."""
    request = TripRequest(
        origin="London",
        destination="Paris",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 30),
        pace=PacePreference.BALANCED,
    )
    itinerary = generate_itinerary(request, "Paris", today=FIXED_TODAY)
    assert len(itinerary.days) == 30
    assert itinerary.days[0].day_number == 1
    assert itinerary.days[-1].day_number == 30
    assert itinerary.days[-1].date == date(2026, 6, 30)


# ---------------------------------------------------------------------------
# 10. GeocodeResult vs String Destination & Weather As Item Mode
# ---------------------------------------------------------------------------


def test_destination_geocode_result_resolution() -> None:
    """Test GeocodeResult destination object is resolved into structured label."""
    request = TripRequest(
        origin="London",
        destination="Paris",
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 11),
    )
    geocode = create_sample_geocode()
    itinerary = generate_itinerary(request, destination=geocode, today=FIXED_TODAY)

    assert "Paris, Île-de-France, France" in itinerary.summary
    assert "Paris, Île-de-France, France" in itinerary.days[0].items[0].title


def test_weather_as_item_mode() -> None:
    """Test weather_as_item=True prepends a dedicated retrieved weather item."""
    request = TripRequest(
        origin="London",
        destination="Paris",
        start_date=date(2026, 6, 10),
        end_date=date(2026, 6, 11),
        pace=PacePreference.RELAXED,
    )
    trip_dates = [date(2026, 6, 10), date(2026, 6, 11)]
    weather = create_sample_weather(trip_dates)

    itinerary = generate_itinerary(
        request,
        destination="Paris",
        weather=weather,
        today=FIXED_TODAY,
        weather_as_item=True,
    )

    day1 = itinerary.days[0]
    # Weather item prepended + 2 activity items = 3 items
    assert len(day1.items) == 3
    weather_item = day1.items[0]
    assert weather_item.title.startswith("Weather Briefing")
    assert weather_item.provenance == Provenance.RETRIEVED
    assert weather_item.source_ref == "https://open-meteo.com/"
