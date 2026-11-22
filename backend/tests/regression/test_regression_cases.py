"""Automated data-driven regression test suite running 100% offline.

Governed by Phase 4 Task 13 reliability contracts:
- Consumes declarative JSON test cases from `backend/tests/regression/cases/*.json`.
- Parametrized by case ID with strict offline deterministic execution.
- Employs injected fake tool behaviors with zero network sockets or sleeps.
- Verifies expected workflow status, issue/warning codes, and tool call counts.
- Reports clear category summaries and explicit case failure diagnostics.
"""

import json
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from app.agent.errors import ToolErrorCode
from app.agent.gateway import ModelGateway, RuleBasedGateway, ScriptedGateway
from app.agent.graph import run_workflow
from app.agent.state import Intent, TripState, create_fresh_trip_state
from app.agent.tools.contracts import ToolResult, ToolStatus
from app.schemas.itinerary_v2 import (
    ActivityLocation,
    CostStatus,
    DurationBasis,
    DurationEstimate,
    ItineraryActivityV2,
    ItineraryDayV2,
    ItineraryV2,
)
from app.schemas.provider import Provenance, SourceInfo, WeatherDay, WeatherSummary
from app.schemas.trip import PacePreference, TripRequest

# ==============================================================================
# 1. Case Discovery & Loading
# ==============================================================================

CASES_DIR = Path(__file__).parent / "cases"


def load_regression_cases() -> list[dict[str, Any]]:
    """Discover and parse all JSON regression case definitions."""
    cases: list[dict[str, Any]] = []
    case_files = sorted(CASES_DIR.glob("*.json"))
    for file_path in case_files:
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                cases.extend(data)
            elif isinstance(data, dict):
                cases.append(data)
    return cases


ALL_REGRESSION_CASES = load_regression_cases()


# ==============================================================================
# 2. Standard Fixtures & Helpers
# ==============================================================================


@pytest.fixture(autouse=True)
def setup_reference_date() -> None:
    """Freeze reference date for TripRequest models across regression tests."""
    TripRequest.set_test_today(date(2026, 5, 1))


def get_mock_source_info(provider: str, origin: str = "mock") -> SourceInfo:
    """Generate canonical source metadata for mock responses."""
    return SourceInfo(
        provider=provider,
        url=f"https://api.{provider.lower()}.org/v1/mock",
        attribution=f"{provider} Mock Service",
        fetched_at=datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC),
        data_origin=origin,
    )


def make_valid_activity(
    act_id: str = "act_1",
    title: str = "City Center Tour",
) -> ItineraryActivityV2:
    """Helper creating a valid activity conformant to Itinerary Schema v2."""
    return ItineraryActivityV2(
        id=act_id,
        title=title,
        description=f"Explore attractions during {title}.",
        time_of_day="morning",
        interest_tags=["culture"],
        location=ActivityLocation(
            name="Munich Plaza", latitude=48.1351, longitude=11.5820
        ),
        duration_estimate=DurationEstimate(
            min_minutes=60, max_minutes=120, basis=DurationBasis.HEURISTIC
        ),
        source_refs=[],
        provenance=Provenance.GENERATED_SUGGESTION,
        cost_status=CostStatus.UNKNOWN,
        cost_note=None,
        uncertainty_notes=[],
    )


def make_critical_duplicate_activities(
    title: str = "Duplicate Tour",
) -> list[ItineraryActivityV2]:
    """Helper producing 4 duplicate activities triggering CRITICAL severity."""
    return [make_valid_activity(act_id=f"dup_{i}", title=title) for i in range(1, 5)]


def make_invalid_itinerary_draft(num_days: int = 3) -> ItineraryV2:
    """Construct an itinerary draft with critical duplicate activities on Day 1."""
    start = date(2026, 12, 10)
    days: list[ItineraryDayV2] = []
    for day_idx in range(1, num_days + 1):
        d_date = start + timedelta(days=day_idx - 1)
        if day_idx == 1:
            acts = make_critical_duplicate_activities("Duplicate Walking Tour")
        else:
            acts = [
                make_valid_activity(
                    act_id=f"day_{day_idx}_act_{a}",
                    title=f"Day {day_idx} Activity {a}",
                )
                for a in range(1, 3)
            ]
        days.append(
            ItineraryDayV2(
                day_number=day_idx,
                date=d_date,
                activities=acts,
                uncertainty_notes=[],
            )
        )
    return ItineraryV2(
        schema_version=2,
        summary="A trip draft requiring repair.",
        sources=[],
        warnings=[],
        days=days,
    )


def make_trip_state_from_draft(draft: ItineraryV2) -> TripState:
    """Construct TripState with a pre-populated draft and valid request."""
    req = TripRequest(
        origin="Berlin",
        destination="Munich",
        start_date=date(2026, 12, 10),
        end_date=date(2026, 12, 12),
        party_size=2,
        interests=["culture"],
        pace=PacePreference.BALANCED,
        budget_amount=None,
        currency=None,
    )
    return TripState(
        request_id=f"reg_{uuid4().hex[:10]}",
        user_message=(
            "Plan trip to Munich from 2026-12-10 to 2026-12-12 for 2 travelers"
        ),
        intent=Intent.ITINERARY_PLANNING,
        known_fields={
            "origin": "Berlin",
            "destination": "Munich",
            "start_date": "2026-12-10",
            "end_date": "2026-12-12",
            "party_size": 2,
            "interests": ["culture"],
            "pace": "balanced",
        },
        trip_request=req,
        itinerary_draft=draft,
    )


# ==============================================================================
# 3. Dynamic Mock Tool Factory
# ==============================================================================


def build_mock_tools(
    fake_behaviours: dict[str, Any],
    call_tracker: dict[str, list[dict[str, Any]]],
) -> dict[str, Callable[[dict[str, Any]], ToolResult]]:
    """Build mock tools dispatched per declarative case behavior."""
    om_src = get_mock_source_info("Open-Meteo")
    ors_src = get_mock_source_info("OpenRouteService")

    # Call sequences for recovery simulation
    weather_seq_index = 0

    def mock_geocode(args: dict[str, Any]) -> ToolResult:
        call_tracker["geocode_destination"].append(args)
        query = str(args.get("query", "")).lower()

        geo_config = fake_behaviours.get("geocode_destination", {})
        status = geo_config.get("status", "ok")
        latency = float(geo_config.get("latency_ms", 100.0))

        # Check for simulated failures
        if status == "timeout":
            return ToolResult(
                tool_name="geocode_destination",
                status=ToolStatus.TIMEOUT,
                error_code=ToolErrorCode.TIMEOUT,
                safe_message="Geocoding timed out.",
                attempts=geo_config.get("attempts", 3),
                latency_ms=latency,
                data_origin="none",
            )
        elif status == "auth_failure":
            return ToolResult(
                tool_name="geocode_destination",
                status=ToolStatus.ERROR,
                error_code=ToolErrorCode.AUTH_FAILURE,
                safe_message="Geocoding unauthorized.",
                attempts=1,
                latency_ms=latency,
                data_origin="none",
            )
        elif status == "empty" or "nonexistent" in query:
            return ToolResult(
                tool_name="geocode_destination",
                status=ToolStatus.OK,
                data=[],
                latency_ms=latency,
                source=om_src,
                data_origin="mock",
            )
        elif status == "endpoint_empty" and "nowherestation" in query:
            return ToolResult(
                tool_name="geocode_destination",
                status=ToolStatus.OK,
                data=[],
                latency_ms=latency,
                source=om_src,
                data_origin="mock",
            )

        # Candidate coordinates by landmark/city
        if "marienplatz" in query:
            cand = {
                "name": "Marienplatz",
                "country": "Germany",
                "admin_region": "Munich",
                "latitude": 48.1374,
                "longitude": 11.5755,
                "timezone": "Europe/Berlin",
            }
        elif "english garden" in query:
            cand = {
                "name": "English Garden",
                "country": "Germany",
                "admin_region": "Munich",
                "latitude": 48.1583,
                "longitude": 11.6033,
                "timezone": "Europe/Berlin",
            }
        elif "paris" in query:
            cand = {
                "name": "Paris",
                "country": "France",
                "admin_region": "Île-de-France",
                "latitude": 48.8566,
                "longitude": 2.3522,
                "timezone": "Europe/Paris",
            }
        elif "tokyo" in query:
            cand = {
                "name": "Tokyo",
                "country": "Japan",
                "admin_region": "Tokyo",
                "latitude": 35.6762,
                "longitude": 139.6503,
                "timezone": "Asia/Tokyo",
            }
        elif "rome" in query:
            cand = {
                "name": "Rome",
                "country": "Italy",
                "admin_region": "Lazio",
                "latitude": 41.9028,
                "longitude": 12.4964,
                "timezone": "Europe/Rome",
            }
        elif "crete" in query or "greece" in query:
            cand = {
                "name": "Crete",
                "country": "Greece",
                "admin_region": "Crete",
                "latitude": 35.2401,
                "longitude": 24.8093,
                "timezone": "Europe/Athens",
            }
        elif "berlin" in query:
            cand = {
                "name": "Berlin",
                "country": "Germany",
                "admin_region": "Berlin",
                "latitude": 52.5200,
                "longitude": 13.4050,
                "timezone": "Europe/Berlin",
            }
        else:
            cand = {
                "name": "Munich",
                "country": "Germany",
                "admin_region": "Bavaria",
                "latitude": 48.1351,
                "longitude": 11.5820,
                "timezone": "Europe/Berlin",
            }

        return ToolResult(
            tool_name="geocode_destination",
            status=ToolStatus.OK,
            data=[cand],
            latency_ms=latency,
            source=om_src,
            data_origin="mock",
        )

    def mock_weather(args: dict[str, Any]) -> ToolResult:
        nonlocal weather_seq_index
        call_tracker["get_weather"].append(args)

        weather_config = fake_behaviours.get("get_weather") or fake_behaviours.get(
            "weather_forecast", {}
        )
        latency = float(weather_config.get("latency_ms", 120.0))
        status_mode = weather_config.get("status", "ok")

        if status_mode == "recovery_on_retry":
            # Simulate adapter executing call_with_retry internally
            # (attempt 1 timeout, attempt 2 success)
            summary = WeatherSummary(
                location="Destination Location",
                days=[
                    WeatherDay(
                        date=date(2027, 6, 1) + timedelta(days=i),
                        temp_min_c=12.0 + i,
                        temp_max_c=22.0 + i,
                        precipitation_probability_pct=10,
                        precipitation_sum_mm=0.0,
                        weather_code=1,
                        condition_description="Clear sky",
                    )
                    for i in range(3)
                ],
                units={"temperature": "celsius", "precipitation": "mm"},
                source=om_src,
                fetched_at=om_src.fetched_at,
                data_origin="mock",
            )
            return ToolResult(
                tool_name="get_weather",
                status=ToolStatus.OK,
                data=summary.model_dump(mode="json"),
                latency_ms=latency,
                attempts=2,
                source=om_src,
                data_origin="mock",
            )

        if status_mode == "timeout":
            return ToolResult(
                tool_name="get_weather",
                status=ToolStatus.TIMEOUT,
                error_code=ToolErrorCode.TIMEOUT,
                safe_message="Weather provider timed out.",
                attempts=weather_config.get("attempts", 3),
                latency_ms=latency,
                data_origin="none",
            )
        elif status_mode == "auth_failure":
            return ToolResult(
                tool_name="get_weather",
                status=ToolStatus.ERROR,
                error_code="authentication_failed",
                safe_message="Weather provider authorization failed.",
                attempts=1,
                latency_ms=latency,
                data_origin="none",
            )
        elif status_mode == "rate_limited":
            return ToolResult(
                tool_name="get_weather",
                status=ToolStatus.RATE_LIMITED,
                error_code=ToolErrorCode.RATE_LIMITED,
                safe_message="Weather provider rate limit exceeded (429).",
                attempts=1,
                latency_ms=latency,
                data_origin="none",
            )

        # OK payload
        summary = WeatherSummary(
            location="Destination Location",
            days=[
                WeatherDay(
                    date=date(2027, 6, 1) + timedelta(days=i),
                    temp_min_c=12.0 + i,
                    temp_max_c=22.0 + i,
                    precipitation_probability_pct=10,
                    precipitation_sum_mm=0.0,
                    weather_code=1,
                    condition_description="Clear sky",
                )
                for i in range(3)
            ],
            units={"temperature": "celsius", "precipitation": "mm"},
            source=om_src,
            fetched_at=om_src.fetched_at,
            data_origin="mock",
        )
        return ToolResult(
            tool_name="get_weather",
            status=ToolStatus.OK,
            data=summary.model_dump(mode="json"),
            latency_ms=latency,
            source=om_src,
            data_origin="mock",
        )

    def mock_route(args: dict[str, Any]) -> ToolResult:
        call_tracker["get_route_context"].append(args)

        route_config = fake_behaviours.get("get_route_context", {})
        status = route_config.get("status", "ok")
        latency = float(route_config.get("latency_ms", 180.0))

        if status == "timeout":
            return ToolResult(
                tool_name="get_route_context",
                status=ToolStatus.TIMEOUT,
                error_code=ToolErrorCode.TIMEOUT,
                safe_message="OpenRouteService directions timed out after 4.0s.",
                attempts=route_config.get("attempts", 2),
                latency_ms=latency,
                data_origin="none",
            )
        elif status == "auth_failure":
            return ToolResult(
                tool_name="get_route_context",
                status=ToolStatus.ERROR,
                error_code="authentication_failed",
                safe_message="OpenRouteService authentication failed (401).",
                attempts=1,
                latency_ms=latency,
                data_origin="none",
            )
        elif status == "rate_limited":
            return ToolResult(
                tool_name="get_route_context",
                status=ToolStatus.RATE_LIMITED,
                error_code=ToolErrorCode.RATE_LIMITED,
                safe_message="OpenRouteService rate limit exceeded (429).",
                attempts=1,
                latency_ms=latency,
                data_origin="none",
            )
        elif status == "empty":
            return ToolResult(
                tool_name="get_route_context",
                status=ToolStatus.EMPTY,
                error_code=None,
                safe_message="No route found between locations.",
                attempts=1,
                latency_ms=latency,
                data_origin="none",
            )

        return ToolResult(
            tool_name="get_route_context",
            status=ToolStatus.OK,
            data={
                "distance_km": 2.7,
                "duration_minutes": 35.0,
                "mode": args.get("mode", "walking"),
                "origin": [
                    args.get("origin_lat", 48.1374),
                    args.get("origin_lon", 11.5755),
                ],
                "destination": [
                    args.get("dest_lat", 48.1583),
                    args.get("dest_lon", 11.6033),
                ],
            },
            latency_ms=latency,
            source=ors_src,
            data_origin="mock",
        )

    return {
        "geocode_destination": mock_geocode,
        "get_weather": mock_weather,
        "get_route_context": mock_route,
    }


# ==============================================================================
# 4. Parametrized Test Runner
# ==============================================================================


@pytest.mark.regression
@pytest.mark.parametrize(
    "case",
    ALL_REGRESSION_CASES,
    ids=[c["id"] for c in ALL_REGRESSION_CASES],
)
def test_regression_case(case: dict[str, Any]) -> None:
    """Execute a single declarative regression case and verify contract assertions."""
    case_id = case["id"]
    category = case["category"]
    input_data = case["input"]
    fake_behaviours = case.get("fake_tool_behaviours", {})
    expected_status_str = case["expected_status"]
    expected_warnings = case.get("expected_warning_codes", [])
    expected_counts = case.get("expected_tool_call_counts", {})
    expected_repair_attempts = case.get("expected_repair_attempts")

    call_tracker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    mock_tools = build_mock_tools(fake_behaviours, call_tracker)

    # 1. State preparation
    if case.get("initial_draft") == "critical_duplicate":
        draft = make_invalid_itinerary_draft(num_days=3)
        state = make_trip_state_from_draft(draft)
    else:
        user_msg = input_data.get("user_message", "Trip planning request")
        known = dict(input_data.get("known_fields", {}))
        intent_str = input_data.get("intent")
        intent = Intent(intent_str) if intent_str else Intent.ITINERARY_PLANNING
        state = create_fresh_trip_state(
            user_message=user_msg,
            initial_known_fields=known,
            intent=intent,
        )

    # 2. Gateway preparation
    gateway_override = case.get("gateway_override")
    gateway: ModelGateway
    if gateway_override == "repair_success":
        gateway = ScriptedGateway()
    elif gateway_override == "repair_exhausted":

        class PersistentBadGateway(RuleBasedGateway):
            """Gateway returning distinct invalid drafts to exhaust attempts."""

            def __init__(self) -> None:
                super().__init__()
                self.calls = 0

            def repair(
                self, itinerary: dict[str, Any], issues: list[dict[str, Any]]
            ) -> dict[str, Any]:
                self.calls += 1
                base_itin = make_invalid_itinerary_draft(num_days=3)
                if self.calls == 1:
                    # Attempt 1: Day 2 has duplicates, Day 1 clean
                    day_2_bad = base_itin.days[1].model_copy(
                        update={
                            "activities": make_critical_duplicate_activities(
                                "Dup Day 2"
                            )
                        }
                    )
                    return base_itin.model_copy(
                        update={
                            "days": [base_itin.days[0], day_2_bad, base_itin.days[2]]
                        }
                    ).model_dump(mode="json")
                else:
                    # Attempt 2: Day 3 has duplicates
                    day_3_bad = base_itin.days[2].model_copy(
                        update={
                            "activities": make_critical_duplicate_activities(
                                "Dup Day 3"
                            )
                        }
                    )
                    return base_itin.model_copy(
                        update={
                            "days": [base_itin.days[0], base_itin.days[1], day_3_bad]
                        }
                    ).model_dump(mode="json")

        gateway = PersistentBadGateway()
    elif gateway_override == "no_progress":

        class IdenticalBadGateway(RuleBasedGateway):
            """Gateway returning identical invalid output to halt repair."""

            def repair(
                self, itinerary: dict[str, Any], issues: list[dict[str, Any]]
            ) -> dict[str, Any]:
                return itinerary

        gateway = IdenticalBadGateway()
    else:
        gateway = RuleBasedGateway()

    # 3. Execution
    final_state = run_workflow(state, gateway=gateway, tools=mock_tools)

    # 4. Status Assertion
    actual_status = final_state.status.value
    assert actual_status == expected_status_str, (
        f"[{case_id}] ({category}) Expected status '{expected_status_str}', "
        f"but got '{actual_status}'. Warnings: {final_state.warnings}, "
        f"Contradictions: {final_state.contradictions}, "
        f"Validation issues: {final_state.validation_issues}"
    )

    # 5. Warning / Issue Codes Assertion
    all_notices = (
        final_state.warnings
        + final_state.contradictions
        + final_state.validation_issues
        + (
            [final_state.clarification_question]
            if final_state.clarification_question
            else []
        )
    )
    for expected_code in expected_warnings:
        matched = any(expected_code.lower() in str(n).lower() for n in all_notices)
        assert matched, (
            f"[{case_id}] ({category}) Expected notice substring '{expected_code}' "
            f"not found in notices: {all_notices}"
        )

    # 6. Tool Call Counts Assertion
    for tool_name, expected_count in expected_counts.items():
        actual_count = len(call_tracker[tool_name])
        assert actual_count == expected_count, (
            f"[{case_id}] ({category}) Tool '{tool_name}' expected {expected_count} "
            f"calls, but recorded {actual_count}."
        )

    # 7. Repair Attempts Assertion (if specified)
    if expected_repair_attempts is not None:
        assert final_state.repair_attempts == expected_repair_attempts, (
            f"[{case_id}] ({category}) Expected {expected_repair_attempts} repair "
            f"attempts, but recorded {final_state.repair_attempts}."
        )
