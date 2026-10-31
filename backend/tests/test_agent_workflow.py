"""Unit and integration tests for the Phase 3 LangGraph agent workflow.

Verifies:
- Graph compiles successfully into an executable LangGraph instance.
- Each conditional edge is routed correctly according to state.
- Destination discovery calls ONLY geocoding (no weather, no itinerary).
- Weather planning calls geocoding and weather in exact order.
- Unsupported/booking requests call NO tools and fail gracefully.
- MAX_TOOL_CALLS is strictly enforced.
- Step count guard terminates a deliberately cyclic graph.
- Happy path returns a full itinerary and TripResponse document.
- Weather tool is NOT called when geocoding returns an empty result.
- Low-budget threshold sets low_budget flag.
"""

from datetime import UTC, date, datetime
from typing import Any

import pytest
from langgraph.graph import END, START, StateGraph

from app.agent.gateway import RuleBasedGateway, ScriptedGateway
from app.agent.graph import compile_agent_graph, create_agent_graph, run_workflow
from app.agent.nodes import (
    execute_tools,
    parse_request,
    respond,
)
from app.agent.state import Intent, RunStatus, TripState, create_fresh_trip_state
from app.agent.tools.contracts import ToolCall, ToolResult, ToolStatus
from app.schemas.provider import SourceInfo, WeatherDay, WeatherSummary

# ==============================================================================
# Test Fixtures & Fakes
# ==============================================================================


@pytest.fixture
def sample_source_info() -> SourceInfo:
    return SourceInfo(
        provider="Open-Meteo",
        url="https://open-meteo.com/",
        attribution="Weather data by Open-Meteo.com",
        fetched_at=datetime(2026, 10, 31, 12, 0, 0, tzinfo=UTC),
        data_origin="mock",
    )


@pytest.fixture
def mock_geocode_success(sample_source_info: SourceInfo) -> ToolResult:
    return ToolResult(
        tool_name="geocode_destination",
        status=ToolStatus.OK,
        data=[
            {
                "name": "Tokyo",
                "country": "Japan",
                "admin_region": "Tokyo",
                "latitude": 35.6762,
                "longitude": 139.6503,
                "timezone": "Asia/Tokyo",
                "source": sample_source_info.model_dump(mode="json"),
                "fetched_at": sample_source_info.fetched_at.isoformat(),
            }
        ],
        source=sample_source_info,
        fetched_at=sample_source_info.fetched_at,
        data_origin="mock",
    )


@pytest.fixture
def mock_geocode_empty() -> ToolResult:
    return ToolResult(
        tool_name="geocode_destination",
        status=ToolStatus.EMPTY,
        data=[],
        safe_message="No locations found.",
        data_origin="none",
    )


@pytest.fixture
def mock_weather_success(sample_source_info: SourceInfo) -> ToolResult:
    weather = WeatherSummary(
        location="Tokyo, Japan",
        days=[
            WeatherDay(
                date=date(2026, 11, 1),
                temp_min_c=12.0,
                temp_max_c=18.5,
                precipitation_probability_pct=10,
                precipitation_sum_mm=0.0,
                weather_code=1,
                condition_description="Clear",
            )
        ],
        units={"temperature": "celsius", "precipitation": "mm"},
        source=sample_source_info,
        fetched_at=sample_source_info.fetched_at,
        data_origin="mock",
    )
    return ToolResult(
        tool_name="get_weather",
        status=ToolStatus.OK,
        data=weather.model_dump(mode="json"),
        source=sample_source_info,
        fetched_at=sample_source_info.fetched_at,
        data_origin="mock",
    )


class RecordingTool:
    """Mock tool callable recording arguments and returning configured ToolResult."""

    def __init__(self, return_value: ToolResult) -> None:
        self.return_value = return_value
        self.invocations: list[dict[str, Any]] = []

    def invoke(self, args: dict[str, Any]) -> ToolResult:
        self.invocations.append(dict(args))
        return self.return_value


# ==============================================================================
# 1. Compilation & Assembly Tests
# ==============================================================================


def test_agent_graph_compiles_successfully() -> None:
    """StateGraph compiles into an executable LangGraph instance without errors."""
    builder = create_agent_graph()
    assert isinstance(builder, StateGraph)
    compiled = compile_agent_graph()
    assert compiled is not None
    assert hasattr(compiled, "invoke")


# ==============================================================================
# 2. Intent Routing & Tool Planning Tests
# ==============================================================================


def test_discovery_calls_only_geocode(mock_geocode_success: ToolResult) -> None:
    """Destination discovery intent plans and invokes only the geocode tool."""
    geo_tool = RecordingTool(mock_geocode_success)
    weather_tool = RecordingTool(mock_geocode_success)

    tools = {
        "geocode_destination": geo_tool,
        "get_weather": weather_tool,
    }

    state = create_fresh_trip_state(
        user_message="Explore Tokyo",
        intent=Intent.DESTINATION_DISCOVERY,
        initial_known_fields={"destination": "Tokyo"},
    )

    final_state = run_workflow(state, tools=tools)

    assert final_state.status == RunStatus.COMPLETED
    assert len(geo_tool.invocations) == 1
    assert geo_tool.invocations[0]["query"] == "Tokyo"
    # Weather tool was never invoked
    assert len(weather_tool.invocations) == 0
    # No itinerary draft synthesized for simple discovery
    assert final_state.itinerary_draft is None


def test_weather_planning_calls_both_in_order(
    mock_geocode_success: ToolResult,
    mock_weather_success: ToolResult,
) -> None:
    """Weather planning intent calls geocoding first, then weather with coords."""
    call_order: list[str] = []

    def _geo(args: dict[str, Any]) -> ToolResult:
        call_order.append("geocode")
        return mock_geocode_success

    def _weather(args: dict[str, Any]) -> ToolResult:
        call_order.append("weather")
        assert args["latitude"] == 35.6762
        assert args["longitude"] == 139.6503
        return mock_weather_success

    tools = {
        "geocode_destination": _geo,
        "get_weather": _weather,
    }

    gateway = ScriptedGateway(
        scripted_fields={
            "destination": "Tokyo",
            "start_date": "2026-11-01",
            "end_date": "2026-11-05",
        },
        scripted_intent=Intent.WEATHER_PLANNING,
    )

    state = create_fresh_trip_state(
        user_message="How is the weather in Tokyo in November?",
        initial_known_fields={
            "destination": "Tokyo",
            "start_date": "2026-11-01",
            "end_date": "2026-11-05",
        },
    )

    final_state = run_workflow(state, gateway=gateway, tools=tools)

    assert call_order == ["geocode", "weather"]
    assert len(final_state.tool_results) == 2
    assert final_state.tool_results[0].tool_name == "geocode_destination"
    assert final_state.tool_results[1].tool_name == "get_weather"


def test_unsupported_calls_no_tools(
    mock_geocode_success: ToolResult,
    mock_weather_success: ToolResult,
) -> None:
    """Unsupported requests execute zero tools and fail politely."""
    geo_tool = RecordingTool(mock_geocode_success)
    weather_tool = RecordingTool(mock_weather_success)
    tools = {
        "geocode_destination": geo_tool,
        "get_weather": weather_tool,
    }

    state = create_fresh_trip_state(user_message="Book a flight from London to Paris")

    final_state = run_workflow(state, tools=tools)

    assert final_state.status == RunStatus.FAILED
    assert len(geo_tool.invocations) == 0
    assert len(weather_tool.invocations) == 0
    assert any("out of scope" in w.lower() for w in final_state.warnings)


def test_weather_tool_not_called_when_geocoding_empty(
    mock_geocode_empty: ToolResult,
    mock_weather_success: ToolResult,
) -> None:
    """Weather tool must NOT be invoked when destination geocoding returns empty."""
    geo_tool = RecordingTool(mock_geocode_empty)
    weather_tool = RecordingTool(mock_weather_success)
    tools = {
        "geocode_destination": geo_tool,
        "get_weather": weather_tool,
    }

    state = create_fresh_trip_state(
        user_message="Plan trip to Atlantis from 2026-11-01 to 2026-11-03",
        initial_known_fields={
            "destination": "Atlantis",
            "origin": "London",
            "start_date": "2026-11-01",
            "end_date": "2026-11-03",
        },
    )

    final_state = run_workflow(state, tools=tools)

    assert len(geo_tool.invocations) == 1
    # Strict requirement: weather tool is never invoked when geocode returned empty
    assert len(weather_tool.invocations) == 0
    assert any("skipped" in w.lower() for w in final_state.warnings)


# ==============================================================================
# 3. Execution Bounds & Guardrails Tests
# ==============================================================================


def test_max_tool_calls_enforced(mock_geocode_success: ToolResult) -> None:
    """execute_tools caps invocations at MAX_TOOL_CALLS and records a warning."""
    tool = RecordingTool(mock_geocode_success)
    tools = {"dummy_tool": tool}

    state = create_fresh_trip_state(user_message="Run multiple tools")
    state.planned_tool_calls = [
        ToolCall(tool_name="dummy_tool", arguments={"i": 1}),
        ToolCall(tool_name="dummy_tool", arguments={"i": 2}),
        ToolCall(tool_name="dummy_tool", arguments={"i": 3}),
        ToolCall(tool_name="dummy_tool", arguments={"i": 4}),
        ToolCall(tool_name="dummy_tool", arguments={"i": 5}),
    ]

    update = execute_tools(state, tools=tools, max_tool_calls=3)

    assert len(tool.invocations) == 3
    assert len(update["tool_results"]) == 3
    assert any("capped by MAX_TOOL_CALLS" in w for w in update["warnings"])


def test_step_guard_terminates_deliberately_cyclic_fake() -> None:
    """Step count guard halts execution and marks status FAILED if a cycle occurs."""
    builder = StateGraph(TripState)

    def _looping_node_a(state: TripState) -> dict[str, Any]:
        return {"step_count": state.step_count + 1}

    def _looping_node_b(state: TripState) -> dict[str, Any]:
        return {"step_count": state.step_count + 1}

    def _respond_node(state: TripState) -> dict[str, Any]:
        return respond(state, max_steps=5)

    def _cyclic_route(state: TripState) -> str:
        if state.step_count >= 5:
            return "respond"
        return "node_b"

    builder.add_node("node_a", _looping_node_a)
    builder.add_node("node_b", _looping_node_b)
    builder.add_node("respond", _respond_node)

    builder.add_edge(START, "node_a")
    builder.add_conditional_edges(
        "node_a", _cyclic_route, {"node_b": "node_b", "respond": "respond"}
    )
    builder.add_edge("node_b", "node_a")
    builder.add_edge("respond", END)

    compiled = builder.compile()

    state = create_fresh_trip_state("Test cycle")
    result_dict = compiled.invoke(state, config={"recursion_limit": 20})
    final_state = TripState.model_validate(result_dict)

    assert final_state.status == RunStatus.FAILED
    assert any("step count guard exceeded threshold" in w for w in final_state.warnings)


# ==============================================================================
# 4. Conditional Edge Routing Tests
# ==============================================================================


def test_conditional_edge_missing_fields_routes_to_clarification() -> None:
    """Missing required fields triggers clarification edge and stops before planning."""
    state = create_fresh_trip_state(
        user_message="Plan a trip",
        initial_known_fields={},  # No destination or dates
    )

    final_state = run_workflow(state)

    assert final_state.status == RunStatus.NEEDS_CLARIFICATION
    assert final_state.clarification_question is not None
    assert "destination" in final_state.missing_fields
    assert len(final_state.tool_results) == 0


def test_low_budget_flag_set_from_per_person_day_threshold() -> None:
    """Low budget requests (< 50 units / day-person) set low_budget flag."""
    gateway = RuleBasedGateway()
    state = create_fresh_trip_state(
        user_message="Plan a 4-day trip to Tokyo",
        initial_known_fields={
            "destination": "Tokyo",
            "start_date": "2026-11-01",
            "end_date": "2026-11-04",  # 4 days
            "party_size": 2,  # 2 * 4 = 8 person-days
            "budget_amount": "200.00",  # 200 / 8 = 25.0 (< 50.0 threshold)
        },
    )

    update = parse_request(state, gateway=gateway)
    assert update["low_budget"] is True


# ==============================================================================
# 5. Full Happy Path Itinerary Synthesis Tests
# ==============================================================================


def test_happy_path_returns_complete_itinerary(
    mock_geocode_success: ToolResult,
    mock_weather_success: ToolResult,
) -> None:
    """Complete input with valid tools generates a full Itinerary and TripResponse."""
    tools = {
        "geocode_destination": RecordingTool(mock_geocode_success),
        "get_weather": RecordingTool(mock_weather_success),
    }

    state = create_fresh_trip_state(
        user_message="Plan a trip from London to Tokyo from 2026-11-01 to 2026-11-03",
        initial_known_fields={
            "origin": "London",
            "destination": "Tokyo",
            "start_date": "2026-11-01",
            "end_date": "2026-11-03",
            "party_size": 2,
            "interests": ["history", "food"],
            "pace": "balanced",
        },
    )

    final_state = run_workflow(state, tools=tools)

    assert final_state.status == RunStatus.COMPLETED
    assert final_state.itinerary_draft is not None
    assert len(final_state.itinerary_draft.days) == 3
    assert final_state.final_response is not None
    assert final_state.final_response.request.destination == "Tokyo"
    assert len(final_state.final_response.sources) >= 1
