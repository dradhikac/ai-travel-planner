"""Unit and integration tests for multi-tool routing intent and graceful degradation.

Governed by Phase 4 Task 11 reliability contracts:
- Intent classification for route planning inquiries.
- Targeted single clarification when route inputs (destination, from, to) are missing.
- Contradiction detection when route_from == route_to.
- Tool planning order: geocode destination -> geocode endpoints -> get_route_context.
- Weather tool is NOT called for pure route inquiries.
- Expected tool sets and call counts per intent (1, 2, 4, 5).
- Route success -> RunStatus.COMPLETED with coordinate injection and Route Context.
- Route timeout -> RunStatus.PARTIAL with geocoded locations preserved.
- Route auth failure -> RunStatus.PARTIAL with attempts == 1 (no retries).
- Geocode empty -> dependent tools skipped (ToolStatus.SKIPPED with reason).
- Unavailable route tool -> skipped before execution, safe message explains capability.
- MAX_TOOL_CALLS = 5 enforced.
- Destination discovery and weather planning remain completely unchanged.
"""

from datetime import UTC, datetime
from typing import Any

import pytest

from app.agent.errors import ToolErrorCode
from app.agent.gateway import RuleBasedGateway
from app.agent.graph import run_workflow
from app.agent.nodes import is_route_tool_available, plan_tool_calls
from app.agent.state import Intent, RunStatus, TripState, create_fresh_trip_state
from app.agent.tools.contracts import ToolResult, ToolStatus
from app.core.config import Settings
from app.schemas.provider import SourceInfo

# ==============================================================================
# Test Fixtures & Doubles
# ==============================================================================


@pytest.fixture
def ors_source_info() -> SourceInfo:
    """Attribution metadata for OpenRouteService mock provider."""
    return SourceInfo(
        provider="OpenRouteService",
        url="https://api.openrouteservice.org/v2/directions/foot-walking",
        attribution="OpenRouteService Directions API",
        fetched_at=datetime(2026, 11, 1, 12, 0, 0, tzinfo=UTC),
        data_origin="mock",
    )


@pytest.fixture
def om_source_info() -> SourceInfo:
    """Attribution metadata for Open-Meteo geocoding provider."""
    return SourceInfo(
        provider="Open-Meteo",
        url="https://geocoding-api.open-meteo.com/v1/search",
        attribution="Open-Meteo Geocoding API",
        fetched_at=datetime(2026, 11, 1, 12, 0, 0, tzinfo=UTC),
        data_origin="mock",
    )


@pytest.fixture
def mock_geocode_destination(om_source_info: SourceInfo) -> ToolResult:
    """Successful geocode result for Munich destination."""
    return ToolResult(
        tool_name="geocode_destination",
        status=ToolStatus.OK,
        data=[
            {
                "name": "Munich",
                "country": "Germany",
                "admin_region": "Bavaria",
                "latitude": 48.137154,
                "longitude": 11.576124,
                "timezone": "Europe/Berlin",
            }
        ],
        source=om_source_info,
        fetched_at=om_source_info.fetched_at,
        data_origin="mock",
    )


@pytest.fixture
def mock_geocode_marienplatz(om_source_info: SourceInfo) -> ToolResult:
    """Successful geocode result for starting point (Marienplatz)."""
    return ToolResult(
        tool_name="geocode_destination",
        status=ToolStatus.OK,
        data=[
            {
                "name": "Marienplatz",
                "country": "Germany",
                "admin_region": "Munich",
                "latitude": 48.1374,
                "longitude": 11.5755,
                "timezone": "Europe/Berlin",
            }
        ],
        source=om_source_info,
        fetched_at=om_source_info.fetched_at,
        data_origin="mock",
    )


@pytest.fixture
def mock_geocode_english_garden(om_source_info: SourceInfo) -> ToolResult:
    """Successful geocode result for arrival destination (English Garden)."""
    return ToolResult(
        tool_name="geocode_destination",
        status=ToolStatus.OK,
        data=[
            {
                "name": "English Garden",
                "country": "Germany",
                "admin_region": "Munich",
                "latitude": 48.1583,
                "longitude": 11.6033,
                "timezone": "Europe/Berlin",
            }
        ],
        source=om_source_info,
        fetched_at=om_source_info.fetched_at,
        data_origin="mock",
    )


@pytest.fixture
def mock_route_success(ors_source_info: SourceInfo) -> ToolResult:
    """Successful route calculation result."""
    return ToolResult(
        tool_name="get_route_context",
        status=ToolStatus.OK,
        data={
            "distance_km": 2.7,
            "duration_minutes": 35.0,
            "mode": "walking",
            "origin": [48.1374, 11.5755],
            "destination": [48.1583, 11.6033],
        },
        source=ors_source_info,
        fetched_at=ors_source_info.fetched_at,
        data_origin="mock",
    )


def make_mock_tools(
    dest_geo: ToolResult,
    from_geo: ToolResult,
    to_geo: ToolResult,
    route_res: ToolResult | None = None,
) -> dict[str, Any]:
    """Helper to dispatch geocode calls by query string and return configured route."""

    def _geo(args: dict[str, Any]) -> ToolResult:
        query = str(args.get("query", "")).lower()
        if "marienplatz" in query:
            return from_geo
        elif "english garden" in query or "nowhere" in query:
            return to_geo
        return dest_geo

    tools: dict[str, Any] = {"geocode_destination": _geo}
    if route_res is not None:
        tools["get_route_context"] = lambda args: route_res
    return tools


# ==============================================================================
# 1. Intent Classification & Field Extraction Tests
# ==============================================================================


def test_classify_intent_route_planning() -> None:
    """Gateway correctly classifies various route queries as Intent.ROUTE_PLANNING."""
    gw = RuleBasedGateway()

    # Query with 'from X to Y in City'
    fields1 = gw.extract_known_fields(
        "How do I walk from Marienplatz to English Garden in Munich?"
    )
    assert fields1.get("route_from") == "Marienplatz"
    assert fields1.get("route_to") == "English Garden"
    assert fields1.get("destination") == "Munich"
    assert fields1.get("route_mode") == "walking"
    assert "origin" not in fields1  # Must NOT set origin to route_from
    assert (
        gw.classify_intent(
            "How do I walk from Marienplatz to English Garden in Munich?", fields1
        )
        == Intent.ROUTE_PLANNING
    )

    # Query with 'between X and Y'
    fields2 = gw.extract_known_fields("Route between Tokyo Station and Shibuya")
    assert fields2.get("route_from") == "Tokyo Station"
    assert fields2.get("route_to") == "Shibuya"
    assert (
        gw.classify_intent("Route between Tokyo Station and Shibuya", fields2)
        == Intent.ROUTE_PLANNING
    )

    # Query with cycling mode
    fields3 = gw.extract_known_fields("Can I bike from Colosseum to Vatican in Rome?")
    assert fields3.get("route_from") == "Colosseum"
    assert fields3.get("route_to") == "Vatican"
    assert fields3.get("destination") == "Rome"
    assert fields3.get("route_mode") == "cycling"
    assert (
        gw.classify_intent("Can I bike from Colosseum to Vatican in Rome?", fields3)
        == Intent.ROUTE_PLANNING
    )


# ==============================================================================
# 2. Targeted Clarification Tests
# ==============================================================================


def test_clarification_missing_route_endpoints() -> None:
    """Missing route endpoints trigger a single targeted clarification question."""
    # Missing both endpoints
    state1 = create_fresh_trip_state(
        user_message="Directions in Munich",
        intent=Intent.ROUTE_PLANNING,
        initial_known_fields={"destination": "Munich"},
    )
    out1 = run_workflow(state1)
    assert out1.status == RunStatus.NEEDS_CLARIFICATION
    assert "starting location" in out1.clarification_question.lower()
    assert "arrival destination" in out1.clarification_question.lower()

    # Missing starting location
    state2 = create_fresh_trip_state(
        user_message="Can I walk to English Garden in Munich?",
        intent=Intent.ROUTE_PLANNING,
        initial_known_fields={
            "destination": "Munich",
            "route_to": "English Garden",
        },
    )
    out2 = run_workflow(state2)
    assert out2.status == RunStatus.NEEDS_CLARIFICATION
    assert "starting location" in out2.clarification_question.lower()

    # Missing destination city
    state3 = create_fresh_trip_state(
        user_message="Walk from Marienplatz to English Garden",
        intent=Intent.ROUTE_PLANNING,
        initial_known_fields={
            "route_from": "Marienplatz",
            "route_to": "English Garden",
        },
    )
    out3 = run_workflow(state3)
    assert out3.status == RunStatus.NEEDS_CLARIFICATION
    assert "destination city" in out3.clarification_question.lower()


def test_clarification_identical_endpoints_contradiction() -> None:
    """Identical starting and arrival locations trigger contradiction clarification."""
    state = create_fresh_trip_state(
        user_message="Directions from Marienplatz to Marienplatz in Munich",
        intent=Intent.ROUTE_PLANNING,
        initial_known_fields={
            "destination": "Munich",
            "route_from": "Marienplatz",
            "route_to": "Marienplatz",
        },
    )
    out = run_workflow(state)
    assert out.status == RunStatus.NEEDS_CLARIFICATION
    assert (
        "Starting location and arrival destination cannot be identical"
        in out.contradictions
    )


# ==============================================================================
# 3. Tool Sets and Call Counts per Intent
# ==============================================================================


def test_expected_tool_sets_and_call_counts_per_intent() -> None:
    """Verify exact tool sets and call count limits planned per intent."""
    # 1. ROUTE_PLANNING: exactly 4 tools (3 geocodes + 1 route), NO weather
    route_state = create_fresh_trip_state(
        user_message="Directions",
        intent=Intent.ROUTE_PLANNING,
        initial_known_fields={
            "destination": "Munich",
            "route_from": "Marienplatz",
            "route_to": "English Garden",
            "route_mode": "walking",
        },
    )
    plan_res = plan_tool_calls(route_state)
    planned = plan_res["planned_tool_calls"]
    assert len(planned) == 4
    assert planned[0].tool_name == "geocode_destination"
    assert planned[0].arguments["query"] == "Munich"
    assert planned[1].tool_name == "geocode_destination"
    assert planned[1].arguments["query"] == "Marienplatz, Munich"
    assert planned[2].tool_name == "geocode_destination"
    assert planned[2].arguments["query"] == "English Garden, Munich"
    assert planned[3].tool_name == "get_route_context"
    assert planned[3].arguments["mode"] == "walking"
    assert not any(c.tool_name == "get_weather" for c in planned)

    # 2. WEATHER_PLANNING: exactly 2 tools (geocode + weather)
    weather_state = create_fresh_trip_state(
        user_message="Weather in Munich",
        intent=Intent.WEATHER_PLANNING,
        initial_known_fields={
            "destination": "Munich",
            "start_date": "2026-11-01",
            "end_date": "2026-11-03",
        },
    )
    weather_planned = plan_tool_calls(weather_state)["planned_tool_calls"]
    assert len(weather_planned) == 2
    assert [c.tool_name for c in weather_planned] == [
        "geocode_destination",
        "get_weather",
    ]

    # 3. DESTINATION_DISCOVERY: exactly 1 tool (geocode only)
    disc_state = create_fresh_trip_state(
        user_message="Explore Munich",
        intent=Intent.DESTINATION_DISCOVERY,
        initial_known_fields={"destination": "Munich"},
    )
    disc_planned = plan_tool_calls(disc_state)["planned_tool_calls"]
    assert len(disc_planned) == 1
    assert disc_planned[0].tool_name == "geocode_destination"

    # 4. ITINERARY_PLANNING with route pair: up to 5 tools
    itin_state = create_fresh_trip_state(
        user_message="Plan trip to Munich with route",
        intent=Intent.ITINERARY_PLANNING,
        initial_known_fields={
            "destination": "Munich",
            "origin": "Berlin",
            "start_date": "2026-11-01",
            "end_date": "2026-11-03",
            "party_size": 2,
            "route_from": "Marienplatz",
            "route_to": "English Garden",
        },
    )
    itin_planned = plan_tool_calls(itin_state)["planned_tool_calls"]
    assert len(itin_planned) == 5
    assert [c.tool_name for c in itin_planned] == [
        "geocode_destination",
        "get_weather",
        "geocode_destination",
        "geocode_destination",
        "get_route_context",
    ]


# ==============================================================================
# 4. Route Success Workflow & Coordinate Injection
# ==============================================================================


def test_route_success_workflow(
    mock_geocode_destination: ToolResult,
    mock_geocode_marienplatz: ToolResult,
    mock_geocode_english_garden: ToolResult,
    mock_route_success: ToolResult,
) -> None:
    """Route planning resolves coordinates, calculates route, and audits activity."""
    recorded_args: dict[str, Any] = {}

    def _route_tool(args: dict[str, Any]) -> ToolResult:
        recorded_args.update(args)
        return mock_route_success

    tools = make_mock_tools(
        dest_geo=mock_geocode_destination,
        from_geo=mock_geocode_marienplatz,
        to_geo=mock_geocode_english_garden,
        route_res=None,
    )
    tools["get_route_context"] = _route_tool

    state = create_fresh_trip_state(
        user_message="How do I get from Marienplatz to English Garden in Munich?",
        intent=Intent.ROUTE_PLANNING,
        initial_known_fields={
            "destination": "Munich",
            "route_from": "Marienplatz",
            "route_to": "English Garden",
        },
    )

    final_state = run_workflow(state, tools=tools)

    assert final_state.status == RunStatus.COMPLETED

    # Check coordinate propagation from geocoded endpoints
    assert recorded_args["origin_lat"] == pytest.approx(48.1374)
    assert recorded_args["origin_lon"] == pytest.approx(11.5755)
    assert recorded_args["dest_lat"] == pytest.approx(48.1583)
    assert recorded_args["dest_lon"] == pytest.approx(11.6033)
    assert recorded_args["mode"] == "walking"

    # Verify tool results & tool_activity
    assert len(final_state.tool_results) == 4
    route_activity = next(
        (a for a in final_state.tool_activity if a.tool_label == "Route Context"),
        None,
    )
    assert route_activity is not None
    assert route_activity.status == "ok"
    assert "OpenRouteService" in route_activity.source
    assert route_activity.data_origin == "mock"

    # Route summary note appears in warnings
    assert any("Retrieved walking route: 2.7 km" in w for w in final_state.warnings)


# ==============================================================================
# 5. Fault Isolation: Route Timeout -> Partial
# ==============================================================================


def test_route_timeout_yields_partial_with_places_preserved(
    mock_geocode_destination: ToolResult,
    mock_geocode_marienplatz: ToolResult,
    mock_geocode_english_garden: ToolResult,
    mock_route_success: ToolResult,
) -> None:
    """Route timeout yields RunStatus.PARTIAL while preserving resolved places."""
    timeout_result = ToolResult(
        tool_name="get_route_context",
        status=ToolStatus.TIMEOUT,
        error_code=ToolErrorCode.TIMEOUT,
        safe_message="OpenRouteService directions timed out after 4.0s.",
        data_origin="none",
        attempts=2,
    )

    tools = make_mock_tools(
        dest_geo=mock_geocode_destination,
        from_geo=mock_geocode_marienplatz,
        to_geo=mock_geocode_english_garden,
        route_res=timeout_result,
    )

    state = create_fresh_trip_state(
        user_message="How do I get from Marienplatz to English Garden in Munich?",
        intent=Intent.ROUTE_PLANNING,
        initial_known_fields={
            "destination": "Munich",
            "route_from": "Marienplatz",
            "route_to": "English Garden",
        },
    )

    final_state = run_workflow(state, tools=tools)

    assert final_state.status == RunStatus.PARTIAL

    # Places geocodes are preserved
    assert len(final_state.tool_results) == 4
    geo_results = [
        r for r in final_state.tool_results if r.tool_name == "geocode_destination"
    ]
    assert len(geo_results) == 3
    assert all(r.status == ToolStatus.OK for r in geo_results)

    # Route result is recorded with TIMEOUT
    route_res = final_state.tool_results[3]
    assert route_res.status == ToolStatus.TIMEOUT

    # Honest note present in warnings
    assert any(
        "Route calculation timed out. Geocoded locations preserved." in w
        for w in final_state.warnings
    )

    # Activity panel has Route Context marked as timed out
    route_act = next(
        a for a in final_state.tool_activity if a.tool_label == "Route Context"
    )
    assert route_act.status == "timeout"


# ==============================================================================
# 6. Fault Isolation: Route Auth Failure -> Partial (1 attempt)
# ==============================================================================


def test_route_auth_failure_yields_partial_single_attempt(
    mock_geocode_destination: ToolResult,
    mock_geocode_marienplatz: ToolResult,
    mock_geocode_english_garden: ToolResult,
) -> None:
    """Authentication failure yields PARTIAL without retries (attempts == 1)."""
    auth_err_result = ToolResult(
        tool_name="get_route_context",
        status=ToolStatus.ERROR,
        error_code=ToolErrorCode.PROVIDER_UNAVAILABLE,
        safe_message=(
            "OpenRouteService authentication failed: API key missing or invalid."
        ),
        data_origin="none",
        attempts=1,
    )

    tools = make_mock_tools(
        dest_geo=mock_geocode_destination,
        from_geo=mock_geocode_marienplatz,
        to_geo=mock_geocode_english_garden,
        route_res=auth_err_result,
    )

    state = create_fresh_trip_state(
        user_message="Directions from Marienplatz to English Garden in Munich",
        intent=Intent.ROUTE_PLANNING,
        initial_known_fields={
            "destination": "Munich",
            "route_from": "Marienplatz",
            "route_to": "English Garden",
        },
    )

    final_state = run_workflow(state, tools=tools)

    assert final_state.status == RunStatus.PARTIAL
    route_res = next(
        r for r in final_state.tool_results if r.tool_name == "get_route_context"
    )
    assert route_res.status == ToolStatus.ERROR
    assert route_res.attempts == 1  # Strictly 1 attempt, non-retryable
    assert any(
        "Route calculation failed due to provider authentication error." in w
        for w in final_state.warnings
    )


# ==============================================================================
# 7. Dependency Handling: Empty Geocode Skips Dependent Tools
# ==============================================================================


def test_destination_geocode_empty_skips_endpoints_and_route() -> None:
    """When destination geocode is empty, entire workflow fails gracefully."""
    empty_dest = ToolResult(
        tool_name="geocode_destination",
        status=ToolStatus.EMPTY,
        data=[],
        safe_message="No locations found.",
        data_origin="none",
    )

    tools = {
        "geocode_destination": lambda args: empty_dest,
        "get_route_context": lambda args: pytest.fail(
            "Route tool should never be called when destination geocoding fails!"
        ),
    }

    state = create_fresh_trip_state(
        user_message="Directions from Marienplatz to English Garden in UnknownCity",
        intent=Intent.ROUTE_PLANNING,
        initial_known_fields={
            "destination": "UnknownCity",
            "route_from": "Marienplatz",
            "route_to": "English Garden",
        },
    )

    final_state = run_workflow(state, tools=tools)

    assert final_state.status == RunStatus.FAILED
    assert any("Could not find that destination" in w for w in final_state.warnings)


def test_endpoint_geocode_empty_skips_route_tool(
    mock_geocode_destination: ToolResult,
    mock_geocode_marienplatz: ToolResult,
) -> None:
    """When an endpoint geocode returns empty, route tool is skipped with reason."""
    empty_to = ToolResult(
        tool_name="geocode_destination",
        status=ToolStatus.EMPTY,
        data=[],
        safe_message="Location not found.",
        data_origin="none",
    )

    tools = make_mock_tools(
        dest_geo=mock_geocode_destination,
        from_geo=mock_geocode_marienplatz,
        to_geo=empty_to,
        route_res=None,
    )
    # Add dummy route tool that must not be invoked
    tools["get_route_context"] = lambda args: pytest.fail(
        "Route tool must not be called when an endpoint geocode fails!"
    )

    state = create_fresh_trip_state(
        user_message="Directions from Marienplatz to Nowhere in Munich",
        intent=Intent.ROUTE_PLANNING,
        initial_known_fields={
            "destination": "Munich",
            "route_from": "Marienplatz",
            "route_to": "Nowhere",
        },
    )

    final_state = run_workflow(state, tools=tools)

    assert final_state.status == RunStatus.PARTIAL
    skipped_route = next(
        (r for r in final_state.tool_results if r.tool_name == "get_route_context"),
        None,
    )
    assert skipped_route is not None
    assert skipped_route.status == ToolStatus.SKIPPED
    assert "location coordinates could not be resolved" in skipped_route.safe_message


# ==============================================================================
# 8. Unavailable Tools Handling
# ==============================================================================


def test_unavailable_route_tool_skipped_without_provider_failure(
    mock_geocode_destination: ToolResult,
    mock_geocode_marienplatz: ToolResult,
    mock_geocode_english_garden: ToolResult,
) -> None:
    """Unavailable tool is skipped before execution with safe notice."""
    # Test availability helper directly
    live_settings_no_key = Settings(
        ROUTING_PROVIDER_MODE="live",
        OPENROUTESERVICE_API_KEY=None,
    )
    assert not is_route_tool_available(settings=live_settings_no_key)

    tools_without_route = make_mock_tools(
        dest_geo=mock_geocode_destination,
        from_geo=mock_geocode_marienplatz,
        to_geo=mock_geocode_english_garden,
        route_res=None,
    )
    # tools_without_route does not contain 'get_route_context'
    assert not is_route_tool_available(tools=tools_without_route)

    state = create_fresh_trip_state(
        user_message="Directions from Marienplatz to English Garden in Munich",
        intent=Intent.ROUTE_PLANNING,
        initial_known_fields={
            "destination": "Munich",
            "route_from": "Marienplatz",
            "route_to": "English Garden",
        },
    )

    final_state = run_workflow(state, tools=tools_without_route)

    assert final_state.status == RunStatus.PARTIAL
    # Route tool was never in planned_tool_calls
    assert not any(
        c.tool_name == "get_route_context" for c in final_state.planned_tool_calls
    )

    # Route tool is recorded as skipped with explanation
    skipped_route = next(
        r for r in final_state.tool_results if r.tool_name == "get_route_context"
    )
    assert skipped_route.status == ToolStatus.SKIPPED
    assert "Routing capability is unavailable" in skipped_route.safe_message

    # Response states capability is unavailable, not as provider failure
    assert any("Routing capability is unavailable" in w for w in final_state.warnings)
    assert any(
        "Routing capability is currently unavailable." in w
        for w in final_state.warnings
    )


# ==============================================================================
# 9. MAX_TOOL_CALLS Limit Enforced
# ==============================================================================


def test_max_tool_calls_enforced(
    mock_geocode_destination: ToolResult,
    mock_geocode_marienplatz: ToolResult,
    mock_geocode_english_garden: ToolResult,
    mock_route_success: ToolResult,
) -> None:
    """Execution terminates cleanly with warning when MAX_TOOL_CALLS is reached."""
    tools = make_mock_tools(
        dest_geo=mock_geocode_destination,
        from_geo=mock_geocode_marienplatz,
        to_geo=mock_geocode_english_garden,
        route_res=mock_route_success,
    )

    state = create_fresh_trip_state(
        user_message="Directions from Marienplatz to English Garden in Munich",
        intent=Intent.ROUTE_PLANNING,
        initial_known_fields={
            "destination": "Munich",
            "route_from": "Marienplatz",
            "route_to": "English Garden",
        },
    )

    # Execute workflow with limit capped at 2
    from app.agent.graph import create_agent_graph

    graph = create_agent_graph(tools=tools, max_tool_calls=2).compile()
    final_dict = graph.invoke(state)
    final_state = TripState.model_validate(final_dict)

    assert len(final_state.tool_results) == 2
    assert any(
        "Tool execution capped by MAX_TOOL_CALLS limit (2)" in w
        for w in final_state.warnings
    )


# ==============================================================================
# 10. Existing Intents Unchanged
# ==============================================================================


def test_destination_discovery_unchanged(
    mock_geocode_destination: ToolResult,
) -> None:
    """Destination discovery remains strictly unchanged: 1 tool call, COMPLETED."""
    tools = {"geocode_destination": lambda args: mock_geocode_destination}
    state = create_fresh_trip_state(
        user_message="Explore Munich",
        intent=Intent.DESTINATION_DISCOVERY,
        initial_known_fields={"destination": "Munich"},
    )
    final_state = run_workflow(state, tools=tools)
    assert final_state.status == RunStatus.COMPLETED
    assert len(final_state.tool_results) == 1
    assert final_state.tool_results[0].tool_name == "geocode_destination"
    assert final_state.itinerary_draft is None


def test_weather_planning_unchanged(
    mock_geocode_destination: ToolResult,
) -> None:
    """Weather planning remains strictly unchanged: 2 tool calls in order."""
    call_order: list[str] = []

    def _geo(args: dict[str, Any]) -> ToolResult:
        call_order.append("geocode")
        return mock_geocode_destination

    def _weather(args: dict[str, Any]) -> ToolResult:
        call_order.append("weather")
        return ToolResult(
            tool_name="get_weather",
            status=ToolStatus.OK,
            data={"daily": []},
            data_origin="mock",
        )

    tools = {
        "geocode_destination": _geo,
        "get_weather": _weather,
    }

    state = create_fresh_trip_state(
        user_message="Weather in Munich in November",
        intent=Intent.WEATHER_PLANNING,
        initial_known_fields={
            "destination": "Munich",
            "start_date": "2026-11-01",
            "end_date": "2026-11-05",
        },
    )

    final_state = run_workflow(state, tools=tools)

    assert call_order == ["geocode", "weather"]
    assert len(final_state.tool_results) == 2
    assert not any(r.tool_name == "get_route_context" for r in final_state.tool_results)
