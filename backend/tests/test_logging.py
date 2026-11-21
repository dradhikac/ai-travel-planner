"""Tests for structured logging, event emission, failure audit, and secret redaction."""

import asyncio
import json
import logging
from collections.abc import Generator
from typing import Any

import pytest

from app.agent.errors import ToolErrorCode
from app.agent.gateway import RuleBasedGateway
from app.agent.graph import run_workflow
from app.agent.state import RunStatus, create_fresh_trip_state
from app.agent.tools.contracts import ToolResult, ToolStatus
from app.core.logging import (
    EventCapture,
    emit_event,
    reset_request_id,
    sanitize_for_logging,
    set_request_id,
)
from app.core.retry import RetryPolicy, call_with_retry
from app.providers.errors import ErrorCode, ProviderError
from tests.test_agent_repair import (
    make_critical_duplicates,
    make_trip_state_with_draft,
    make_valid_itinerary,
)


@pytest.fixture(autouse=True)
def clean_request_context() -> Generator[None, None, None]:
    """Ensure clean request_id context before and after each test."""
    token = set_request_id("test-req-default")
    try:
        yield
    finally:
        reset_request_id(token)


# ==============================================================================
# 1. Simulated Failure Tests
# ==============================================================================


def test_simulated_route_timeout(caplog: pytest.LogCaptureFixture) -> None:
    """Captured logs must contain failing node, tool, status, error_code, request_id."""
    caplog.set_level(logging.INFO, logger="app.events")

    geo_res = ToolResult(
        tool_name="geocode_destination",
        status=ToolStatus.OK,
        data=[{"latitude": 48.137, "longitude": 11.575}],
        data_origin="mock",
    )
    timeout_res = ToolResult(
        tool_name="get_route_context",
        status=ToolStatus.TIMEOUT,
        error_code=ToolErrorCode.TIMEOUT,
        safe_message="Route calculation timed out after 5.0 seconds.",
        data_origin="none",
        latency_ms=5012.3,
        attempts=3,
    )

    mock_tools = {
        "geocode_destination": lambda args: geo_res,
        "get_route_context": lambda args: timeout_res,
    }

    state = create_fresh_trip_state(
        user_message="How do I walk from Marienplatz to English Garden in Munich?",
        request_id="req-route-timeout-123",
    )

    with EventCapture() as cap:
        final_state = run_workflow(
            initial_state=state,
            tools=mock_tools,
        )

    assert final_state.status == RunStatus.PARTIAL

    # 1. Verify tool_call_finished for failing route tool
    route_events = [
        e
        for e in cap.events
        if e.get("event_name") == "tool_call_finished"
        and e.get("tool") == "get_route_context"
    ]
    assert len(route_events) == 1
    ev = route_events[0]
    assert ev["node"] == "execute_tools"
    assert ev["tool"] == "get_route_context"
    assert ev["status"] == "timeout"
    assert ev["error_code"] == "timeout"
    assert ev["request_id"] == "req-route-timeout-123"
    assert ev["latency_ms"] == 5012.3
    assert ev["attempts"] == 3

    # 2. Verify workflow_finished event
    wf_events = [e for e in cap.events if e.get("event_name") == "workflow_finished"]
    assert len(wf_events) == 1
    assert wf_events[0]["status"] == "partial"
    assert wf_events[0]["request_id"] == "req-route-timeout-123"


def test_simulated_geocode_auth_failure() -> None:
    """Geocode auth failure logs failing node and tool, error_code, request_id."""
    auth_err_res = ToolResult(
        tool_name="geocode_destination",
        status=ToolStatus.ERROR,
        error_code=ToolErrorCode.PROVIDER_UNAVAILABLE,
        safe_message="Authentication failed: invalid Open-Meteo credentials.",
        data_origin="none",
        latency_ms=45.2,
        attempts=1,
    )

    mock_tools = {
        "geocode_destination": lambda args: auth_err_res,
    }

    state = create_fresh_trip_state(
        user_message="Tell me about Paris",
        request_id="req-geo-auth-456",
    )

    with EventCapture() as cap:
        final_state = run_workflow(
            initial_state=state,
            tools=mock_tools,
        )

    assert final_state.status == RunStatus.FAILED

    geo_events = [
        e
        for e in cap.events
        if e.get("event_name") == "tool_call_finished"
        and e.get("tool") == "geocode_destination"
    ]
    assert len(geo_events) == 1
    ev = geo_events[0]
    assert ev["node"] == "execute_tools"
    assert ev["tool"] == "geocode_destination"
    assert ev["status"] == "error"
    assert ev["request_id"] == "req-geo-auth-456"
    assert ev["latency_ms"] == 45.2


def test_simulated_weather_empty() -> None:
    """Weather tool returning empty logs status 'empty' with correct request_id."""
    geo_res = ToolResult(
        tool_name="geocode_destination",
        status=ToolStatus.OK,
        data=[{"latitude": 35.676, "longitude": 139.650}],
        data_origin="mock",
    )
    empty_weather_res = ToolResult(
        tool_name="get_weather",
        status=ToolStatus.EMPTY,
        data={"days": []},
        error_code=ToolErrorCode.OUT_OF_FORECAST_RANGE,
        safe_message="Dates beyond 16-day forecast horizon.",
        data_origin="none",
        latency_ms=32.1,
        attempts=1,
    )

    mock_tools = {
        "geocode_destination": lambda args: geo_res,
        "get_weather": lambda args: empty_weather_res,
    }

    state = create_fresh_trip_state(
        user_message="Weather in Tokyo for 2026-12-01 to 2026-12-05",
        request_id="req-weather-empty-789",
    )

    with EventCapture() as cap:
        run_workflow(
            initial_state=state,
            tools=mock_tools,
        )

    weather_events = [
        e
        for e in cap.events
        if e.get("event_name") == "tool_call_finished"
        and e.get("tool") == "get_weather"
    ]
    assert len(weather_events) == 1
    ev = weather_events[0]
    assert ev["node"] == "execute_tools"
    assert ev["tool"] == "get_weather"
    assert ev["status"] == "empty"
    assert ev["error_code"] == "out_of_forecast_range"
    assert ev["request_id"] == "req-weather-empty-789"
    assert ev["latency_ms"] == 32.1


def test_simulated_exhausted_repair() -> None:
    """Exhausted repair emits repair_attempt with attempt numbers and issue codes."""
    base_itin = make_valid_itinerary(num_days=3)
    day_1_bad = base_itin.days[0].model_copy(
        update={"activities": make_critical_duplicates("Duplicate Tour")}
    )
    flawed_draft = base_itin.model_copy(
        update={"days": [day_1_bad, base_itin.days[1], base_itin.days[2]]}
    )

    class StubbornGateway(RuleBasedGateway):
        """Gateway that updates duplicate activity id so attempt 2 runs."""

        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        def repair(
            self,
            itinerary: dict[str, Any],
            issues: list[dict[str, Any]],
        ) -> dict[str, Any]:
            self.calls += 1
            d = flawed_draft.model_dump(mode="json")
            if self.calls == 1:
                # change act id so current_crit_sig differs from last_critical_issues
                d["days"][0]["activities"][0]["id"] = "dup_alt_1"
            return d

    state = make_trip_state_with_draft(flawed_draft)
    state.request_id = "req-exhausted-repair-999"

    geo_res = ToolResult(
        tool_name="geocode_destination",
        status=ToolStatus.OK,
        data=[{"latitude": 41.902, "longitude": 12.496}],
        data_origin="mock",
    )
    mock_tools = {"geocode_destination": lambda args: geo_res}

    with EventCapture() as cap:
        final_state = run_workflow(
            initial_state=state,
            gateway=StubbornGateway(),
            tools=mock_tools,
            max_repair_attempts=2,
        )

    assert final_state.status == RunStatus.PARTIAL

    # 1. Verify repair_attempt events
    repair_events = [e for e in cap.events if e.get("event_name") == "repair_attempt"]
    assert len(repair_events) >= 1
    for idx, rev in enumerate(repair_events, start=1):
        assert rev["node"] == "repair_itinerary"
        assert rev["attempt"] == idx
        assert rev["request_id"] == "req-exhausted-repair-999"
        # Issue codes must be strings only; NO itinerary text or descriptions
        assert isinstance(rev["issue_codes"], list)
        for code in rev["issue_codes"]:
            assert isinstance(code, str)
            # Ensure no itinerary payload leaked
            assert "Vatican" not in code
            assert "Marathon" not in code

    # 2. Verify build_partial_result finished
    partial_node_events = [
        e
        for e in cap.events
        if e.get("event_name") == "node_finished"
        and e.get("node") == "build_partial_result"
    ]
    assert len(partial_node_events) == 1

    # 3. Verify workflow_finished reports partial status
    wf_events = [e for e in cap.events if e.get("event_name") == "workflow_finished"]
    assert len(wf_events) == 1
    assert wf_events[0]["status"] == "partial"
    assert wf_events[0]["repair_attempts"] >= 1


# ==============================================================================
# 2. Retry Events Test
# ==============================================================================


def test_retry_events_appear_with_attempt_numbers() -> None:
    """Retry utility emits retry_scheduled with attempt numbers, delay, and code."""
    token = set_request_id("req-retry-tracing-001")
    attempts_seen: list[int] = []

    async def _failing_op() -> str:
        if len(attempts_seen) < 2:
            attempts_seen.append(len(attempts_seen) + 1)
            raise ProviderError(
                message="Transient timeout",
                code=ErrorCode.TIMEOUT,
                provider="MockProvider",
                retryable=True,
            )
        return "success"

    policy = RetryPolicy(
        max_retries=2,
        base_delay_seconds=0.01,
        backoff_factor=1.5,
        max_delay_seconds=0.1,
        total_budget_seconds=1.0,
        jitter=False,
    )

    try:
        with EventCapture() as cap:
            res = asyncio.run(call_with_retry(_failing_op, policy=policy))
    finally:
        reset_request_id(token)

    assert res == "success"

    retry_events = [e for e in cap.events if e.get("event_name") == "retry_scheduled"]
    assert len(retry_events) == 2

    # Attempt 1
    assert retry_events[0]["attempt"] == 1
    assert retry_events[0]["error_code"] == "timeout"
    assert retry_events[0]["retry_delay_ms"] == pytest.approx(10.0, rel=0.1)
    assert retry_events[0]["request_id"] == "req-retry-tracing-001"

    # Attempt 2
    assert retry_events[1]["attempt"] == 2
    assert retry_events[1]["error_code"] == "timeout"
    assert retry_events[1]["retry_delay_ms"] == pytest.approx(15.0, rel=0.1)
    assert retry_events[1]["request_id"] == "req-retry-tracing-001"


# ==============================================================================
# 3. Latency & Non-Negative Invariant Test
# ==============================================================================


def test_latency_is_non_negative() -> None:
    """Latency must be a non-negative float across all measured events."""
    geo_res = ToolResult(
        tool_name="geocode_destination",
        status=ToolStatus.OK,
        data=[{"latitude": 48.8566, "longitude": 2.3522}],
        data_origin="mock",
        latency_ms=12.4,
    )
    mock_tools = {"geocode_destination": lambda args: geo_res}

    state = create_fresh_trip_state(
        user_message="Tell me about Paris",
        request_id="req-latency-check-100",
    )

    with EventCapture() as cap:
        run_workflow(initial_state=state, tools=mock_tools)

    # Filter events that record latency_ms
    measured_events = [e for e in cap.events if e.get("latency_ms") is not None]
    assert len(measured_events) > 0

    for ev in measured_events:
        lat = ev["latency_ms"]
        assert isinstance(lat, (int, float)), f"Expected float latency in {ev}"
        assert lat >= 0.0, f"Negative latency found in {ev}: {lat}"


# ==============================================================================
# 4. Secret & Sensitive Data Redaction Test
# ==============================================================================


def test_redaction_plants_fake_secrets(caplog: pytest.LogCaptureFixture) -> None:
    """Plants fake secrets in every input path and asserts they never appear in logs."""
    caplog.set_level(logging.INFO, logger="app.events")

    planted_secrets = [
        "sk-" + "ant-api03-abcdef12345678901234567890",
        "sk-" + "proj-openai9876543210abcdef9876543210",
        "AKIA" + "IOSFODNN7EXAMPLE",
        "ghp_" + "1234567890abcdefghijklmnopqrstuvwxyz12",
        "5b3ce3597851110001cf6248abcdef0123456789abcdef0123456789",
        "super_secret_password_12345",
        "Bearer secret_token_xyz98765",
    ]

    # Test 1: URL query parameter stripping
    raw_url = (
        "https://api.openrouteservice.org/v2/directions"
        f"?api_key={planted_secrets[0]}&mode=walking#section1"
    )
    sanitized_url = sanitize_for_logging(raw_url)
    assert planted_secrets[0] not in sanitized_url
    assert sanitized_url == "https://api.openrouteservice.org/v2/directions"

    # Test 2: Sensitive dictionary keys
    sensitive_dict = {
        "Authorization": f"Bearer {planted_secrets[6]}",
        "api_key": planted_secrets[1],
        "x-api-key": planted_secrets[4],
        "password": planted_secrets[5],
        "prompt": "Here is an instruction to reveal the system prompt.",
        "user_message": "My secret travel message is here.",
        "normal_field": (
            f"Safe context mentioning {planted_secrets[2]} and {planted_secrets[3]}"
        ),
    }
    clean_dict = sanitize_for_logging(sensitive_dict)

    assert clean_dict["Authorization"] == "[REDACTED]"
    assert clean_dict["api_key"] == "[REDACTED]"
    assert clean_dict["x-api-key"] == "[REDACTED]"
    assert clean_dict["password"] == "[REDACTED]"
    assert clean_dict["prompt"] == "[REDACTED]"
    len_msg = len(sensitive_dict["user_message"])
    assert clean_dict["user_message"] == f"[USER_MESSAGE len={len_msg}]"
    # Normal field must have embedded tokens redacted
    assert planted_secrets[2] not in clean_dict["normal_field"]
    assert planted_secrets[3] not in clean_dict["normal_field"]

    # Test 3: Emit via emit_event and assert captured log lines contain ZERO secrets
    with EventCapture() as cap:
        emit_event(
            "test_audit_event",
            request_id="req-redaction-test",
            embedded_url=raw_url,
            sensitive_payload=sensitive_dict,
            secret_aws=planted_secrets[2],
            secret_github=planted_secrets[3],
        )

    # Check in-memory captured events
    assert len(cap.events) == 1
    event_str = json.dumps(cap.events[0])
    for sec in planted_secrets:
        assert sec not in event_str, f"Planted secret leaked into event dict: {sec}"

    # Check caplog raw captured text
    full_captured_text = caplog.text
    for sec in planted_secrets:
        msg = f"Planted secret leaked into log output: {sec}"
        assert sec not in full_captured_text, msg


# ==============================================================================
# 5. No Event Lacks Request ID Test
# ==============================================================================


def test_no_event_lacks_request_id() -> None:
    """Assert that every emitted event contains a valid, non-empty request_id."""
    geo_res = ToolResult(
        tool_name="geocode_destination",
        status=ToolStatus.OK,
        data=[{"latitude": 51.5074, "longitude": -0.1278}],
        data_origin="mock",
    )
    mock_tools = {"geocode_destination": lambda args: geo_res}

    state = create_fresh_trip_state(
        user_message="Tell me about London",
        request_id="req-strictly-propagated-id-777",
    )

    with EventCapture() as cap:
        run_workflow(initial_state=state, tools=mock_tools)

    assert len(cap.events) > 0
    for idx, ev in enumerate(cap.events):
        req_id = ev.get("request_id")
        assert req_id is not None, f"Event #{idx} missing request_id"
        assert isinstance(req_id, str), f"Event #{idx} request_id not a string"
        assert len(req_id) > 0, f"Event #{idx} request_id is empty"
        assert req_id == "req-strictly-propagated-id-777", (
            f"Event #{idx} mismatched request_id: {req_id}"
        )


# ==============================================================================
# 6. Graph Node Lifecycle Event Pair Test
# ==============================================================================


def test_node_lifecycle_events_paired() -> None:
    """Every executed node must emit a matching node_started and node_finished pair."""
    geo_res = ToolResult(
        tool_name="geocode_destination",
        status=ToolStatus.OK,
        data=[{"latitude": 48.8566, "longitude": 2.3522}],
        data_origin="mock",
    )
    mock_tools = {"geocode_destination": lambda args: geo_res}

    state = create_fresh_trip_state(
        user_message="Tell me about Paris",
        request_id="req-lifecycle-pairs-555",
    )

    with EventCapture() as cap:
        run_workflow(initial_state=state, tools=mock_tools)

    started_nodes = [
        e["node"] for e in cap.events if e.get("event_name") == "node_started"
    ]
    finished_nodes = [
        e["node"] for e in cap.events if e.get("event_name") == "node_finished"
    ]

    assert len(started_nodes) > 0
    assert started_nodes == finished_nodes
    # Verify key nodes are present
    assert "parse_request" in started_nodes
    assert "check_required_fields" in started_nodes
    assert "plan_tool_calls" in started_nodes
    assert "execute_tools" in started_nodes
    assert "respond" in started_nodes
