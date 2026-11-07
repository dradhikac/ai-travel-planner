"""Comprehensive unit and integration tests for Phase 3 clarification and errors.

Verifies:
1. Each essential field missing individually and in combination triggers clarification.
2. Contradictory inputs (reversed dates, origin equals destination, invalid party size,
   past dates, duration > 30 days) route to clarification with explicit reasoning.
3. Safe defaults apply ONLY for pace (balanced), interests ([]), and budget (None),
   and are announced in response warnings.
4. Stateless multi-turn interaction works across requests using known_fields.
5. Geocode failure: empty -> FAILED with not found + rephrase suggestion;
   timeout/error/rate_limited -> FAILED with safe retry message.
6. Weather failure policy: timeout/error/out-of-range -> PARTIAL with itinerary without
   weather statements, weather=None, and explicit warning.
7. Malformed tool output does not crash; returns safe FAILED or PARTIAL.
8. Tool activity audit entries: no URLs with query strings, no stack traces,
   no secrets, and failed tools never claim live success.
"""

from datetime import UTC, date, datetime
from typing import Any

import pytest

from app.agent.errors import ToolErrorCode
from app.agent.graph import run_workflow
from app.agent.nodes import sanitize_url
from app.agent.state import RunStatus, create_fresh_trip_state
from app.agent.tools.contracts import ToolResult, ToolStatus
from app.schemas.provider import SourceInfo, WeatherDay, WeatherSummary
from app.schemas.trip import TripRequest


@pytest.fixture(autouse=True)
def reference_today() -> date:
    """Set deterministic reference date for trip validation across tests."""
    ref_date = date(2026, 11, 1)
    TripRequest.set_test_today(ref_date)
    yield ref_date
    TripRequest.set_test_today(None)


@pytest.fixture
def sample_source_with_query() -> SourceInfo:
    """SourceInfo fixture containing a raw URL with sensitive query parameters."""
    return SourceInfo(
        provider="Open-Meteo",
        url="https://geocoding-api.open-meteo.com/v1/search?name=Tokyo&count=5&apikey=secret123",
        attribution="Weather data by Open-Meteo.com",
        fetched_at=datetime(2026, 11, 1, 12, 0, 0, tzinfo=UTC),
        data_origin="mock",
    )


@pytest.fixture
def mock_geocode_ok(sample_source_with_query: SourceInfo) -> ToolResult:
    return ToolResult(
        tool_name="geocode_destination",
        status=ToolStatus.OK,
        data=[
            {
                "name": "Tokyo",
                "country": "Japan",
                "latitude": 35.6762,
                "longitude": 139.6503,
            }
        ],
        source=sample_source_with_query,
        fetched_at=sample_source_with_query.fetched_at,
        data_origin="mock",
    )


@pytest.fixture
def mock_weather_ok(sample_source_with_query: SourceInfo) -> ToolResult:
    summary = WeatherSummary(
        location="Tokyo, Japan",
        data_origin="mock",
        days=[
            WeatherDay(
                date=date(2026, 11, 5),
                temp_min_c=12.0,
                temp_max_c=18.0,
                precipitation_probability_pct=10,
                precipitation_sum_mm=0.0,
                weather_code=1,
                condition_description="Clear",
            )
        ],
        units={"temperature": "celsius", "precipitation": "mm"},
        source=sample_source_with_query,
        fetched_at=sample_source_with_query.fetched_at,
    )
    return ToolResult(
        tool_name="get_weather",
        status=ToolStatus.OK,
        data=summary.model_dump(mode="json"),
        source=sample_source_with_query,
        fetched_at=sample_source_with_query.fetched_at,
        data_origin="mock",
    )


class RecordingTool:
    def __init__(self, result: ToolResult) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    def __call__(self, args: dict[str, Any]) -> ToolResult:
        self.calls.append(args)
        return self.result


# ==============================================================================
# 1. Missing Essential Fields Tests
# ==============================================================================


def test_missing_destination_routes_to_clarification() -> None:
    """Missing destination alone routes to ask_clarification."""
    state = create_fresh_trip_state(
        user_message="Plan a trip from London on 2026-11-05 to 2026-11-08 for 2 people",
        initial_known_fields={
            "origin": "London",
            "start_date": "2026-11-05",
            "end_date": "2026-11-08",
            "party_size": 2,
        },
    )
    final_state = run_workflow(state)

    assert final_state.status == RunStatus.NEEDS_CLARIFICATION
    assert "destination" in final_state.missing_fields
    assert final_state.clarification_question is not None
    assert "destination city" in final_state.clarification_question.lower()
    assert len(final_state.tool_results) == 0


def test_missing_origin_routes_to_clarification() -> None:
    """Missing origin alone routes to ask_clarification."""
    state = create_fresh_trip_state(
        user_message="Plan a trip to Paris on 2026-11-05 to 2026-11-08 for 2 people",
        initial_known_fields={
            "destination": "Paris",
            "start_date": "2026-11-05",
            "end_date": "2026-11-08",
            "party_size": 2,
        },
    )
    final_state = run_workflow(state)

    assert final_state.status == RunStatus.NEEDS_CLARIFICATION
    assert "origin" in final_state.missing_fields
    assert final_state.clarification_question is not None
    assert "departure location" in final_state.clarification_question.lower()
    assert len(final_state.tool_results) == 0


def test_missing_dates_routes_to_clarification() -> None:
    """Missing both dates routes to ask_clarification and asks for travel dates."""
    state = create_fresh_trip_state(
        user_message="Plan a trip from London to Tokyo for 2 travelers",
        initial_known_fields={
            "origin": "London",
            "destination": "Tokyo",
            "party_size": 2,
        },
    )
    final_state = run_workflow(state)

    assert final_state.status == RunStatus.NEEDS_CLARIFICATION
    assert "dates" in final_state.missing_fields
    assert final_state.clarification_question is not None
    assert "travel dates" in final_state.clarification_question.lower()
    assert len(final_state.tool_results) == 0


def test_missing_start_date_alone_routes_to_clarification() -> None:
    """Missing start_date alone asks specifically for departure date."""
    state = create_fresh_trip_state(
        user_message="Trip returning 2026-11-10",
        initial_known_fields={
            "origin": "London",
            "destination": "Tokyo",
            "end_date": "2026-11-10",
            "party_size": 2,
        },
    )
    final_state = run_workflow(state)

    assert final_state.status == RunStatus.NEEDS_CLARIFICATION
    assert "start_date" in final_state.missing_fields
    assert "departure date" in final_state.clarification_question.lower()


def test_missing_end_date_alone_routes_to_clarification() -> None:
    """Missing end_date alone asks specifically for return date."""
    state = create_fresh_trip_state(
        user_message="Trip starting 2026-11-05",
        initial_known_fields={
            "origin": "London",
            "destination": "Tokyo",
            "start_date": "2026-11-05",
            "party_size": 2,
        },
    )
    final_state = run_workflow(state)

    assert final_state.status == RunStatus.NEEDS_CLARIFICATION
    assert "end_date" in final_state.missing_fields
    assert "return date" in final_state.clarification_question.lower()


def test_missing_party_size_routes_to_clarification() -> None:
    """Missing party_size routes to ask_clarification without inventing a default."""
    state = create_fresh_trip_state(
        user_message="Plan a trip from London to Tokyo from 2026-11-05 to 2026-11-08",
        initial_known_fields={
            "origin": "London",
            "destination": "Tokyo",
            "start_date": "2026-11-05",
            "end_date": "2026-11-08",
        },
    )
    final_state = run_workflow(state)

    assert final_state.status == RunStatus.NEEDS_CLARIFICATION
    assert "party_size" in final_state.missing_fields
    assert final_state.clarification_question is not None
    assert "number of travelers" in final_state.clarification_question.lower()


def test_missing_all_essential_fields_combined() -> None:
    """Missing multiple essential fields produces ONE concise question."""
    state = create_fresh_trip_state(
        user_message="I want to go on vacation",
        initial_known_fields={},
    )
    final_state = run_workflow(state)

    assert final_state.status == RunStatus.NEEDS_CLARIFICATION
    assert "destination" in final_state.missing_fields
    assert "origin" in final_state.missing_fields
    assert "dates" in final_state.missing_fields
    assert "party_size" in final_state.missing_fields

    q = final_state.clarification_question
    assert q is not None
    assert q.endswith("?")
    assert "destination city" in q
    assert "departure location" in q
    assert "travel dates" in q
    assert "number of travelers" in q


# ==============================================================================
# 2. Contradiction & Unparseable Values Tests
# ==============================================================================


def test_reversed_dates_contradiction_routes_to_clarification() -> None:
    """Reversed travel dates (end_date < start_date) triggers clarification."""
    state = create_fresh_trip_state(
        user_message=(
            "Plan a trip from London to Rome from 2026-11-10 to 2026-11-05 for 2"
        ),
        initial_known_fields={
            "origin": "London",
            "destination": "Rome",
            "start_date": "2026-11-10",
            "end_date": "2026-11-05",
            "party_size": 2,
        },
    )
    final_state = run_workflow(state)

    assert final_state.status == RunStatus.NEEDS_CLARIFICATION
    assert len(final_state.contradictions) > 0
    assert any("earlier than" in c.lower() for c in final_state.contradictions)
    assert final_state.clarification_question is not None
    assert "return date cannot be earlier" in final_state.clarification_question.lower()


def test_identical_origin_and_destination_contradiction() -> None:
    """Origin identical to destination (case-insensitive) triggers clarification."""
    state = create_fresh_trip_state(
        user_message=(
            "Plan a trip from Paris to paris from 2026-11-05 to 2026-11-08 for 1"
        ),
        initial_known_fields={
            "origin": "Paris",
            "destination": "paris",
            "start_date": "2026-11-05",
            "end_date": "2026-11-08",
            "party_size": 1,
        },
    )
    final_state = run_workflow(state)

    assert final_state.status == RunStatus.NEEDS_CLARIFICATION
    assert any("identical" in c.lower() for c in final_state.contradictions)
    assert "identical" in final_state.clarification_question.lower()


def test_past_start_date_contradiction_routes_to_clarification() -> None:
    """Trip starting in the past (before reference today) triggers clarification."""
    state = create_fresh_trip_state(
        user_message="Plan trip from London to Rome in 2026-10-01",
        initial_known_fields={
            "origin": "London",
            "destination": "Rome",
            "start_date": "2026-10-01",  # Past (today is 2026-11-01)
            "end_date": "2026-10-05",
            "party_size": 2,
        },
    )
    final_state = run_workflow(state)

    assert final_state.status == RunStatus.NEEDS_CLARIFICATION
    assert any("past" in c.lower() for c in final_state.contradictions)


def test_trip_duration_exceeds_30_days_contradiction() -> None:
    """Trip length exceeding 30 days triggers clarification with limit note."""
    state = create_fresh_trip_state(
        user_message="Plan 40-day trip from London to Rome",
        initial_known_fields={
            "origin": "London",
            "destination": "Rome",
            "start_date": "2026-11-01",
            "end_date": "2026-12-15",  # 45 days
            "party_size": 2,
        },
    )
    final_state = run_workflow(state)

    assert final_state.status == RunStatus.NEEDS_CLARIFICATION
    assert any("30 days" in c for c in final_state.contradictions)


def test_invalid_party_size_contradiction() -> None:
    """Party size < 1 or > 20 triggers clarification with group limit note."""
    state = create_fresh_trip_state(
        user_message="Trip for 0 people",
        initial_known_fields={
            "origin": "London",
            "destination": "Rome",
            "start_date": "2026-11-05",
            "end_date": "2026-11-08",
            "party_size": 0,
        },
    )
    final_state = run_workflow(state)

    assert final_state.status == RunStatus.NEEDS_CLARIFICATION
    assert any("at least 1" in c.lower() for c in final_state.contradictions)


def test_unparseable_date_contradiction() -> None:
    """Non-ISO or invalid calendar date triggers clarification."""
    state = create_fresh_trip_state(
        user_message="Trip on invalid dates",
        initial_known_fields={
            "origin": "London",
            "destination": "Rome",
            "start_date": "not-a-date",
            "end_date": "2026-11-08",
            "party_size": 2,
        },
    )
    final_state = run_workflow(state)

    assert final_state.status == RunStatus.NEEDS_CLARIFICATION
    assert any("valid ISO" in c for c in final_state.contradictions)


# ==============================================================================
# 3. Safe Defaults Tests
# ==============================================================================


def test_safe_defaults_applied_and_announced_in_warnings(
    mock_geocode_ok: ToolResult,
    mock_weather_ok: ToolResult,
) -> None:
    """Safe defaults apply ONLY for pace, interests, budget, announced in warnings."""
    tools = {
        "geocode_destination": RecordingTool(mock_geocode_ok),
        "get_weather": RecordingTool(mock_weather_ok),
    }

    state = create_fresh_trip_state(
        user_message=(
            "Plan a trip from London to Tokyo from 2026-11-05 to 2026-11-08 for 2"
        ),
        initial_known_fields={
            "origin": "London",
            "destination": "Tokyo",
            "start_date": "2026-11-05",
            "end_date": "2026-11-08",
            "party_size": 2,
            # pace, interests, budget omitted
        },
    )
    final_state = run_workflow(state, tools=tools)

    assert final_state.status == RunStatus.COMPLETED
    assert final_state.final_response is not None

    req = final_state.final_response.request
    assert req.pace == "balanced"
    assert req.interests == []
    assert req.budget_amount is None

    # Check announced warnings
    warnings = final_state.final_response.warnings
    assert any(
        "pace was not specified; defaulted to balanced pace" in w for w in warnings
    )
    assert any(
        "interests were not specified; defaulting to general" in w for w in warnings
    )
    assert any(
        "budget was not specified; estimated costs will be unknown" in w.lower()
        for w in warnings
    )


# ==============================================================================
# 4. Stateless Multi-turn Clarification Simulation
# ==============================================================================


def test_stateless_multi_turn_clarification(
    mock_geocode_ok: ToolResult,
    mock_weather_ok: ToolResult,
) -> None:
    """Stateless multi-turn intake: first call asks for info; second call completes."""
    tools = {
        "geocode_destination": RecordingTool(mock_geocode_ok),
        "get_weather": RecordingTool(mock_weather_ok),
    }

    # Turn 1: Incomplete prompt
    state_turn1 = create_fresh_trip_state(
        user_message="I'd like to visit Tokyo",
        initial_known_fields={"destination": "Tokyo"},
    )
    out_turn1 = run_workflow(state_turn1, tools=tools)

    assert out_turn1.status == RunStatus.NEEDS_CLARIFICATION
    assert out_turn1.clarification_question is not None
    assert "origin" in out_turn1.missing_fields
    assert "dates" in out_turn1.missing_fields

    # Client collects answers and sends accumulated fields
    accumulated_fields = dict(out_turn1.known_fields)
    accumulated_fields.update(
        {
            "origin": "London",
            "start_date": "2026-11-05",
            "end_date": "2026-11-08",
            "party_size": 2,
        }
    )

    # Turn 2: New stateless call with accumulated fields
    state_turn2 = create_fresh_trip_state(
        user_message=(
            "Departing from London from 2026-11-05 to 2026-11-08 for 2 travelers"
        ),
        initial_known_fields=accumulated_fields,
    )
    out_turn2 = run_workflow(state_turn2, tools=tools)

    assert out_turn2.status == RunStatus.COMPLETED
    assert out_turn2.final_response is not None
    assert out_turn2.final_response.request.destination == "Tokyo"
    assert out_turn2.final_response.request.origin == "London"
    assert len(out_turn2.final_response.itinerary.days) == 4


# ==============================================================================
# 5. Geocode Failure Policies
# ==============================================================================


def test_geocode_empty_returns_failed_with_rephrase_suggestion() -> None:
    """Geocode empty results in FAILED with destination not found and rephrase hint."""
    mock_empty = ToolResult(
        tool_name="geocode_destination",
        status=ToolStatus.EMPTY,
        data=[],
        safe_message="No locations found.",
        data_origin="none",
    )
    tools = {"geocode_destination": RecordingTool(mock_empty)}

    state = create_fresh_trip_state(
        user_message=(
            "Plan a trip from London to Atlantis on 2026-11-05 to 2026-11-08 for 1"
        ),
        initial_known_fields={
            "origin": "London",
            "destination": "Atlantis",
            "start_date": "2026-11-05",
            "end_date": "2026-11-08",
            "party_size": 1,
        },
    )
    final_state = run_workflow(state, tools=tools)

    assert final_state.status == RunStatus.FAILED
    assert final_state.final_response is None
    assert any(
        "could not find that destination" in w.lower() for w in final_state.warnings
    )
    assert any(
        "rephrase" in w.lower() or "more specific" in w.lower()
        for w in final_state.warnings
    )


def test_geocode_timeout_returns_failed_with_safe_retry_message() -> None:
    """Geocode timeout results in FAILED with safe retry message."""
    mock_timeout = ToolResult(
        tool_name="geocode_destination",
        status=ToolStatus.TIMEOUT,
        error_code=ToolErrorCode.TIMEOUT,
        safe_message="Search timed out.",
        data_origin="none",
    )
    tools = {"geocode_destination": RecordingTool(mock_timeout)}

    state = create_fresh_trip_state(
        user_message="Plan a trip to Tokyo",
        initial_known_fields={
            "origin": "London",
            "destination": "Tokyo",
            "start_date": "2026-11-05",
            "end_date": "2026-11-08",
            "party_size": 1,
        },
    )
    final_state = run_workflow(state, tools=tools)

    assert final_state.status == RunStatus.FAILED
    assert final_state.final_response is None
    assert any("timed out" in w.lower() for w in final_state.warnings)
    assert any("try again" in w.lower() for w in final_state.warnings)


def test_geocode_rate_limited_returns_failed_with_retry_message() -> None:
    """Geocode rate limited results in FAILED with safe retry message."""
    mock_rate_limit = ToolResult(
        tool_name="geocode_destination",
        status=ToolStatus.RATE_LIMITED,
        error_code=ToolErrorCode.RATE_LIMITED,
        safe_message="Rate limit exceeded.",
        data_origin="none",
    )
    tools = {"geocode_destination": RecordingTool(mock_rate_limit)}

    state = create_fresh_trip_state(
        user_message="Plan a trip to Tokyo",
        initial_known_fields={
            "origin": "London",
            "destination": "Tokyo",
            "start_date": "2026-11-05",
            "end_date": "2026-11-08",
            "party_size": 1,
        },
    )
    final_state = run_workflow(state, tools=tools)

    assert final_state.status == RunStatus.FAILED
    assert any("rate limit" in w.lower() for w in final_state.warnings)


def test_geocode_error_returns_failed_with_safe_message() -> None:
    """Geocode general error results in FAILED with safe message."""
    mock_err = ToolResult(
        tool_name="geocode_destination",
        status=ToolStatus.ERROR,
        error_code=ToolErrorCode.PROVIDER_UNAVAILABLE,
        safe_message="Service unavailable.",
        data_origin="none",
    )
    tools = {"geocode_destination": RecordingTool(mock_err)}

    state = create_fresh_trip_state(
        user_message="Plan a trip to Tokyo",
        initial_known_fields={
            "origin": "London",
            "destination": "Tokyo",
            "start_date": "2026-11-05",
            "end_date": "2026-11-08",
            "party_size": 1,
        },
    )
    final_state = run_workflow(state, tools=tools)

    assert final_state.status == RunStatus.FAILED
    assert any("temporary error" in w.lower() for w in final_state.warnings)


# ==============================================================================
# 6. Weather Failure Policies
# ==============================================================================


def test_weather_timeout_returns_partial_with_warning_and_no_weather_statements(
    mock_geocode_ok: ToolResult,
) -> None:
    """Weather timeout produces PARTIAL run without weather statements."""
    mock_weather_timeout = ToolResult(
        tool_name="get_weather",
        status=ToolStatus.TIMEOUT,
        error_code=ToolErrorCode.TIMEOUT,
        safe_message="Weather timeout",
        data_origin="none",
    )
    tools = {
        "geocode_destination": RecordingTool(mock_geocode_ok),
        "get_weather": RecordingTool(mock_weather_timeout),
    }

    state = create_fresh_trip_state(
        user_message=(
            "Plan a trip from London to Tokyo on 2026-11-05 to 2026-11-08 for 2"
        ),
        initial_known_fields={
            "origin": "London",
            "destination": "Tokyo",
            "start_date": "2026-11-05",
            "end_date": "2026-11-08",
            "party_size": 2,
        },
    )
    final_state = run_workflow(state, tools=tools)

    assert final_state.status == RunStatus.PARTIAL
    assert final_state.final_response is not None
    assert final_state.final_response.weather is None

    # Itinerary must have NO live forecast statements (e.g. °C, precipitation sum, etc.)
    for day in final_state.final_response.itinerary.days:
        for item in day.items:
            assert "°C" not in item.description
            if item.note:
                assert "Forecast:" not in item.note

    assert any("timed out" in w.lower() for w in final_state.final_response.warnings)


def test_weather_out_of_range_returns_partial_with_warning(
    mock_geocode_ok: ToolResult,
) -> None:
    """Weather out of range produces PARTIAL status and explicit horizon notice."""
    mock_weather_out_of_range = ToolResult(
        tool_name="get_weather",
        status=ToolStatus.ERROR,
        error_code=ToolErrorCode.OUT_OF_FORECAST_RANGE,
        safe_message="Dates outside 16-day forecast horizon.",
        data_origin="none",
    )
    tools = {
        "geocode_destination": RecordingTool(mock_geocode_ok),
        "get_weather": RecordingTool(mock_weather_out_of_range),
    }

    state = create_fresh_trip_state(
        user_message=(
            "Plan a trip from London to Tokyo on 2026-11-05 to 2026-11-08 for 2"
        ),
        initial_known_fields={
            "origin": "London",
            "destination": "Tokyo",
            "start_date": "2026-11-05",
            "end_date": "2026-11-08",
            "party_size": 2,
        },
    )
    final_state = run_workflow(state, tools=tools)

    assert final_state.status == RunStatus.PARTIAL
    assert final_state.final_response is not None
    assert final_state.final_response.weather is None
    assert any(
        "weather forecast is unavailable" in w.lower()
        for w in final_state.final_response.warnings
    )


# ==============================================================================
# 7. Malformed Tool Output & Robustness
# ==============================================================================


def test_malformed_tool_output_handled_safely(
    mock_geocode_ok: ToolResult,
) -> None:
    """Tool returning malformed payload does not crash; handled safely as PARTIAL."""
    mock_malformed_weather = ToolResult(
        tool_name="get_weather",
        status=ToolStatus.OK,
        data={"invalid_structure": "garbage"},  # Not a valid WeatherSummary
        data_origin="none",
    )
    tools = {
        "geocode_destination": RecordingTool(mock_geocode_ok),
        "get_weather": RecordingTool(mock_malformed_weather),
    }

    state = create_fresh_trip_state(
        user_message=(
            "Plan a trip from London to Tokyo from 2026-11-05 to 2026-11-08 for 2"
        ),
        initial_known_fields={
            "origin": "London",
            "destination": "Tokyo",
            "start_date": "2026-11-05",
            "end_date": "2026-11-08",
            "party_size": 2,
        },
    )
    final_state = run_workflow(state, tools=tools)

    # Workflow handles gracefully without unhandled exception
    assert final_state.status == RunStatus.PARTIAL
    assert final_state.final_response is not None
    assert final_state.final_response.weather is None


# ==============================================================================
# 8. Tool Activity Sanitization & Audit Trail
# ==============================================================================


def test_tool_activity_entries_present_and_sanitized(
    mock_geocode_ok: ToolResult,
    mock_weather_ok: ToolResult,
) -> None:
    """tool_activity entries contain no query strings, stack traces, or secrets."""
    tools = {
        "geocode_destination": RecordingTool(mock_geocode_ok),
        "get_weather": RecordingTool(mock_weather_ok),
    }

    state = create_fresh_trip_state(
        user_message=(
            "Plan a trip from London to Tokyo on 2026-11-05 to 2026-11-08 for 2"
        ),
        initial_known_fields={
            "origin": "London",
            "destination": "Tokyo",
            "start_date": "2026-11-05",
            "end_date": "2026-11-08",
            "party_size": 2,
        },
    )
    final_state = run_workflow(state, tools=tools)

    assert len(final_state.tool_activity) == 2
    assert final_state.final_response is not None
    assert len(final_state.final_response.tool_activity) == 2

    for entry in final_state.tool_activity:
        # Check required audit fields
        assert entry.tool_label in ("Destination Geocoding", "Weather Forecast")
        assert entry.status == "ok"
        assert entry.data_origin == "mock"
        assert entry.fetched_at is not None
        assert len(entry.explanation) > 10

        # Assert no query strings in source
        assert "?" not in entry.source
        assert "apikey" not in entry.source.lower()
        assert "secret" not in entry.source.lower()

        # Assert no stack traces
        assert "traceback" not in entry.explanation.lower()
        assert 'file "' not in entry.explanation.lower()


def test_failed_tool_never_shown_as_successful_live_result(
    mock_geocode_ok: ToolResult,
) -> None:
    """Failed tools must never claim live success in tool_activity or sources."""
    mock_failed_weather = ToolResult(
        tool_name="get_weather",
        status=ToolStatus.TIMEOUT,
        error_code=ToolErrorCode.TIMEOUT,
        safe_message="Timeout",
        data_origin="none",
    )
    tools = {
        "geocode_destination": RecordingTool(mock_geocode_ok),
        "get_weather": RecordingTool(mock_failed_weather),
    }

    state = create_fresh_trip_state(
        user_message=(
            "Plan a trip from London to Tokyo on 2026-11-05 to 2026-11-08 for 2"
        ),
        initial_known_fields={
            "origin": "London",
            "destination": "Tokyo",
            "start_date": "2026-11-05",
            "end_date": "2026-11-08",
            "party_size": 2,
        },
    )
    final_state = run_workflow(state, tools=tools)

    weather_activity = next(
        a for a in final_state.tool_activity if a.tool_label == "Weather Forecast"
    )
    assert weather_activity.status == "timeout"
    assert weather_activity.data_origin == "none"

    # TripResponse sources must NOT include weather source
    assert final_state.final_response is not None
    sources = final_state.final_response.sources
    assert not any("weather" in str(s.url).lower() for s in sources)


def test_sanitize_url_helper() -> None:
    """sanitize_url helper cleanly strips query parameters and fragment anchors."""
    url = "https://api.example.com/search?q=Paris&key=secret#section1"
    cleaned = sanitize_url(url)
    assert cleaned == "https://api.example.com/search"

    assert sanitize_url(None) is None
    assert sanitize_url("") is None
