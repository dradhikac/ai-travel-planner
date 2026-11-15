"""Unit tests for Phase 4 deterministic validation rules catalog and registry.

Verifies:
- One passing and one failing test per rule in VALIDATION_REGISTRY:
  - DATE_RANGE_MISMATCH
  - DUPLICATE_ACTIVITY (warning for 1-2, critical for >=3)
  - MAX_DAILY_ACTIVITIES (relaxed 3, balanced 4, packed 5)
  - MISSING_REQUIRED_INTEREST (exact tag matching, unsupported interest records note)
  - MISSING_SOURCE_METADATA
  - MISSING_PROVENANCE
  - BOOKING_LANGUAGE_DETECTED
  - WEATHER_WITHOUT_TOOL_SUCCESS
  - INVALID_COST_STATUS
  - BUDGET_FLOOR_VIOLATION
- Boundary conditions:
  - Daily activity cap boundary (exact cap vs cap + 1)
  - Single-day trip (1 day)
  - Multi-week trip (30 days)
- Duplicates normalization across whitespace and case variations
- Exact interest tag match behavior (synonyms are NOT guessed, documented)
- Multiple issues deterministic sort order
- Message sanitization and truncation
- has_critical behavior
- TripState input handling
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.agent.state import create_fresh_trip_state
from app.agent.tools.contracts import ToolResult, ToolStatus
from app.agent.validation import (
    ValidationCode,
    ValidationIssue,
    ValidationSeverity,
    has_critical,
    sanitize_message_text,
    validate_itinerary,
)
from app.schemas.itinerary_v2 import (
    ActivityLocation,
    CostStatus,
    DurationBasis,
    DurationEstimate,
    ItineraryActivityV2,
    ItineraryDayV2,
    ItineraryV2,
)
from app.schemas.provider import Provenance, SourceInfo
from app.schemas.trip import PacePreference, TripRequest

FIXED_TODAY = date(2026, 12, 1)


@pytest.fixture(autouse=True)
def setup_test_date() -> None:
    """Set reference test date for TripRequest models."""
    TripRequest.set_test_today(FIXED_TODAY)


@pytest.fixture
def sample_source() -> SourceInfo:
    return SourceInfo(
        provider="Open-Meteo",
        url="https://open-meteo.com/",
        attribution="Weather data by Open-Meteo.com",
        fetched_at=datetime(2026, 12, 1, 10, 0, 0, tzinfo=UTC),
        data_origin="mock",
    )


def make_valid_activity(
    act_id: str = "day_1_act_1",
    title: str = "Historic City Walking Tour",
    interest_tags: list[str] | None = None,
    location_name: str = "Munich Central Plaza",
    provenance: Provenance = Provenance.GENERATED_SUGGESTION,
    cost_status: CostStatus = CostStatus.UNKNOWN,
    source_refs: list[str] | None = None,
    uncertainty_notes: list[str] | None = None,
) -> ItineraryActivityV2:
    """Helper to instantiate a valid schema v2 activity."""
    return ItineraryActivityV2(
        id=act_id,
        title=title,
        description=f"Explore sights during {title}.",
        time_of_day="morning",
        interest_tags=interest_tags or ["culture", "history"],
        location=ActivityLocation(
            name=location_name, latitude=48.1351, longitude=11.5820
        ),
        duration_estimate=DurationEstimate(
            min_minutes=60, max_minutes=120, basis=DurationBasis.HEURISTIC
        ),
        source_refs=source_refs or [],
        provenance=provenance,
        cost_status=cost_status,
        cost_note=None,
        uncertainty_notes=uncertainty_notes or [],
    )


def make_valid_itinerary(
    start_date: date = date(2026, 12, 10),
    num_days: int = 3,
    activities_per_day: int = 2,
    sources: list[SourceInfo] | None = None,
) -> ItineraryV2:
    """Helper to generate a cleanly structured N-day itinerary."""
    days: list[ItineraryDayV2] = []
    for day_idx in range(1, num_days + 1):
        day_date = start_date + timedelta(days=day_idx - 1)
        acts = [
            make_valid_activity(
                act_id=f"day_{day_idx}_act_{a_idx}",
                title=f"Day {day_idx} Activity {a_idx} in Munich",
                interest_tags=["culture" if a_idx == 1 else "food"],
                location_name=f"Munich Point {day_idx}_{a_idx}",
            )
            for a_idx in range(1, activities_per_day + 1)
        ]
        days.append(
            ItineraryDayV2(
                day_number=day_idx,
                date=day_date,
                activities=acts,
                uncertainty_notes=[],
            )
        )

    return ItineraryV2(
        schema_version=2,
        summary="A delightful 3-day exploration of Munich.",
        sources=sources or [],
        warnings=[],
        days=days,
    )


def make_sample_request(
    start_date: date = date(2026, 12, 10),
    end_date: date = date(2026, 12, 12),
    interests: list[str] | None = None,
    pace: PacePreference = PacePreference.BALANCED,
    budget_amount: str = "600.00",
    currency: str = "EUR",
) -> TripRequest:
    return TripRequest(
        origin="Berlin",
        destination="Munich",
        start_date=start_date,
        end_date=end_date,
        party_size=2,
        budget_amount=Decimal(budget_amount),
        currency=currency,
        interests=interests or ["culture", "food"],
        pace=pace,
    )


# ==============================================================================
# 1. Rule 1: DATE_RANGE_MISMATCH Tests
# ==============================================================================


def test_date_range_mismatch_passing() -> None:
    """Conforming itinerary dates and day_numbers pass without DATE_RANGE_MISMATCH."""
    itinerary = make_valid_itinerary(start_date=date(2026, 12, 10), num_days=3)
    request = make_sample_request(
        start_date=date(2026, 12, 10), end_date=date(2026, 12, 12)
    )

    issues = validate_itinerary(itinerary, request=request)
    mismatch_issues = [
        i for i in issues if i.code == ValidationCode.DATE_RANGE_MISMATCH
    ]
    assert len(mismatch_issues) == 0


def test_date_range_mismatch_failing_missing_day() -> None:
    """Trip requesting 3 days but itinerary having only 2 triggers
    critical DATE_RANGE_MISMATCH.
    """
    itinerary = make_valid_itinerary(start_date=date(2026, 12, 10), num_days=2)
    request = make_sample_request(
        start_date=date(2026, 12, 10), end_date=date(2026, 12, 12)
    )  # 3 days

    issues = validate_itinerary(itinerary, request=request)
    mismatch_issues = [
        i for i in issues if i.code == ValidationCode.DATE_RANGE_MISMATCH
    ]
    assert len(mismatch_issues) >= 1
    assert any(i.severity == ValidationSeverity.CRITICAL for i in mismatch_issues)
    assert has_critical(issues) is True


def test_date_range_mismatch_failing_non_consecutive_day_number() -> None:
    """Itinerary days with non-consecutive day numbers (e.g. 1 then 3)
    trigger DATE_RANGE_MISMATCH.
    """
    itinerary = make_valid_itinerary(start_date=date(2026, 12, 10), num_days=2)
    itinerary.days[1].day_number = 3  # Gap: day 2 missing

    issues = validate_itinerary(itinerary)
    mismatch_issues = [
        i for i in issues if i.code == ValidationCode.DATE_RANGE_MISMATCH
    ]
    assert len(mismatch_issues) >= 1
    assert mismatch_issues[0].severity == ValidationSeverity.CRITICAL


# ==============================================================================
# 2. Rule 2: DUPLICATE_ACTIVITY Tests
# ==============================================================================


def test_duplicate_activity_passing_unique_items() -> None:
    """Unique activities and exempt repeat categories pass without
    DUPLICATE_ACTIVITY.
    """
    itinerary = make_valid_itinerary(num_days=2)
    # Add breakfast on both days (exempt category)
    itinerary.days[0].activities.append(
        make_valid_activity(
            act_id="day_1_b",
            title="Hotel Breakfast",
            interest_tags=["food"],
            location_name="Munich",
        )
    )
    itinerary.days[1].activities.append(
        make_valid_activity(
            act_id="day_2_b",
            title="Hotel Breakfast",
            interest_tags=["food"],
            location_name="Munich",
        )
    )

    issues = validate_itinerary(itinerary)
    dup_issues = [i for i in issues if i.code == ValidationCode.DUPLICATE_ACTIVITY]
    assert len(dup_issues) == 0


def test_duplicate_activity_failing_warning_for_1_or_2_duplicates() -> None:
    """1 or 2 duplicate non-exempt activities trigger WARNING severity."""
    itinerary = make_valid_itinerary(num_days=2)
    # Schedule identical museum visit on day 1 and day 2
    dup = make_valid_activity(
        act_id="dup_1",
        title="Alte Pinakothek Museum",
        interest_tags=["museums"],
        location_name="Munich Art District",
    )
    dup_copy = make_valid_activity(
        act_id="dup_2",
        title="Alte Pinakothek Museum",
        interest_tags=["museums"],
        location_name="Munich Art District",
    )
    itinerary.days[0].activities.append(dup)
    itinerary.days[1].activities.append(dup_copy)

    issues = validate_itinerary(itinerary)
    dup_issues = [i for i in issues if i.code == ValidationCode.DUPLICATE_ACTIVITY]
    assert len(dup_issues) == 1
    assert dup_issues[0].severity == ValidationSeverity.WARNING
    assert dup_issues[0].day_number == 2
    assert dup_issues[0].activity_id == "dup_2"


def test_duplicate_activity_failing_critical_for_3_or_more_duplicates() -> None:
    """3 or more duplicate non-exempt activities trigger CRITICAL severity."""
    itinerary = make_valid_itinerary(num_days=4)
    # Add same attraction on 4 consecutive days (1 original + 3 duplicates)
    for day_idx in range(4):
        itinerary.days[day_idx].activities.append(
            make_valid_activity(
                act_id=f"dup_{day_idx + 1}",
                title="Bavarian Castle Tour",
                interest_tags=["history"],
                location_name="Füssen",
            )
        )

    issues = validate_itinerary(itinerary)
    dup_issues = [i for i in issues if i.code == ValidationCode.DUPLICATE_ACTIVITY]
    assert len(dup_issues) == 3
    # All 3 duplicates should be elevated to CRITICAL
    for issue in dup_issues:
        assert issue.severity == ValidationSeverity.CRITICAL
    assert has_critical(issues) is True


def test_duplicate_activity_normalizes_case_and_whitespace() -> None:
    """Duplicates with varying whitespace and casing are correctly caught."""
    itinerary = make_valid_itinerary(num_days=2)
    itinerary.days[0].activities.append(
        make_valid_activity(
            act_id="dup_a",
            title="   Deutsches   Museum  ",
            interest_tags=["museums"],
            location_name="  Museumsinsel 1  ",
        )
    )
    itinerary.days[1].activities.append(
        make_valid_activity(
            act_id="dup_b",
            title="deutsches museum",
            interest_tags=["museums"],
            location_name="museumsinsel 1",
        )
    )

    issues = validate_itinerary(itinerary)
    dup_issues = [i for i in issues if i.code == ValidationCode.DUPLICATE_ACTIVITY]
    assert len(dup_issues) == 1
    assert (
        "Deutsches Museum" in dup_issues[0].message
        or "deutsches museum" in dup_issues[0].message.lower()
    )


# ==============================================================================
# 3. Rule 3: MAX_DAILY_ACTIVITIES Tests
# ==============================================================================


@pytest.mark.parametrize(
    "pace, cap",
    [
        (PacePreference.RELAXED, 3),
        (PacePreference.BALANCED, 4),
        (PacePreference.PACKED, 5),
    ],
)
def test_max_daily_activities_boundary_at_cap_passes(
    pace: PacePreference, cap: int
) -> None:
    """Activity counts exactly at the pace cap pass without issue."""
    itinerary = make_valid_itinerary(num_days=1, activities_per_day=cap)
    request = make_sample_request(
        start_date=date(2026, 12, 10),
        end_date=date(2026, 12, 10),
        pace=pace,
    )

    issues = validate_itinerary(itinerary, request=request)
    cap_issues = [i for i in issues if i.code == ValidationCode.MAX_DAILY_ACTIVITIES]
    assert len(cap_issues) == 0


@pytest.mark.parametrize(
    "pace, cap",
    [
        (PacePreference.RELAXED, 3),
        (PacePreference.BALANCED, 4),
        (PacePreference.PACKED, 5),
    ],
)
def test_max_daily_activities_boundary_at_cap_plus_one_fails(
    pace: PacePreference, cap: int
) -> None:
    """Activity counts at cap + 1 trigger critical MAX_DAILY_ACTIVITIES."""
    itinerary = make_valid_itinerary(num_days=1, activities_per_day=cap + 1)
    request = make_sample_request(
        start_date=date(2026, 12, 10),
        end_date=date(2026, 12, 10),
        pace=pace,
    )

    issues = validate_itinerary(itinerary, request=request)
    cap_issues = [i for i in issues if i.code == ValidationCode.MAX_DAILY_ACTIVITIES]
    assert len(cap_issues) == 1
    assert cap_issues[0].severity == ValidationSeverity.CRITICAL
    assert cap_issues[0].day_number == 1
    assert f"pace cap of {cap}" in cap_issues[0].message


# ==============================================================================
# 4. Rule 4: MISSING_REQUIRED_INTEREST Tests
# ==============================================================================


def test_missing_required_interest_passing() -> None:
    """When all requested interests appear on activities, no issue is emitted."""
    itinerary = make_valid_itinerary(num_days=2)
    itinerary.days[0].activities[0].interest_tags = ["culture", "history"]
    itinerary.days[1].activities[0].interest_tags = ["food"]

    request = make_sample_request(interests=["culture", "food"])
    issues = validate_itinerary(itinerary, request=request)
    interest_issues = [
        i for i in issues if i.code == ValidationCode.MISSING_REQUIRED_INTEREST
    ]
    assert len(interest_issues) == 0


def test_missing_required_interest_exact_match_synonyms_not_guessed() -> None:
    """Synonyms are NOT guessed: tag 'historic' does not satisfy interest 'history'."""
    itinerary = make_valid_itinerary(num_days=1)
    # Tag is 'historic', but request asks for 'history'
    itinerary.days[0].activities[0].interest_tags = ["historic"]

    request = make_sample_request(
        start_date=date(2026, 12, 10),
        end_date=date(2026, 12, 10),
        interests=["history"],
    )
    issues = validate_itinerary(itinerary, request=request)
    interest_issues = [
        i for i in issues if i.code == ValidationCode.MISSING_REQUIRED_INTEREST
    ]
    assert len(interest_issues) == 1
    assert interest_issues[0].severity == ValidationSeverity.WARNING
    assert "history" in interest_issues[0].message


def test_missing_required_interest_unsupported_interest_records_uncertainty_note() -> (
    None
):
    """An interest not supported by templates (e.g. 'falconry') records
    an uncertainty note and does not fail.
    """
    itinerary = make_valid_itinerary(num_days=1)
    request = make_sample_request(
        start_date=date(2026, 12, 10),
        end_date=date(2026, 12, 10),
        interests=["falconry"],
    )

    issues = validate_itinerary(itinerary, request=request)
    interest_issues = [
        i for i in issues if i.code == ValidationCode.MISSING_REQUIRED_INTEREST
    ]
    assert len(interest_issues) == 1
    # Severity must be WARNING, not CRITICAL
    assert interest_issues[0].severity == ValidationSeverity.WARNING
    assert has_critical(issues) is False

    # Uncertainty note must be recorded on itinerary
    assert any("falconry" in note.lower() for note in itinerary.warnings)
    assert any(
        "falconry" in note.lower() for note in itinerary.days[0].uncertainty_notes
    )


# ==============================================================================
# 5. Rule 5: MISSING_SOURCE_METADATA Tests
# ==============================================================================


def test_missing_source_metadata_passing(sample_source: SourceInfo) -> None:
    """Retrieved activity pointing to existing, complete SourceInfo passes."""
    itinerary = make_valid_itinerary(sources=[sample_source])
    itinerary.days[0].activities[0].provenance = Provenance.RETRIEVED
    itinerary.days[0].activities[0].source_refs = ["https://open-meteo.com/"]

    issues = validate_itinerary(itinerary)
    meta_issues = [
        i for i in issues if i.code == ValidationCode.MISSING_SOURCE_METADATA
    ]
    assert len(meta_issues) == 0


def test_missing_source_metadata_failing_missing_source_ref() -> None:
    """Activity with provenance 'retrieved' but no source_refs fails."""
    itinerary = make_valid_itinerary()
    # Bypass pydantic validator via object dict manipulation or valid init
    act = make_valid_activity(
        provenance=Provenance.GENERATED_SUGGESTION,
    )
    # Manually set provenance to RETRIEVED without source_refs
    object.__setattr__(act, "provenance", Provenance.RETRIEVED)
    object.__setattr__(act, "source_refs", [])
    itinerary.days[0].activities[0] = act

    issues = validate_itinerary(itinerary)
    meta_issues = [
        i for i in issues if i.code == ValidationCode.MISSING_SOURCE_METADATA
    ]
    assert len(meta_issues) >= 1
    assert meta_issues[0].severity == ValidationSeverity.CRITICAL


def test_missing_source_metadata_failing_unresolved_source() -> None:
    """Activity referencing a source URL not present in itinerary.sources fails."""
    itinerary = make_valid_itinerary(sources=[])  # Empty sources
    act = make_valid_activity(
        provenance=Provenance.RETRIEVED,
        source_refs=["https://unknown-provider.example.com"],
    )
    itinerary.days[0].activities[0] = act

    issues = validate_itinerary(itinerary)
    meta_issues = [
        i for i in issues if i.code == ValidationCode.MISSING_SOURCE_METADATA
    ]
    assert len(meta_issues) >= 1
    assert "does not exist in itinerary sources" in meta_issues[0].message


# ==============================================================================
# 6. Rule 6: Phase 3 Safety & Truthfulness Rules Tests
# ==============================================================================


def test_missing_provenance_failing() -> None:
    """Activity with invalid/missing Provenance triggers critical MISSING_PROVENANCE."""
    itinerary = make_valid_itinerary()
    act = itinerary.days[0].activities[0]
    object.__setattr__(act, "provenance", None)

    issues = validate_itinerary(itinerary)
    prov_issues = [i for i in issues if i.code == ValidationCode.MISSING_PROVENANCE]
    assert len(prov_issues) >= 1
    assert prov_issues[0].severity == ValidationSeverity.CRITICAL


def test_booking_language_passing() -> None:
    """Normal discovery and planning text without transactional language passes."""
    itinerary = make_valid_itinerary()
    itinerary.summary = (
        "A curated sightseeing plan for Munich. Indicative, not bookable here."
    )
    issues = validate_itinerary(itinerary)
    booking_issues = [
        i for i in issues if i.code == ValidationCode.BOOKING_LANGUAGE_DETECTED
    ]
    assert len(booking_issues) == 0


@pytest.mark.parametrize(
    "prohibited_term",
    [
        "booked",
        "booking confirmed",
        "reservation confirmed",
        "ticket purchased",
        "tickets purchased",
        "payment processed",
        "cancellation policy",
        "instant booking",
        "non-refundable",
    ],
)
def test_booking_language_failing(prohibited_term: str) -> None:
    """Transaction and reservation terms trigger critical BOOKING_LANGUAGE_DETECTED."""
    itinerary = make_valid_itinerary()
    itinerary.days[0].activities[
        0
    ].description = f"Your hotel room is {prohibited_term}."

    issues = validate_itinerary(itinerary)
    booking_issues = [
        i for i in issues if i.code == ValidationCode.BOOKING_LANGUAGE_DETECTED
    ]
    assert len(booking_issues) >= 1
    assert booking_issues[0].severity == ValidationSeverity.CRITICAL


def test_weather_without_tool_success_failing_when_weather_failed() -> None:
    """Weather claims made when weather tool returned ERROR trigger critical issue."""
    itinerary = make_valid_itinerary()
    itinerary.summary = "Munich itinerary: Sunny with weather forecast indicating 22°C."

    failed_weather = ToolResult(
        tool_name="get_weather",
        status=ToolStatus.ERROR,
        safe_message="Provider timeout",
        data_origin="none",
    )

    issues = validate_itinerary(itinerary, tool_results=[failed_weather])
    weather_issues = [
        i for i in issues if i.code == ValidationCode.WEATHER_WITHOUT_TOOL_SUCCESS
    ]
    assert len(weather_issues) == 1
    assert weather_issues[0].severity == ValidationSeverity.CRITICAL


def test_weather_without_tool_success_passing_when_weather_succeeded(
    sample_source: SourceInfo,
) -> None:
    """Weather claims backed by ToolStatus.OK tool result pass."""
    itinerary = make_valid_itinerary(sources=[sample_source])
    itinerary.summary = "Munich itinerary: Sunny with weather forecast indicating 22°C."

    ok_weather = ToolResult(
        tool_name="get_weather",
        status=ToolStatus.OK,
        data={"temperature": 22.0},
        source=sample_source,
        fetched_at=sample_source.fetched_at,
        data_origin="mock",
    )

    issues = validate_itinerary(itinerary, tool_results=[ok_weather])
    weather_issues = [
        i for i in issues if i.code == ValidationCode.WEATHER_WITHOUT_TOOL_SUCCESS
    ]
    assert len(weather_issues) == 0


def test_invalid_cost_status_failing_on_guaranteed_fare() -> None:
    """Cost notes claiming guaranteed live ticket prices trigger INVALID_COST_STATUS."""
    itinerary = make_valid_itinerary()
    act = itinerary.days[0].activities[0]
    object.__setattr__(act, "cost_note", "Guaranteed fare: €45.00 live booking price")

    issues = validate_itinerary(itinerary)
    cost_issues = [i for i in issues if i.code == ValidationCode.INVALID_COST_STATUS]
    assert len(cost_issues) >= 1
    assert cost_issues[0].severity == ValidationSeverity.CRITICAL


# ==============================================================================
# 7. Rule 7: BUDGET_FLOOR_VIOLATION Tests
# ==============================================================================


def test_budget_floor_violation_failing_below_hard_floor() -> None:
    """Budget below currency hard floor (e.g. $10/day vs $30 floor)
    triggers critical violation.
    """
    itinerary = make_valid_itinerary(num_days=3)
    # 2 persons * 3 days = 6 person-days. Budget $60 = $10/person/day (< $30 hard floor)
    request = make_sample_request(
        start_date=date(2026, 12, 10),
        end_date=date(2026, 12, 12),
        budget_amount="60.00",
        currency="USD",
    )

    issues = validate_itinerary(itinerary, request=request)
    budget_issues = [
        i for i in issues if i.code == ValidationCode.BUDGET_FLOOR_VIOLATION
    ]
    assert len(budget_issues) == 1
    assert budget_issues[0].severity == ValidationSeverity.CRITICAL
    assert "hard floor of USD 30.00" in budget_issues[0].message


def test_budget_floor_violation_passing_above_hard_floor() -> None:
    """Budget above hard floor passes without violation."""
    itinerary = make_valid_itinerary(num_days=3)
    request = make_sample_request(
        start_date=date(2026, 12, 10),
        end_date=date(2026, 12, 12),
        budget_amount="300.00",
        currency="USD",
    )

    issues = validate_itinerary(itinerary, request=request)
    budget_issues = [
        i for i in issues if i.code == ValidationCode.BUDGET_FLOOR_VIOLATION
    ]
    assert len(budget_issues) == 0


# ==============================================================================
# 8. Boundary Conditions: Single-Day & 30-Day Trips
# ==============================================================================


def test_boundary_single_day_trip() -> None:
    """Single-day trip (start == end, 1 day) validates cleanly."""
    single_date = date(2026, 12, 15)
    itinerary = make_valid_itinerary(
        start_date=single_date, num_days=1, activities_per_day=3
    )
    request = make_sample_request(
        start_date=single_date, end_date=single_date, pace=PacePreference.BALANCED
    )

    issues = validate_itinerary(itinerary, request=request)
    assert len([i for i in issues if i.severity == ValidationSeverity.CRITICAL]) == 0


def test_boundary_thirty_day_trip() -> None:
    """30-day extended trip with 30 consecutive days validates cleanly."""
    start_date = date(2026, 12, 1)
    end_date = start_date + timedelta(days=29)  # 30 days
    itinerary = make_valid_itinerary(
        start_date=start_date, num_days=30, activities_per_day=2
    )
    request = make_sample_request(
        start_date=start_date,
        end_date=end_date,
        pace=PacePreference.RELAXED,
        budget_amount="5000.00",
    )

    issues = validate_itinerary(itinerary, request=request)
    critical_issues = [i for i in issues if i.severity == ValidationSeverity.CRITICAL]
    assert len(critical_issues) == 0


# ==============================================================================
# 9. Deterministic Ordering & Sanitization Tests
# ==============================================================================


def test_multiple_issues_deterministic_ordering() -> None:
    """Issues are sorted deterministically: None day first, day 1, day 2,
    CRITICAL before WARNING, then code.
    """
    issues = [
        ValidationIssue(
            code=ValidationCode.DUPLICATE_ACTIVITY,
            severity=ValidationSeverity.WARNING,
            day_number=2,
            message="Duplicate on day 2",
            repair_hint="Remove dup",
        ),
        ValidationIssue(
            code=ValidationCode.MAX_DAILY_ACTIVITIES,
            severity=ValidationSeverity.CRITICAL,
            day_number=1,
            message="Overloaded day 1",
            repair_hint="Prune items",
        ),
        ValidationIssue(
            code=ValidationCode.DATE_RANGE_MISMATCH,
            severity=ValidationSeverity.CRITICAL,
            day_number=None,
            message="Date count mismatch",
            repair_hint="Align dates",
        ),
        ValidationIssue(
            code=ValidationCode.MISSING_REQUIRED_INTEREST,
            severity=ValidationSeverity.WARNING,
            day_number=None,
            message="Missing interest note",
            repair_hint="No repair",
        ),
        ValidationIssue(
            code=ValidationCode.BOOKING_LANGUAGE_DETECTED,
            severity=ValidationSeverity.CRITICAL,
            day_number=1,
            message="Booking term on day 1",
            repair_hint="Remove term",
        ),
    ]

    from app.agent.validation import _issue_sort_key

    sorted_issues = sorted(issues, key=_issue_sort_key)

    # 1. Root level (day_number None): CRITICAL first, then WARNING
    assert sorted_issues[0].code == ValidationCode.DATE_RANGE_MISMATCH
    assert sorted_issues[0].day_number is None
    assert sorted_issues[1].code == ValidationCode.MISSING_REQUIRED_INTEREST
    assert sorted_issues[1].day_number is None

    # 2. Day 1: CRITICAL issues ordered by code
    # (BOOKING_LANGUAGE_DETECTED before MAX_DAILY_ACTIVITIES)
    assert sorted_issues[2].day_number == 1
    assert sorted_issues[2].code == ValidationCode.BOOKING_LANGUAGE_DETECTED
    assert sorted_issues[3].day_number == 1
    assert sorted_issues[3].code == ValidationCode.MAX_DAILY_ACTIVITIES

    # 3. Day 2: WARNING
    assert sorted_issues[4].day_number == 2
    assert sorted_issues[4].code == ValidationCode.DUPLICATE_ACTIVITY


def test_message_sanitization_and_truncation() -> None:
    """Embedded text in validation messages is truncated to 50 chars and
    stripped of injection characters.
    """
    raw_prompt_injection = (
        "<script>alert('hack')</script> SELECT * FROM secrets WHERE `id` = 1 "
        "and this title is very very long, exceeding normal bounds by many characters."
    )
    sanitized = sanitize_message_text(raw_prompt_injection, max_length=50)

    assert len(sanitized) <= 50
    assert "<" not in sanitized
    assert ">" not in sanitized
    assert "`" not in sanitized
    assert sanitized.endswith("...")


# ==============================================================================
# 10. has_critical Helper & TripState Integration Tests
# ==============================================================================


def test_has_critical_returns_true_only_when_critical_present() -> None:
    """has_critical correctly identifies presence of critical severity."""
    assert has_critical([]) is False

    only_warnings = [
        ValidationIssue(
            code=ValidationCode.DUPLICATE_ACTIVITY,
            severity=ValidationSeverity.WARNING,
            message="warning",
            repair_hint="hint",
        )
    ]
    assert has_critical(only_warnings) is False

    with_critical = [
        ValidationIssue(
            code=ValidationCode.DUPLICATE_ACTIVITY,
            severity=ValidationSeverity.WARNING,
            message="warning",
            repair_hint="hint",
        ),
        ValidationIssue(
            code=ValidationCode.DATE_RANGE_MISMATCH,
            severity=ValidationSeverity.CRITICAL,
            message="critical",
            repair_hint="hint",
        ),
    ]
    assert has_critical(with_critical) is True


def test_validate_itinerary_with_trip_state_input() -> None:
    """validate_itinerary accepts TripState directly and validates its draft."""
    itinerary = make_valid_itinerary(num_days=2)
    request = make_sample_request(
        start_date=date(2026, 12, 10),
        end_date=date(2026, 12, 11),
    )

    state = create_fresh_trip_state(
        user_message="Plan my Munich trip",
        initial_known_fields={"destination": "Munich"},
    )
    state.itinerary_draft = itinerary
    state.trip_request = request

    issues = validate_itinerary(state)
    assert isinstance(issues, list)
    assert has_critical(issues) is False


def test_validate_itinerary_with_empty_trip_state_returns_issue() -> None:
    """validate_itinerary on TripState without draft returns critical issue."""
    state = create_fresh_trip_state(user_message="Plan trip")
    state.itinerary_draft = None

    issues = validate_itinerary(state)
    assert len(issues) == 1
    assert issues[0].code == ValidationCode.DATE_RANGE_MISMATCH
    assert issues[0].severity == ValidationSeverity.CRITICAL
