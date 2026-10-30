"""Unit tests for Phase 3 typed TripState, tool arguments, and ToolResult contracts."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from app.agent.errors import ToolErrorCode
from app.agent.state import (
    Intent,
    RunStatus,
    TripState,
    create_fresh_trip_state,
)
from app.agent.tools import (
    GeocodeArgs,
    ToolCall,
    ToolResult,
    ToolStatus,
    WeatherArgs,
)
from app.schemas.provider import SourceInfo
from app.schemas.trip import (
    Itinerary,
    ItineraryDay,
    ItineraryItem,
    PacePreference,
    TimeOfDay,
    TripRequest,
    TripResponse,
)

# ==============================================================================
# 1. GeocodeArgs Contract Tests
# ==============================================================================


def test_geocode_args_valid_and_normalized() -> None:
    """GeocodeArgs normalizes whitespace, trims query, and uppercases country code."""
    args = GeocodeArgs(query="  Paris   France  ", country_code="fr", count=5)
    assert args.query == "Paris France"
    assert args.country_code == "FR"
    assert args.count == 5


def test_geocode_args_count_boundaries() -> None:
    """GeocodeArgs accepts counts 1 to 10 and rejects outside boundaries."""
    assert GeocodeArgs(query="Rome", count=1).count == 1
    assert GeocodeArgs(query="Rome", count=10).count == 10

    with pytest.raises(ValueError):
        GeocodeArgs(query="Rome", count=0)

    with pytest.raises(ValueError):
        GeocodeArgs(query="Rome", count=11)


def test_geocode_args_rejects_blank_or_too_long_query() -> None:
    """GeocodeArgs rejects blank strings and queries exceeding 100 characters."""
    with pytest.raises(ValueError, match="Location query cannot be empty"):
        GeocodeArgs(query="   ")

    with pytest.raises(ValueError):
        GeocodeArgs(query="A" * 101)


def test_geocode_args_country_code_validation() -> None:
    """GeocodeArgs requires exactly 2 alphabetic characters for country code."""
    assert GeocodeArgs(query="Madrid", country_code=None).country_code is None
    assert GeocodeArgs(query="Madrid", country_code="es").country_code == "ES"

    with pytest.raises(ValueError, match="2-letter alphabetic"):
        GeocodeArgs(query="Madrid", country_code="ESP")

    with pytest.raises(ValueError, match="2-letter alphabetic"):
        GeocodeArgs(query="Madrid", country_code="12")


# ==============================================================================
# 2. WeatherArgs Contract Tests
# ==============================================================================


def test_weather_args_valid_coordinates_and_dates() -> None:
    """WeatherArgs accepts valid coordinates and date ordering."""
    args = WeatherArgs(
        latitude=48.8566,
        longitude=2.3522,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 5),
    )
    assert args.latitude == 48.8566
    assert args.longitude == 2.3522
    assert args.start_date == date(2026, 6, 1)
    assert args.end_date == date(2026, 6, 5)


def test_weather_args_coordinate_bounds() -> None:
    """WeatherArgs validates latitude (-90..90) and longitude (-180..180)."""
    # Accept boundaries
    assert WeatherArgs(
        latitude=-90.0,
        longitude=-180.0,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 1),
    )
    assert WeatherArgs(
        latitude=90.0,
        longitude=180.0,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 1),
    )

    with pytest.raises(ValueError):
        WeatherArgs(
            latitude=-90.1,
            longitude=0.0,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 1),
        )

    with pytest.raises(ValueError):
        WeatherArgs(
            latitude=0.0,
            longitude=180.1,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 1),
        )


def test_weather_args_rejects_inverted_dates() -> None:
    """WeatherArgs rejects end_date earlier than start_date."""
    with pytest.raises(ValueError, match="end_date must be on or after start_date"):
        WeatherArgs(
            latitude=52.52,
            longitude=13.405,
            start_date=date(2026, 6, 10),
            end_date=date(2026, 6, 5),
        )


def test_weather_args_duration_bounds() -> None:
    """WeatherArgs rejects date spans exceeding 30 days limit."""
    # 30 days inclusive is allowed
    WeatherArgs(
        latitude=52.52,
        longitude=13.405,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 30),
    )

    # 31 days is rejected
    with pytest.raises(ValueError, match="exceeds maximum allowed limit of 30 days"):
        WeatherArgs(
            latitude=52.52,
            longitude=13.405,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 7, 1),
        )


# ==============================================================================
# 3. ToolResult Invariants & Truthfulness Tests
# ==============================================================================


def test_tool_result_success_invariant() -> None:
    """ToolResult with OK status allows live or mock origin and stores data."""
    source = SourceInfo(
        provider="Open-Meteo",
        url="https://api.open-meteo.com/v1/forecast",
        attribution="Weather data by Open-Meteo.com",
        fetched_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
        data_origin="live",
    )
    result = ToolResult(
        tool_name="weather_tool",
        status=ToolStatus.OK,
        data={"temp": 22.5},
        source=source,
        fetched_at=datetime.now(UTC),
        data_origin="live",
        latency_ms=120.5,
    )
    assert result.status == ToolStatus.OK
    assert result.data_origin == "live"
    assert result.data == {"temp": 22.5}
    assert result.latency_ms == 120.5


def test_tool_result_ok_rejects_none_data() -> None:
    """ToolResult with status OK must contain non-null data payload."""
    with pytest.raises(ValueError, match="must contain non-null data"):
        ToolResult(
            tool_name="geocode_tool",
            status=ToolStatus.OK,
            data=None,
            data_origin="live",
        )


@pytest.mark.parametrize(
    "failure_status",
    [
        ToolStatus.ERROR,
        ToolStatus.TIMEOUT,
        ToolStatus.RATE_LIMITED,
        ToolStatus.SKIPPED,
    ],
)
def test_tool_result_failed_cannot_claim_live_or_mock(
    failure_status: ToolStatus,
) -> None:
    """Failed or skipped results must have data_origin='none'."""
    # Disallow data_origin='live'
    with pytest.raises(
        ValueError, match="data_origin must be 'none' for failed or skipped status"
    ):
        ToolResult(
            tool_name="weather_tool",
            status=failure_status,
            error_code=ToolErrorCode.TIMEOUT,
            safe_message="Request timed out",
            data_origin="live",
        )

    # Disallow data_origin='mock'
    with pytest.raises(
        ValueError, match="data_origin must be 'none' for failed or skipped status"
    ):
        ToolResult(
            tool_name="weather_tool",
            status=failure_status,
            error_code=ToolErrorCode.PROVIDER_UNAVAILABLE,
            safe_message="Service offline",
            data_origin="mock",
        )

    # Valid failure representation with data_origin='none'
    res = ToolResult(
        tool_name="weather_tool",
        status=failure_status,
        error_code=ToolErrorCode.TIMEOUT,
        safe_message="Service timed out",
        data_origin="none",
    )
    assert res.data_origin == "none"
    assert res.status == failure_status


def test_tool_result_fetched_at_utc_conversion() -> None:
    """ToolResult automatically converts naive fetched_at timestamps to UTC."""
    naive_dt = datetime(2026, 6, 1, 10, 30)
    result = ToolResult(
        tool_name="geocode_tool",
        status=ToolStatus.EMPTY,
        data=None,
        fetched_at=naive_dt,
        data_origin="none",
    )
    assert result.fetched_at is not None
    assert result.fetched_at.tzinfo == UTC


# ==============================================================================
# 4. ToolCall Contract Tests
# ==============================================================================


def test_tool_call_instantiation() -> None:
    """ToolCall encapsulates tool_name, arguments, and optional call_id."""
    call = ToolCall(
        tool_name="geocode_tool",
        arguments={"query": "Tokyo", "count": 3},
        call_id="call-12345",
    )
    assert call.tool_name == "geocode_tool"
    assert call.arguments["query"] == "Tokyo"
    assert call.call_id == "call-12345"


# ==============================================================================
# 5. Enum Round-Trip Tests
# ==============================================================================


def test_enum_values_and_round_trips() -> None:
    """Enums serialize to exact strings and deserialize cleanly."""
    for s in [
        ToolStatus.OK,
        ToolStatus.EMPTY,
        ToolStatus.ERROR,
        ToolStatus.TIMEOUT,
        ToolStatus.RATE_LIMITED,
        ToolStatus.SKIPPED,
    ]:
        assert ToolStatus(str(s)) == s

    for e in [
        ToolErrorCode.PROVIDER_UNAVAILABLE,
        ToolErrorCode.TIMEOUT,
        ToolErrorCode.RATE_LIMITED,
        ToolErrorCode.INVALID_ARGUMENTS,
        ToolErrorCode.MALFORMED_RESPONSE,
        ToolErrorCode.NOT_FOUND,
        ToolErrorCode.EXECUTION_FAILED,
        ToolErrorCode.SKIPPED,
    ]:
        assert ToolErrorCode(str(e)) == e

    for i in [
        Intent.DESTINATION_DISCOVERY,
        Intent.WEATHER_PLANNING,
        Intent.ITINERARY_PLANNING,
        Intent.UNSUPPORTED,
    ]:
        assert Intent(str(i)) == i

    for r in [
        RunStatus.NEEDS_CLARIFICATION,
        RunStatus.COMPLETED,
        RunStatus.PARTIAL,
        RunStatus.FAILED,
    ]:
        assert RunStatus(str(r)) == r


# ==============================================================================
# 6. TripState Lifecycle & Constructor Helper Tests
# ==============================================================================


def test_create_fresh_trip_state_defaults() -> None:
    """create_fresh_trip_state initializes valid default state."""
    state = create_fresh_trip_state(
        user_message="Plan a weekend in Rome",
        initial_known_fields={"destination": "Rome"},
        intent=Intent.ITINERARY_PLANNING,
    )
    assert state.user_message == "Plan a weekend in Rome"
    assert state.request_id.startswith("req_")
    assert state.known_fields == {"destination": "Rome"}
    assert state.intent == Intent.ITINERARY_PLANNING
    assert state.status == RunStatus.NEEDS_CLARIFICATION
    assert state.low_budget is False
    assert state.repair_attempts == 0
    assert state.step_count == 0
    assert state.missing_fields == []
    assert state.planned_tool_calls == []
    assert state.tool_results == []
    assert state.warnings == []


def test_create_fresh_trip_state_rejects_empty_message() -> None:
    """create_fresh_trip_state rejects empty user message."""
    with pytest.raises(ValueError, match="user_message cannot be empty"):
        create_fresh_trip_state("   ")


def test_trip_state_custom_request_id() -> None:
    """TripState accepts a custom request_id string."""
    state = create_fresh_trip_state(
        user_message="Test trip",
        request_id="custom-req-001",
    )
    assert state.request_id == "custom-req-001"


# ==============================================================================
# 7. Security: Secret Rejection in known_fields
# ==============================================================================


@pytest.mark.parametrize(
    "secret_key",
    [
        "api_key",
        "API_KEY",
        "open_meteo_apiKey",
        "auth_token",
        "bearer_Token",
        "user_password",
        "PASSWORD",
        "client_secret",
        "SECRET",
        "auth_header",
        "user_credential",
        "private_key",
    ],
)
def test_trip_state_rejects_secret_keys_in_known_fields(secret_key: str) -> None:
    """TripState strictly rejects secret-bearing keys in known_fields."""
    with pytest.raises(ValueError, match="rejects forbidden secret-like key"):
        create_fresh_trip_state(
            user_message="Travel with secret",
            initial_known_fields={secret_key: "super_secret_value_123"},
        )


def test_trip_state_accepts_valid_safe_known_fields() -> None:
    """TripState safely accepts non-sensitive travel fields in known_fields."""
    safe_fields = {
        "origin": "London",
        "destination": "Paris",
        "start_date": "2026-06-01",
        "end_date": "2026-06-05",
        "party_size": 2,
        "pace": "balanced",
        "budget_amount": 1500.0,
        "currency": "EUR",
        "interests": ["culture", "food"],
    }
    state = create_fresh_trip_state(
        user_message="Safe trip prompt",
        initial_known_fields=safe_fields,
    )
    assert state.known_fields["destination"] == "Paris"
    assert state.known_fields["party_size"] == 2


# ==============================================================================
# 8. JSON Serialization & Deserialization Tests
# ==============================================================================


def test_trip_state_json_round_trip() -> None:
    """Complete TripState serializes to JSON and reconstructs losslessly."""
    TripRequest.set_test_today(date(2026, 5, 1))

    trip_req = TripRequest(
        origin="Berlin",
        destination="Munich",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 3),
        party_size=1,
        budget_amount=Decimal("300.00"),
        currency="EUR",
        pace=PacePreference.BALANCED,
    )

    itinerary = Itinerary(
        summary="3-day cultural tour of Munich",
        days=[
            ItineraryDay(
                day_number=1,
                date=date(2026, 6, 1),
                items=[
                    ItineraryItem(
                        title="Marienplatz Exploration",
                        time_of_day=TimeOfDay.MORNING,
                        description="Explore central historic square.",
                    )
                ],
            )
        ],
    )

    trip_resp = TripResponse(
        id=uuid4(),
        request=trip_req,
        itinerary=itinerary,
        weather=None,
        sources=[],
        warnings=["Sample warning"],
        created_at=datetime.now(UTC),
    )

    tool_call = ToolCall(tool_name="geocode_tool", arguments={"query": "Munich"})
    tool_res = ToolResult(
        tool_name="geocode_tool",
        status=ToolStatus.OK,
        data={"name": "Munich", "lat": 48.1351},
        data_origin="mock",
        latency_ms=45.0,
    )

    state = TripState(
        request_id="req-test-999",
        user_message="Take me to Munich",
        known_fields={"destination": "Munich"},
        trip_request=trip_req,
        missing_fields=[],
        contradictions=[],
        clarification_question=None,
        intent=Intent.ITINERARY_PLANNING,
        low_budget=False,
        planned_tool_calls=[tool_call],
        tool_results=[tool_res],
        itinerary_draft=itinerary,
        validation_issues=[],
        repair_attempts=1,
        step_count=3,
        status=RunStatus.COMPLETED,
        final_response=trip_resp,
        warnings=["Sample warning"],
    )

    # Serialize to JSON dict
    state_json = state.model_dump(mode="json")
    assert state_json["request_id"] == "req-test-999"
    assert state_json["status"] == "completed"
    assert state_json["intent"] == "itinerary_planning"

    # Deserialize back into TripState
    restored = TripState.model_validate(state_json)
    assert restored.request_id == state.request_id
    assert restored.user_message == state.user_message
    assert restored.trip_request is not None
    assert restored.trip_request.destination == "Munich"
    assert restored.itinerary_draft is not None
    assert restored.itinerary_draft.summary == "3-day cultural tour of Munich"
    assert len(restored.tool_results) == 1
    assert restored.tool_results[0].tool_name == "geocode_tool"
    assert restored.final_response is not None
    assert restored.final_response.id == trip_resp.id
