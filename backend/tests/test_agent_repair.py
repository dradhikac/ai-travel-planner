"""Unit and regression tests for bounded repair and safe partial results.

Verifies:
- test_repair_succeeds_in_one_attempt: 1 critical duplicate resolved in 1 attempt.
- test_repair_succeeds_in_two_attempts: 2 script attempts resolving issues.
- test_repair_always_invalid_reaches_max_then_partial: 2 attempts, then PARTIAL.
- test_repair_identical_issue_set_early_stop: identical issues halt early.
- test_repair_garbage_non_json_output: non-JSON output caught, degrades safely.
- test_repair_schema_invalid_output: schema-invalid dict caught safely.
- test_repair_adds_booking_claim_rejected: booking claims scrubbed/pruned.
- test_repair_huge_output_rejected: candidate > 250,000 chars rejected.
- test_partial_result_contents: safe partial drops invalid items, renumbers.
- test_completed_with_critical_issues_impossible: respond final guard blocks.
- test_repair_payload_isolation: gateway receives only minimal itinerary.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from app.agent.gateway import ScriptedGateway
from app.agent.graph import run_workflow
from app.agent.nodes import repair_itinerary, respond
from app.agent.partial import FALLBACK_NOTE, build_safe_partial_result
from app.agent.state import Intent, RunStatus, TripState
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


@pytest.fixture
def mock_tools(sample_source: SourceInfo) -> dict[str, Any]:
    class MockTool:
        def __init__(self, result: ToolResult) -> None:
            self.result = result

        def invoke(self, args: dict[str, Any]) -> ToolResult:
            return self.result

    geo_result = ToolResult(
        tool_name="geocode_destination",
        status=ToolStatus.OK,
        data=[
            {
                "name": "Munich",
                "country": "Germany",
                "admin_region": "Bavaria",
                "latitude": 48.1351,
                "longitude": 11.5820,
                "timezone": "Europe/Berlin",
                "source": sample_source.model_dump(mode="json"),
                "fetched_at": sample_source.fetched_at.isoformat(),
            }
        ],
        source=sample_source,
        fetched_at=sample_source.fetched_at,
        data_origin="mock",
    )

    weather_summary = WeatherSummary(
        location="Munich, Germany",
        days=[
            WeatherDay(
                date=date(2026, 12, 10),
                temp_min_c=0.0,
                temp_max_c=5.0,
                precipitation_probability_pct=20,
                precipitation_sum_mm=0.5,
                weather_code=3,
                condition_description="Overcast",
            )
        ],
        units={"temperature": "celsius", "precipitation": "mm"},
        source=sample_source,
        fetched_at=sample_source.fetched_at,
        data_origin="mock",
    )

    weather_result = ToolResult(
        tool_name="get_weather",
        status=ToolStatus.OK,
        data=weather_summary.model_dump(mode="json"),
        source=sample_source,
        fetched_at=sample_source.fetched_at,
        data_origin="mock",
    )

    return {
        "geocode_destination": MockTool(geo_result),
        "get_weather": MockTool(weather_result),
    }


def make_valid_activity(
    act_id: str = "day_1_act_1",
    title: str = "Historic Walking Tour",
    interest_tags: list[str] | None = None,
    provenance: Provenance = Provenance.GENERATED_SUGGESTION,
    cost_status: CostStatus = CostStatus.UNKNOWN,
) -> ItineraryActivityV2:
    return ItineraryActivityV2(
        id=act_id,
        title=title,
        description=f"Explore sights during {title}.",
        time_of_day="morning",
        interest_tags=interest_tags or ["culture"],
        location=ActivityLocation(
            name="Munich Plaza", latitude=48.1351, longitude=11.5820
        ),
        duration_estimate=DurationEstimate(
            min_minutes=60, max_minutes=120, basis=DurationBasis.HEURISTIC
        ),
        source_refs=[],
        provenance=provenance,
        cost_status=cost_status,
        cost_note=None,
        uncertainty_notes=[],
    )


def make_critical_duplicates(
    title: str = "Duplicate Tour",
) -> list[ItineraryActivityV2]:
    """Helper generating 4 duplicate activities triggering CRITICAL severity."""
    return [make_valid_activity(act_id=f"dup_{i}", title=title) for i in range(1, 5)]


def make_valid_itinerary(
    start_date: date = date(2026, 12, 10),
    num_days: int = 3,
    activities_per_day: int = 2,
) -> ItineraryV2:
    days: list[ItineraryDayV2] = []
    for day_idx in range(1, num_days + 1):
        day_date = start_date + timedelta(days=day_idx - 1)
        acts = [
            make_valid_activity(
                act_id=f"day_{day_idx}_act_{a_idx}",
                title=f"Day {day_idx} Activity {a_idx} in Munich",
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
        summary="A delightful exploration of Munich.",
        sources=[],
        warnings=[],
        days=days,
    )


def make_sample_request(
    start_date: date = date(2026, 12, 10),
    end_date: date = date(2026, 12, 12),
) -> TripRequest:
    return TripRequest(
        origin="Berlin",
        destination="Munich",
        start_date=start_date,
        end_date=end_date,
        party_size=2,
        interests=["culture"],
        pace=PacePreference.BALANCED,
        budget_amount=None,
        currency=None,
    )


def make_trip_state_with_draft(
    draft: ItineraryV2,
    request: TripRequest | None = None,
) -> TripState:
    req = request or make_sample_request()
    return TripState(
        request_id=str(uuid4()),
        user_message=(
            "Plan trip to Munich from 2026-12-10 to 2026-12-12 for 2 travelers"
        ),
        intent=Intent.ITINERARY_PLANNING,
        known_fields={
            "origin": req.origin,
            "destination": req.destination,
            "start_date": req.start_date.isoformat(),
            "end_date": req.end_date.isoformat(),
            "party_size": req.party_size,
            "interests": req.interests,
            "pace": req.pace.value,
        },
        trip_request=req,
        itinerary_draft=draft,
    )


# ==============================================================================
# 1. Successful Repairs: 1 Attempt and 2 Attempts
# ==============================================================================


def test_repair_succeeds_in_one_attempt(mock_tools: dict[str, Any]) -> None:
    """Draft with 4 duplicate activities triggers CRITICAL issue; repairs in 1 loop."""
    base_itin = make_valid_itinerary(num_days=3)
    day_1 = base_itin.days[0].model_copy(
        update={"activities": make_critical_duplicates("Duplicate Walking Tour")}
    )
    invalid_draft = base_itin.model_copy(
        update={"days": [day_1, base_itin.days[1], base_itin.days[2]]}
    )

    state = make_trip_state_with_draft(invalid_draft)
    gateway = ScriptedGateway()  # Uses RuleBasedGateway().repair by default

    final_state = run_workflow(state, gateway=gateway, tools=mock_tools)

    assert final_state.status == RunStatus.COMPLETED
    assert final_state.repair_attempts == 1
    assert final_state.final_response is not None
    assert final_state.final_response.metadata["repair_attempts"] == 1
    assert final_state.final_response.metadata["run_status"] == "completed"


def test_repair_succeeds_in_two_attempts(mock_tools: dict[str, Any]) -> None:
    """Scripted 2-attempt repair: attempt 1 fixes D1, attempt 2 clears all."""
    base_itin = make_valid_itinerary(num_days=3)
    day_1_bad = base_itin.days[0].model_copy(
        update={"activities": make_critical_duplicates("Day 1 Tour")}
    )
    initial_draft = base_itin.model_copy(
        update={"days": [day_1_bad, base_itin.days[1], base_itin.days[2]]}
    )

    # Attempt 1 repair candidate: fixes Day 1, but Day 2 now has 4 duplicates
    day_1_fixed = make_valid_activity(act_id="d1_clean", title="Clean Museum Tour")
    d1_clean = base_itin.days[0].model_copy(update={"activities": [day_1_fixed]})
    day_2_bad = base_itin.days[1].model_copy(
        update={"activities": make_critical_duplicates("Day 2 Duplicate")}
    )
    attempt_1_candidate = base_itin.model_copy(
        update={"days": [d1_clean, day_2_bad, base_itin.days[2]]}
    ).model_dump(mode="json")

    # Attempt 2 repair candidate: completely clean
    clean_itin = make_valid_itinerary(num_days=3).model_dump(mode="json")

    gateway = ScriptedGateway(scripted_repair=[attempt_1_candidate, clean_itin])
    state = make_trip_state_with_draft(initial_draft)

    final_state = run_workflow(state, gateway=gateway, tools=mock_tools)

    assert final_state.status == RunStatus.COMPLETED
    assert final_state.repair_attempts == 2
    assert final_state.final_response is not None
    assert final_state.final_response.metadata["repair_attempts"] == 2
    assert final_state.final_response.metadata["run_status"] == "completed"


# ==============================================================================
# 2. Exhaustion and Early Stopping
# ==============================================================================


def test_repair_always_invalid_reaches_max_then_partial(
    mock_tools: dict[str, Any],
) -> None:
    """When candidates stay invalid with differing signatures, caps at 2 -> PARTIAL."""
    base_itin = make_valid_itinerary(num_days=3)
    day_1_bad = base_itin.days[0].model_copy(
        update={"activities": make_critical_duplicates("Dup Day 1")}
    )
    initial_draft = base_itin.model_copy(
        update={"days": [day_1_bad, base_itin.days[1], base_itin.days[2]]}
    )

    # Attempt 1 candidate: Day 2 has 4 duplicates
    day_2_bad = base_itin.days[1].model_copy(
        update={"activities": make_critical_duplicates("Dup Day 2")}
    )
    candidate_1 = base_itin.model_copy(
        update={"days": [base_itin.days[0], day_2_bad, base_itin.days[2]]}
    ).model_dump(mode="json")

    # Attempt 2 candidate: Day 3 has 4 duplicates
    day_3_bad = base_itin.days[2].model_copy(
        update={"activities": make_critical_duplicates("Dup Day 3")}
    )
    candidate_2 = base_itin.model_copy(
        update={"days": [base_itin.days[0], base_itin.days[1], day_3_bad]}
    ).model_dump(mode="json")

    gateway = ScriptedGateway(scripted_repair=[candidate_1, candidate_2])
    state = make_trip_state_with_draft(initial_draft)

    final_state = run_workflow(state, gateway=gateway, tools=mock_tools)

    assert final_state.status == RunStatus.PARTIAL
    assert final_state.repair_attempts == 2
    assert final_state.final_response is not None
    assert final_state.final_response.metadata["repair_attempts"] == 2
    assert final_state.final_response.metadata["run_status"] == "partial"


def test_repair_identical_issue_set_early_stop(mock_tools: dict[str, Any]) -> None:
    """When attempt 1 yields identical critical issues, repair halts early at 1."""
    base_itin = make_valid_itinerary(num_days=3)
    day_1_bad = base_itin.days[0].model_copy(
        update={"activities": make_critical_duplicates("Stuck Duplicate")}
    )
    initial_draft = base_itin.model_copy(
        update={"days": [day_1_bad, base_itin.days[1], base_itin.days[2]]}
    )

    # Candidate returns exact same invalid draft with identical critical issues
    stuck_candidate = initial_draft.model_dump(mode="json")
    gateway = ScriptedGateway(scripted_repair=stuck_candidate)
    state = make_trip_state_with_draft(initial_draft)

    final_state = run_workflow(state, gateway=gateway, tools=mock_tools)

    # Must stop at 1 attempt (not waste a 2nd attempt) and build safe partial result
    assert final_state.repair_attempts == 1
    assert final_state.status == RunStatus.PARTIAL
    assert final_state.final_response is not None
    assert final_state.final_response.metadata["repair_attempts"] == 1


# ==============================================================================
# 3. Untrusted Gateway Output Guards: Malformed, Huge, Schema-Invalid
# ==============================================================================


def test_repair_garbage_non_json_output(mock_tools: dict[str, Any]) -> None:
    """Gateway returning non-JSON string is caught safely and degrades to partial."""
    base_itin = make_valid_itinerary(num_days=3)
    day_1_bad = base_itin.days[0].model_copy(
        update={"activities": make_critical_duplicates("Bad Duplicate")}
    )
    initial_draft = base_itin.model_copy(
        update={"days": [day_1_bad, base_itin.days[1], base_itin.days[2]]}
    )

    gateway = ScriptedGateway(
        scripted_repair="{invalid json: definitely not valid JSON}"
    )
    state = make_trip_state_with_draft(initial_draft)

    final_state = run_workflow(state, gateway=gateway, tools=mock_tools)

    assert final_state.status == RunStatus.PARTIAL
    assert any("invalid or unparseable" in w for w in final_state.warnings)


def test_repair_schema_invalid_output(mock_tools: dict[str, Any]) -> None:
    """Gateway returning schema-invalid dictionary is safely rejected."""
    base_itin = make_valid_itinerary(num_days=3)
    day_1_bad = base_itin.days[0].model_copy(
        update={"activities": make_critical_duplicates("Bad Duplicate")}
    )
    initial_draft = base_itin.model_copy(
        update={"days": [day_1_bad, base_itin.days[1], base_itin.days[2]]}
    )

    gateway = ScriptedGateway(
        scripted_repair={"days": "this-is-not-a-list-of-days", "summary": "oops"}
    )
    state = make_trip_state_with_draft(initial_draft)

    final_state = run_workflow(state, gateway=gateway, tools=mock_tools)

    assert final_state.status == RunStatus.PARTIAL
    assert any("invalid or unparseable" in w for w in final_state.warnings)


def test_repair_huge_output_rejected(mock_tools: dict[str, Any]) -> None:
    """Candidate output > 250,000 characters is rejected by safety size bound."""
    base_itin = make_valid_itinerary(num_days=3)
    day_1_bad = base_itin.days[0].model_copy(
        update={"activities": make_critical_duplicates("Bad Duplicate")}
    )
    initial_draft = base_itin.model_copy(
        update={"days": [day_1_bad, base_itin.days[1], base_itin.days[2]]}
    )

    oversized_payload = " " * 300_000
    gateway = ScriptedGateway(scripted_repair=oversized_payload)
    state = make_trip_state_with_draft(initial_draft)

    final_state = run_workflow(state, gateway=gateway, tools=mock_tools)

    assert final_state.status == RunStatus.PARTIAL
    assert any("safety size bounds" in w for w in final_state.warnings)


def test_repair_adds_booking_claim_rejected(mock_tools: dict[str, Any]) -> None:
    """Candidate attempting to introduce booking language is rejected and scrubbed."""
    base_itin = make_valid_itinerary(num_days=3)
    day_1_bad = base_itin.days[0].model_copy(
        update={"activities": make_critical_duplicates("Bad Duplicate")}
    )
    initial_draft = base_itin.model_copy(
        update={"days": [day_1_bad, base_itin.days[1], base_itin.days[2]]}
    )

    # Candidate introduces prohibited booking language
    bad_booking_act = make_valid_activity(
        act_id="book_1", title="Hotel reservation confirmed at Munich Grand"
    )
    booking_candidate = base_itin.model_copy(
        update={
            "days": [
                base_itin.days[0].model_copy(update={"activities": [bad_booking_act]}),
                base_itin.days[1],
                base_itin.days[2],
            ]
        }
    ).model_dump(mode="json")

    gateway = ScriptedGateway(scripted_repair=booking_candidate)
    state = make_trip_state_with_draft(initial_draft)

    final_state = run_workflow(state, gateway=gateway, tools=mock_tools)

    # Must NOT be completed
    assert final_state.status != RunStatus.COMPLETED
    # And final itinerary must NOT contain prohibited booking claim
    if (
        final_state.final_response is not None
        and final_state.final_response.itinerary is not None
    ):
        for day in final_state.final_response.itinerary.days:
            for act in day.activities:
                assert "reservation confirmed" not in act.title.lower()


# ==============================================================================
# 4. Safe Partial Result Builder Contents & Invariants
# ==============================================================================


def test_partial_result_contents() -> None:
    """build_safe_partial_result removes bad activities, adds notes, renumbers."""
    base_itin = make_valid_itinerary(num_days=3)
    # Day 1: 1 bad activity with booking language, 1 good activity
    bad_act = make_valid_activity(act_id="bad_1", title="Hotel booking confirmed")
    good_act = make_valid_activity(act_id="good_1", title="Englischer Garten Stroll")
    day_1 = base_itin.days[0].model_copy(update={"activities": [bad_act, good_act]})

    # Day 2: ONLY bad activities (all will be omitted -> triggers free exploration)
    bad_act_2 = make_valid_activity(act_id="bad_2", title="Ticket purchased for Opera")
    day_2 = base_itin.days[1].model_copy(update={"activities": [bad_act_2]})

    draft = base_itin.model_copy(update={"days": [day_1, day_2]})
    req = make_sample_request(
        start_date=date(2026, 12, 10),
        end_date=date(2026, 12, 11),
    )

    partial_itin, status, warnings = build_safe_partial_result(draft, request=req)

    assert partial_itin is not None
    assert status == RunStatus.PARTIAL
    assert len(partial_itin.days) == 2

    # Day 1 should have kept the good activity, omitted bad
    assert len(partial_itin.days[0].activities) == 1
    assert partial_itin.days[0].activities[0].title == "Englischer Garten Stroll"
    assert FALLBACK_NOTE in partial_itin.days[0].uncertainty_notes

    # Day 2 should have inserted fallback exploration activity
    assert len(partial_itin.days[1].activities) == 1
    assert "Exploration" in partial_itin.days[1].activities[0].title
    assert FALLBACK_NOTE in partial_itin.days[1].uncertainty_notes

    # Days renumbered sequentially 1..2
    assert [d.day_number for d in partial_itin.days] == [1, 2]


def test_completed_with_critical_issues_impossible() -> None:
    """respond node final guard blocks COMPLETED on critical validation issues."""
    base_itin = make_valid_itinerary(num_days=3)
    day_1_bad = base_itin.days[0].model_copy(
        update={"activities": make_critical_duplicates("Dup Title")}
    )
    invalid_draft = base_itin.model_copy(
        update={"days": [day_1_bad, base_itin.days[1], base_itin.days[2]]}
    )

    state = make_trip_state_with_draft(invalid_draft)
    # Deliberately try to set status to COMPLETED
    state.status = RunStatus.COMPLETED

    res = respond(state)

    # Must be forced to PARTIAL (or FAILED), NEVER COMPLETED
    assert res["status"] != RunStatus.COMPLETED
    assert res["status"] == RunStatus.PARTIAL
    assert res["final_response"].metadata["run_status"] == "partial"


# ==============================================================================
# 5. Payload Isolation Contract
# ==============================================================================


def test_repair_payload_isolation() -> None:
    """repair_itinerary passes only structured issues and minimal itinerary JSON."""
    base_itin = make_valid_itinerary(num_days=3)
    day_1_bad = base_itin.days[0].model_copy(
        update={"activities": make_critical_duplicates("Dup")}
    )
    draft = base_itin.model_copy(
        update={"days": [day_1_bad, base_itin.days[1], base_itin.days[2]]}
    )

    state = make_trip_state_with_draft(draft)
    state.user_message = "Confidential user request: my travel budget is 500 USD"
    state.tool_results = [
        ToolResult(
            tool_name="dummy_tool",
            status=ToolStatus.OK,
            data={"api_key_leak_test": "SECRET_VALUE_123"},
        )
    ]

    gateway = ScriptedGateway()
    repair_itinerary(state, gateway=gateway)

    assert len(gateway.repair_calls) == 1
    call_args = gateway.repair_calls[0]

    # Verify keys passed
    assert set(call_args.keys()) == {"itinerary", "issues"}

    # Invariants: user_message, request_id, tool_results, secrets are NEVER passed
    assert "user_message" not in call_args
    assert "request_id" not in call_args
    assert "tool_results" not in call_args
    assert "SECRET_VALUE_123" not in str(call_args)
    assert "Confidential user request" not in str(call_args)

    # Verify issue structure: minimal structured fields only
    for issue in call_args["issues"]:
        assert set(issue.keys()) == {
            "code",
            "day_number",
            "activity_id",
            "repair_hint",
            "severity",
        }
