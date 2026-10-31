"""StateGraph workflow assembly, conditional routing, and bounded execution.

Implements the Phase 3 LangGraph state machine:
- Explicit nodes: parse_request, check_required_fields, plan_tool_calls,
  execute_tools, draft_itinerary, validate_itinerary, ask_clarification, respond.
- Conditional edge routing for clarification seams and tool execution.
- Step count guardrails and LangGraph recursion limits for bounded termination.
- run_workflow entry point accepting injectable dependencies for testing.
"""

from typing import Any

from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph

from app.agent.gateway import ModelGateway, RuleBasedGateway
from app.agent.nodes import (
    ask_clarification,
    check_required_fields,
    draft_itinerary,
    execute_tools,
    parse_request,
    plan_tool_calls,
    respond,
    validate_itinerary,
)
from app.agent.state import Intent, RunStatus, TripState, create_fresh_trip_state
from app.agent.tools.registry import TOOL_REGISTRY
from app.core.config import (
    AGENT_RECURSION_LIMIT,
    MAX_TOOL_CALLS,
    get_settings,
)


def create_agent_graph(
    gateway: ModelGateway | None = None,
    tools: dict[str, Any] | None = None,
    max_tool_calls: int = MAX_TOOL_CALLS,
    max_steps: int = AGENT_RECURSION_LIMIT,
) -> StateGraph:
    """Build and configure the LangGraph StateGraph with conditional edges and guards.

    Args:
        gateway: Optional ModelGateway protocol (defaults to RuleBasedGateway).
        tools: Optional dictionary of tools (defaults to TOOL_REGISTRY).
        max_tool_calls: Bounded limit on sequential tool invocations per workflow run.
        max_steps: Step count ceiling before triggering the runaway guard.

    Returns:
        Uncompiled StateGraph instance parameterized with injected dependencies.
    """
    active_gateway = gateway or RuleBasedGateway()
    active_tools = tools if tools is not None else TOOL_REGISTRY

    # 1. Define node wrappers bound with injected dependencies
    def _node_parse(state: TripState) -> dict[str, Any]:
        return parse_request(state, gateway=active_gateway)

    def _node_check_fields(state: TripState) -> dict[str, Any]:
        return check_required_fields(state)

    def _node_clarify(state: TripState) -> dict[str, Any]:
        return ask_clarification(state, gateway=active_gateway)

    def _node_plan(state: TripState) -> dict[str, Any]:
        return plan_tool_calls(state)

    def _node_execute(state: TripState) -> dict[str, Any]:
        return execute_tools(state, tools=active_tools, max_tool_calls=max_tool_calls)

    def _node_draft(state: TripState) -> dict[str, Any]:
        return draft_itinerary(state)

    def _node_validate(state: TripState) -> dict[str, Any]:
        return validate_itinerary(state)

    def _node_respond(state: TripState) -> dict[str, Any]:
        return respond(state, max_steps=max_steps)

    # 2. Define conditional edge routing logic
    def _route_after_check_fields(state: TripState) -> str:
        """Route to clarification if fields missing, respond if guard, or plan."""
        if state.step_count >= max_steps:
            return "respond"
        if state.missing_fields:
            return "ask_clarification"
        if state.intent == Intent.UNSUPPORTED:
            return "respond"
        return "plan_tool_calls"

    def _route_after_plan_tools(state: TripState) -> str:
        """Route to execute_tools if calls planned; otherwise route to respond."""
        if state.step_count >= max_steps:
            return "respond"
        if not state.planned_tool_calls:
            return "respond"
        return "execute_tools"

    def _route_after_execute_tools(state: TripState) -> str:
        """Route to draft_itinerary for full planning, or respond for discovery."""
        if state.step_count >= max_steps:
            return "respond"
        if state.intent == Intent.DESTINATION_DISCOVERY:
            return "respond"
        return "draft_itinerary"

    # 3. Assemble graph nodes
    builder = StateGraph(TripState)
    builder.add_node("parse_request", _node_parse)
    builder.add_node("check_required_fields", _node_check_fields)
    builder.add_node("ask_clarification", _node_clarify)
    builder.add_node("plan_tool_calls", _node_plan)
    builder.add_node("execute_tools", _node_execute)
    builder.add_node("draft_itinerary", _node_draft)
    builder.add_node("validate_itinerary", _node_validate)
    builder.add_node("respond", _node_respond)

    # 4. Wire edges and conditional routing
    builder.add_edge(START, "parse_request")
    builder.add_edge("parse_request", "check_required_fields")

    builder.add_conditional_edges(
        "check_required_fields",
        _route_after_check_fields,
        {
            "ask_clarification": "ask_clarification",
            "plan_tool_calls": "plan_tool_calls",
            "respond": "respond",
        },
    )

    builder.add_edge("ask_clarification", "respond")

    builder.add_conditional_edges(
        "plan_tool_calls",
        _route_after_plan_tools,
        {
            "execute_tools": "execute_tools",
            "respond": "respond",
        },
    )

    builder.add_conditional_edges(
        "execute_tools",
        _route_after_execute_tools,
        {
            "draft_itinerary": "draft_itinerary",
            "respond": "respond",
        },
    )

    builder.add_edge("draft_itinerary", "validate_itinerary")
    builder.add_edge("validate_itinerary", "respond")
    builder.add_edge("respond", END)

    return builder


def compile_agent_graph(
    gateway: ModelGateway | None = None,
    tools: dict[str, Any] | None = None,
    max_tool_calls: int = MAX_TOOL_CALLS,
    max_steps: int = AGENT_RECURSION_LIMIT,
) -> Any:
    """Compile the configured StateGraph into an executable LangGraph instance."""
    builder = create_agent_graph(
        gateway=gateway,
        tools=tools,
        max_tool_calls=max_tool_calls,
        max_steps=max_steps,
    )
    return builder.compile()


def run_workflow(
    initial_state: TripState | dict[str, Any] | str,
    gateway: ModelGateway | None = None,
    tools: dict[str, Any] | None = None,
    recursion_limit: int | None = None,
    max_tool_calls: int | None = None,
    max_steps: int | None = None,
) -> TripState:
    """Execute the full agent workflow with step guards and recursion limits.

    Args:
        initial_state: TripState instance, state dict, or prompt string.
        gateway: Optional ModelGateway protocol (defaults to RuleBasedGateway).
        tools: Optional dictionary of tools (defaults to TOOL_REGISTRY).
        recursion_limit: Maximum super-step executions permitted by LangGraph runtime.
        max_tool_calls: Maximum sequential tool calls allowed during execution.
        max_steps: Maximum step count ceiling before step guard halts execution.

    Returns:
        Final mutated TripState document conforming to Phase 3 state architecture.
    """
    settings = get_settings()
    active_recursion_limit = (
        recursion_limit
        if recursion_limit is not None
        else settings.AGENT_RECURSION_LIMIT
    )
    active_max_tool_calls = (
        max_tool_calls if max_tool_calls is not None else settings.AGENT_MAX_TOOL_CALLS
    )
    active_max_steps = (
        max_steps if max_steps is not None else settings.AGENT_RECURSION_LIMIT
    )

    # Normalize input into valid TripState
    state_obj: TripState
    if isinstance(initial_state, str):
        state_obj = create_fresh_trip_state(user_message=initial_state)
    elif isinstance(initial_state, dict):
        state_obj = TripState.model_validate(initial_state)
    elif isinstance(initial_state, TripState):
        state_obj = initial_state
    else:
        raise TypeError(
            f"Expected TripState, dict, or str, got {type(initial_state).__name__}"
        )

    compiled = compile_agent_graph(
        gateway=gateway,
        tools=tools,
        max_tool_calls=active_max_tool_calls,
        max_steps=active_max_steps,
    )

    try:
        raw_output = compiled.invoke(
            state_obj,
            config={"recursion_limit": active_recursion_limit},
        )
        if isinstance(raw_output, TripState):
            return raw_output
        return TripState.model_validate(raw_output)

    except GraphRecursionError:
        # Step/recursion limit triggered: return failed state with clear diagnostic note
        return TripState(
            request_id=state_obj.request_id,
            user_message=state_obj.user_message,
            known_fields=state_obj.known_fields,
            intent=state_obj.intent,
            status=RunStatus.FAILED,
            step_count=state_obj.step_count + 1,
            warnings=list(state_obj.warnings)
            + [
                "Workflow execution exceeded recursion limit "
                f"({active_recursion_limit})."
            ],
        )
