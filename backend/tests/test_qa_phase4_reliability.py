"""Independent QA Reliability Verification Suite for Phase 4.

Authored under TASK 14 by the QA Engineer:
1. Property verification of provider error sequences terminating within budget.
2. Auth failures (401/403) abort retries immediately (exactly 1 attempt).
3. Adversarial injection of huge payloads (>100KB) and malformed structures.
4. In-memory upgrade and rendering validation of real stored v1 itinerary rows.
5. Invariant verification: critical issues never reach COMPLETED.
6. Planted secrets in headers, queries, bodies, messages never reach logs.
"""

import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.agent.gateway import ScriptedGateway
from app.agent.graph import run_workflow
from app.agent.nodes import sanitize_url
from app.agent.state import Intent, RunStatus, TripState, create_fresh_trip_state
from app.agent.tools.contracts import ToolResult, ToolStatus
from app.agent.validation import (
    ValidationSeverity,
    validate_itinerary,
)
from app.core.logging import EventCapture
from app.core.retry import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_TOTAL_BUDGET_SECONDS,
    RetryPolicy,
    call_with_retry,
)
from app.providers.errors import (
    ErrorCode,
    ProviderError,
    classify_http_error,
    sanitize_safe_message,
)
from app.schemas.itinerary_v2 import (
    ActivityLocation,
    CostStatus,
    DurationBasis,
    DurationEstimate,
    ItineraryActivityV2,
    ItineraryDayV2,
    ItineraryV2,
    upgrade_itinerary_v1_to_v2,
)
from app.schemas.provider import Provenance, SourceInfo
from app.schemas.trip import PacePreference, TripRequest

V1_FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "itinerary" / "itinerary_v1_sample.json"
)


# ==============================================================================
# Deterministic Doubles
# ==============================================================================


class FakeClock:
    """Monotonic fake clock that records simulated sleep intervals without delay."""

    def __init__(self, initial_time: float = 0.0) -> None:
        self.current_time = initial_time
        self.sleep_calls: list[float] = []

    def clock(self) -> float:
        return self.current_time

    async def sleep(self, duration: float) -> None:
        self.sleep_calls.append(duration)
        self.current_time += duration


@pytest.fixture(autouse=True)
def setup_reference_date() -> None:
    """Freeze reference date for TripRequest models across QA tests."""
    ref_date = date(2027, 5, 1)
    TripRequest.set_test_today(ref_date)
    yield
    TripRequest.set_test_today(None)


def make_qa_source(provider: str = "TestProvider") -> SourceInfo:
    return SourceInfo(
        provider=provider,
        url=f"https://api.{provider.lower()}.org/v1",
        attribution=f"{provider} QA Harness",
        fetched_at=datetime(2027, 5, 1, 12, 0, 0, tzinfo=UTC),
        data_origin="mock",
    )


def make_qa_activity(
    act_id: str = "qa_act_1",
    title: str = "Museum Visit",
) -> ItineraryActivityV2:
    return ItineraryActivityV2(
        id=act_id,
        title=title,
        description=f"Detailed sightseeing for {title}.",
        time_of_day="morning",
        interest_tags=["culture"],
        location=ActivityLocation(
            name="City Museum", latitude=48.137, longitude=11.575
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


# ==============================================================================
# 1. Property-Style Error Sequences & Budget Bounding
# ==============================================================================


@pytest.mark.parametrize(
    "error_sequence",
    [
        # All timeouts
        [
            ProviderError(
                "Timeout 1",
                code=ErrorCode.TIMEOUT,
                provider="P",
                retryable=True,
            ),
            ProviderError(
                "Timeout 2",
                code=ErrorCode.TIMEOUT,
                provider="P",
                retryable=True,
            ),
            ProviderError(
                "Timeout 3",
                code=ErrorCode.TIMEOUT,
                provider="P",
                retryable=True,
            ),
        ],
        # Mixed retryable: 502 then timeout then 503
        [
            classify_http_error(502, provider="P"),
            ProviderError(
                "Read timeout",
                code=ErrorCode.TIMEOUT,
                provider="P",
                retryable=True,
            ),
            classify_http_error(503, provider="P"),
        ],
        # Infinite errors sequence (should be truncated by max_retries = 2)
        [
            ProviderError(
                f"Err {i}",
                code=ErrorCode.TIMEOUT,
                provider="P",
                retryable=True,
            )
            for i in range(10)
        ],
    ],
)
def test_property_provider_error_sequences_terminate_within_budget(
    error_sequence: list[Exception],
) -> None:
    """Any sequence of provider errors terminates within retries and budget."""
    fake = FakeClock()
    call_index = 0

    async def _failing_op() -> str:
        nonlocal call_index
        err = (
            error_sequence[call_index]
            if call_index < len(error_sequence)
            else error_sequence[-1]
        )
        call_index += 1
        raise err

    policy = RetryPolicy(
        max_retries=DEFAULT_MAX_RETRIES,
        base_delay_seconds=0.5,
        backoff_factor=2.0,
        max_delay_seconds=4.0,
        total_budget_seconds=DEFAULT_TOTAL_BUDGET_SECONDS,
    )

    with pytest.raises(ProviderError) as exc_info:
        asyncio.run(
            call_with_retry(
                _failing_op,
                policy=policy,
                sleep=fake.sleep,
                clock=fake.clock,
            )
        )

    # Invariant 1: Total attempts cannot exceed max_retries + 1 (3 attempts)
    assert call_index <= DEFAULT_MAX_RETRIES + 1
    # Invariant 2: Total simulated sleep time cannot exceed total_budget_seconds (8.0s)
    assert fake.current_time <= DEFAULT_TOTAL_BUDGET_SECONDS
    # Invariant 3: Clean error surfaced
    assert exc_info.value.code in (
        ErrorCode.TIMEOUT,
        ErrorCode.UNKNOWN_FAILURE,
    )


# ==============================================================================
# 2. Auth Failures Always Exactly 1 Attempt
# ==============================================================================


@pytest.mark.parametrize(
    "auth_error",
    [
        classify_http_error(401, provider="OpenRouteService"),
        classify_http_error(403, provider="OpenRouteService"),
        ProviderError(
            "Forbidden",
            code=ErrorCode.AUTHENTICATION_FAILED,
            provider="AuthTest",
            retryable=False,
            http_status=403,
        ),
    ],
)
def test_auth_errors_always_exactly_one_attempt_in_retry(
    auth_error: ProviderError,
) -> None:
    """Authentication errors (401/403) must never be retried; exactly 1 attempt."""
    fake = FakeClock()
    calls = 0

    async def _auth_failing_call() -> str:
        nonlocal calls
        calls += 1
        raise auth_error

    policy = RetryPolicy(max_retries=3, total_budget_seconds=10.0)

    with pytest.raises(ProviderError) as exc_info:
        asyncio.run(
            call_with_retry(
                _auth_failing_call,
                policy=policy,
                sleep=fake.sleep,
                clock=fake.clock,
            )
        )

    assert calls == 1
    assert fake.sleep_calls == []
    assert fake.current_time == 0.0
    assert exc_info.value.code == ErrorCode.AUTHENTICATION_FAILED
    assert exc_info.value.retryable is False


def test_auth_failure_in_workflow_executes_exactly_once() -> None:
    """Workflow executing a 401 tool invokes the tool once and preserves partial."""
    route_calls = 0

    def mock_geocode(args: dict[str, Any]) -> ToolResult:
        return ToolResult(
            tool_name="geocode_destination",
            status=ToolStatus.OK,
            data=[{"name": "Munich", "latitude": 48.137, "longitude": 11.575}],
            data_origin="mock",
        )

    def mock_route_401(args: dict[str, Any]) -> ToolResult:
        nonlocal route_calls
        route_calls += 1
        return ToolResult(
            tool_name="get_route_context",
            status=ToolStatus.ERROR,
            error_code=ErrorCode.AUTHENTICATION_FAILED.value,
            safe_message="OpenRouteService authentication failed (401).",
            attempts=1,
            data_origin="none",
        )

    state = create_fresh_trip_state(
        user_message="Directions from Marienplatz to English Garden in Munich",
        initial_known_fields={
            "destination": "Munich",
            "route_from": "Marienplatz",
            "route_to": "English Garden",
        },
        intent=Intent.ROUTE_PLANNING,
    )

    final_state = run_workflow(
        state,
        tools={
            "geocode_destination": mock_geocode,
            "get_route_context": mock_route_401,
        },
    )

    assert route_calls == 1
    assert final_state.status == RunStatus.PARTIAL
    assert any("authentication error" in w.lower() for w in final_state.warnings)


# ==============================================================================
# 3. Adversarial Huge and Corrupted Payloads
# ==============================================================================


def test_fake_tool_huge_payload_handled_safely() -> None:
    """Tool returning a massive 200KB payload does not crash workflow."""
    massive_text = "A" * 200_000

    def mock_huge_geocode(args: dict[str, Any]) -> ToolResult:
        return ToolResult(
            tool_name="geocode_destination",
            status=ToolStatus.OK,
            data=[
                {
                    "name": "Munich",
                    "latitude": 48.137,
                    "longitude": 11.575,
                    "extra_blob": massive_text,
                }
            ],
            data_origin="mock",
        )

    state = create_fresh_trip_state(
        user_message="Trip to Munich from 2027-06-01 to 2027-06-03 for 1 traveler",
        initial_known_fields={
            "origin": "Berlin",
            "destination": "Munich",
            "start_date": "2027-06-01",
            "end_date": "2027-06-03",
            "party_size": 1,
        },
        intent=Intent.ITINERARY_PLANNING,
    )

    final_state = run_workflow(state, tools={"geocode_destination": mock_huge_geocode})

    # Completes safely without unhandled MemoryError or crash
    assert final_state.status in (RunStatus.COMPLETED, RunStatus.PARTIAL)
    assert final_state.itinerary_draft is not None


def test_fake_tool_corrupted_coordinates_handled_safely() -> None:
    """Tool returning non-numeric coordinates is trapped by validation."""

    def mock_corrupt_geocode(args: dict[str, Any]) -> ToolResult:
        return ToolResult(
            tool_name="geocode_destination",
            status=ToolStatus.OK,
            data=[
                {
                    "name": "CorruptCity",
                    "latitude": "not-a-float",
                    "longitude": None,
                }
            ],
            data_origin="mock",
        )

    state = create_fresh_trip_state(
        user_message="Route from Place A to Place B in Munich",
        initial_known_fields={
            "destination": "Munich",
            "route_from": "Place A",
            "route_to": "Place B",
        },
        intent=Intent.ROUTE_PLANNING,
    )

    mock_tools = {
        "geocode_destination": mock_corrupt_geocode,
        "get_route_context": lambda args: ToolResult(
            tool_name="get_route_context",
            status=ToolStatus.OK,
            data={"distance_km": 1.5, "duration_minutes": 20.0},
            data_origin="mock",
        ),
    }

    final_state = run_workflow(state, tools=mock_tools)

    # Must degrade safely to partial without unhandled Python exception
    assert final_state.status == RunStatus.PARTIAL
    assert any(
        "could not be resolved" in w.lower()
        or "skipped" in w.lower()
        or "error" in w.lower()
        or "unavailable" in w.lower()
        for w in final_state.warnings
    )


# ==============================================================================
# 4. v1 Stored Itinerary In-Memory Upgrade & Rendering
# ==============================================================================


def test_stored_v1_itinerary_upgrades_to_v2_cleanly() -> None:
    """Stored Itinerary v1 row is non-destructively upgraded to schema v2."""
    assert V1_FIXTURE_PATH.exists(), f"Missing v1 fixture: {V1_FIXTURE_PATH}"

    with open(V1_FIXTURE_PATH, encoding="utf-8") as f:
        v1_data = json.load(f)

    # 1. Parse via upgrader
    upgraded = upgrade_itinerary_v1_to_v2(v1_data)
    assert isinstance(upgraded, ItineraryV2)
    assert upgraded.schema_version == 2
    assert len(upgraded.days) == len(v1_data["days"])

    # 2. Activity-level inspection
    day_1 = upgraded.days[0]
    assert len(day_1.activities) > 0
    act_1 = day_1.activities[0]

    assert act_1.id.startswith("day_1_act_")
    assert act_1.duration_estimate is not None
    assert act_1.duration_estimate.basis == DurationBasis.HEURISTIC
    assert act_1.provenance in (
        Provenance.RETRIEVED,
        Provenance.GENERATED_SUGGESTION,
    )
    assert act_1.cost_status in (CostStatus.UNKNOWN, CostStatus.ESTIMATE)

    # 3. Re-validation via deterministic validation engine with matching tool results
    om_src = SourceInfo(
        provider="Open-Meteo",
        url="https://api.open-meteo.com/v1/forecast",
        attribution="Weather data by Open-Meteo.com",
        fetched_at=datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC),
        data_origin="mock",
    )
    mock_weather_res = ToolResult(
        tool_name="get_weather",
        status=ToolStatus.OK,
        data={"summary": "Sample weather"},
        source=om_src,
        data_origin="mock",
    )
    issues = validate_itinerary(upgraded, tool_results=[mock_weather_res])
    critical_issues = [i for i in issues if i.severity == ValidationSeverity.CRITICAL]
    # An upgraded valid v1 itinerary should contain zero critical issues
    assert len(critical_issues) == 0

    # 4. JSON serialization round-trip
    dumped_json = upgraded.model_dump_json()
    reparsed = ItineraryV2.model_validate_json(dumped_json)
    assert reparsed.schema_version == 2
    assert len(reparsed.days) == len(upgraded.days)


# ==============================================================================
# 5. Critical Issues Can Never Reach COMPLETED
# ==============================================================================


@pytest.mark.parametrize(
    "corrupt_kind",
    [
        "duplicate_activities",
        "date_mismatch",
        "banned_booking_language",
    ],
)
def test_itinerary_with_critical_issues_never_reaches_completed(
    corrupt_kind: str,
) -> None:
    """An itinerary carrying critical issues can never reach COMPLETED."""
    start = date(2027, 6, 1)

    if corrupt_kind == "duplicate_activities":
        # 4 identical activities on same day -> critical duplicate
        acts = [
            make_qa_activity("dup_1", "Duplicate Walk"),
            make_qa_activity("dup_2", "Duplicate Walk"),
            make_qa_activity("dup_3", "Duplicate Walk"),
            make_qa_activity("dup_4", "Duplicate Walk"),
        ]
        days = [
            ItineraryDayV2(
                day_number=1,
                date=start,
                activities=acts,
                uncertainty_notes=[],
            )
        ]
    elif corrupt_kind == "date_mismatch":
        # Date doesn't match sequence
        acts = [make_qa_activity("act_1", "City Tour")]
        days = [
            ItineraryDayV2(
                day_number=1,
                date=date(2027, 8, 1),  # Mismatched from start_date
                activities=acts,
                uncertainty_notes=[],
            )
        ]
    else:
        # Banned booking claims in summary
        acts = [make_qa_activity("act_1", "City Tour")]
        days = [
            ItineraryDayV2(
                day_number=1,
                date=start,
                activities=acts,
                uncertainty_notes=[],
            )
        ]

    summary = (
        "Your flight and hotel are booked and reserved!"
        if corrupt_kind == "banned_booking_language"
        else "Test trip"
    )

    draft = ItineraryV2(
        schema_version=2,
        summary=summary,
        sources=[],
        warnings=[],
        days=days,
    )

    req = TripRequest(
        origin="Berlin",
        destination="Munich",
        start_date=start,
        end_date=start + timedelta(days=len(days) - 1),
        party_size=1,
        interests=["culture"],
        pace=PacePreference.BALANCED,
    )

    state = TripState(
        request_id="qa_crit_check",
        user_message="Plan trip",
        intent=Intent.ITINERARY_PLANNING,
        known_fields={
            "origin": "Berlin",
            "destination": "Munich",
            "start_date": str(start),
            "end_date": str(start + timedelta(days=len(days) - 1)),
            "party_size": 1,
        },
        trip_request=req,
        itinerary_draft=draft,
    )

    # Run workflow through repair
    final_state = run_workflow(state, gateway=ScriptedGateway())

    # Strict invariant: MUST NOT be COMPLETED
    assert final_state.status != RunStatus.COMPLETED
    assert final_state.status in (RunStatus.PARTIAL, RunStatus.FAILED)


# ==============================================================================
# 6. Planted Secrets Never Reach Logs
# ==============================================================================


def test_planted_secrets_in_headers_urls_bodies_never_reach_logs() -> None:
    """Planted secret tokens across headers, URLs, args never reach logs."""
    planted_secrets = [
        "sk-ant-api03-abcdef12345678901234567890",
        "AKIAIOSFODNN7EXAMPLE",
        "ghp_1234567890abcdefghijklmnopqrstuvwxyz",
        "top_secret_api_key_value_987654321",
    ]

    dirty_url = (
        "https://api.openrouteservice.org/v2/directions/foot-walking"
        f"?api_key={planted_secrets[3]}&user_id=123"
    )
    cleaned_url = sanitize_url(dirty_url)
    assert planted_secrets[3] not in cleaned_url

    dirty_message = (
        f"Directions using key {planted_secrets[0]} and token={planted_secrets[2]}"
    )
    sanitized_msg = sanitize_safe_message(dirty_message)
    assert planted_secrets[0] not in sanitized_msg
    assert planted_secrets[2] not in sanitized_msg

    # 1. Verify TripState boundary guard rejects secret-like field names
    with pytest.raises(ValueError):
        create_fresh_trip_state(
            user_message="Trip to Munich",
            initial_known_fields={"api_key": planted_secrets[0]},
        )

    # 2. Verify EventCapture scrubbing of user message and tool safe_message
    with EventCapture() as cap:
        state = create_fresh_trip_state(
            user_message=(
                f"Directions with auth Bearer {planted_secrets[1]} "
                f"to Munich from 2027-06-01 to 2027-06-03"
            ),
            initial_known_fields={"destination": "Munich"},
            intent=Intent.ROUTE_PLANNING,
        )

        def mock_tool(args: dict[str, Any]) -> ToolResult:
            return ToolResult(
                tool_name="geocode_destination",
                status=ToolStatus.OK,
                data=[{"name": "Munich", "lat": 48.1, "lon": 11.5}],
                safe_message=f"Fetched with {planted_secrets[0]}",
                data_origin="mock",
            )

        run_workflow(state, tools={"geocode_destination": mock_tool})

    # Assert no secret appears in any emitted event payload
    serialized_events = json.dumps(cap.events)
    for secret in planted_secrets:
        assert secret not in serialized_events, (
            f"Leak detected in structured logs: {secret}"
        )
