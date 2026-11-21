"""StateGraph workflow assembly, conditional routing, and bounded execution.

Implements the Phase 3 LangGraph state machine:
- Explicit nodes: parse_request, check_required_fields, plan_tool_calls,
  execute_tools, draft_itinerary, validate_itinerary, ask_clarification, respond.
- Conditional edge routing for clarification seams and tool execution.
- Step count guardrails and LangGraph recursion limits for bounded termination.
- run_workflow entry point accepting injectable dependencies for testing.
"""

import time
from typing import Any

from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph

from app.agent.gateway import ModelGateway, get_default_gateway
from app.agent.nodes import (
    ask_clarification,
    build_partial_result_node,
    check_required_fields,
    draft_itinerary,
    execute_tools,
    parse_request,
    plan_tool_calls,
    repair_itinerary,
    respond,
    validate_itinerary,
)
from app.agent.state import Intent, RunStatus, TripState, create_fresh_trip_state
from app.agent.tools.contracts import ToolStatus
from app.agent.tools.registry import TOOL_REGISTRY
from app.agent.validation import (
    ValidationSeverity,
    has_critical,
    run_itinerary_validation,
)
from app.core.config import (
    AGENT_RECURSION_LIMIT,
    MAX_REPAIR_ATTEMPTS,
    MAX_TOOL_CALLS,
    get_settings,
)
from app.core.logging import (
    emit_event,
    reset_current_node,
    reset_request_id,
    set_current_node,
    set_request_id,
)


def create_agent_graph(
    gateway: ModelGateway | None = None,
    tools: dict[str, Any] | None = None,
    max_tool_calls: int = MAX_TOOL_CALLS,
    max_steps: int = AGENT_RECURSION_LIMIT,
    max_repair_attempts: int = MAX_REPAIR_ATTEMPTS,
) -> StateGraph:
    """Build and configure the LangGraph StateGraph with conditional edges and guards.

    Args:
        gateway: Optional ModelGateway protocol (defaults to RuleBasedGateway).
        tools: Optional dictionary of tools (defaults to TOOL_REGISTRY).
        max_tool_calls: Bounded limit on sequential tool invocations per workflow run.
        max_steps: Step count ceiling before triggering the runaway guard.
        max_repair_attempts: Maximum bounded repair loops before safe degradation.

    Returns:
        Uncompiled StateGraph instance parameterized with injected dependencies.
    """
    active_gateway = gateway or get_default_gateway()
    active_tools = tools if tools is not None else TOOL_REGISTRY

    # 1. Define node wrappers bound with injected dependencies
    def _node_parse(state: TripState) -> dict[str, Any]:
        return parse_request(state, gateway=active_gateway)

    def _node_check_fields(state: TripState) -> dict[str, Any]:
        return check_required_fields(state)

    def _node_clarify(state: TripState) -> dict[str, Any]:
        return ask_clarification(state, gateway=active_gateway)

    def _node_plan(state: TripState) -> dict[str, Any]:
        return plan_tool_calls(state, tools=active_tools)

    def _node_execute(state: TripState) -> dict[str, Any]:
        return execute_tools(state, tools=active_tools, max_tool_calls=max_tool_calls)

    def _node_draft(state: TripState) -> dict[str, Any]:
        return draft_itinerary(state)

    def _node_validate(state: TripState) -> dict[str, Any]:
        return validate_itinerary(state)

    def _node_repair(state: TripState) -> dict[str, Any]:
        return repair_itinerary(state, gateway=active_gateway)

    def _node_partial(state: TripState) -> dict[str, Any]:
        return build_partial_result_node(state)

    def _node_respond(state: TripState) -> dict[str, Any]:
        return respond(state, max_steps=max_steps)

    # 2. Define conditional edge routing logic
    def _route_after_check_fields(state: TripState) -> str:
        """Route to clarification if fields missing/contradictory, else proceed."""
        if state.step_count >= max_steps:
            return "respond"
        if state.missing_fields or state.contradictions:
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
        """Route to draft_itinerary for planning, or respond for discovery/failure."""
        if state.step_count >= max_steps:
            return "respond"
        if state.intent in (Intent.DESTINATION_DISCOVERY, Intent.ROUTE_PLANNING):
            return "respond"
        geo_res = next(
            (r for r in state.tool_results if r.tool_name == "geocode_destination"),
            None,
        )
        if geo_res is not None and (
            geo_res.status != ToolStatus.OK or not geo_res.data
        ):
            return "respond"
        return "draft_itinerary"

    def _route_after_validate(state: TripState) -> str:
        """Route after validation: respond if clean, else repair or partial result."""
        if state.step_count >= max_steps or state.itinerary_draft is None:
            return "respond"

        issues = run_itinerary_validation(
            state.itinerary_draft,
            request=state.trip_request,
            tool_results=state.tool_results,
        )
        if not has_critical(issues):
            return "respond"

        # Check maximum repair attempts
        if state.repair_attempts >= max_repair_attempts:
            return "build_partial_result"

        # Check for no-progress / identical critical issue set
        current_crit_sig = sorted(
            [
                f"{i.code}:{i.day_number}:{i.activity_id}"
                for i in issues
                if i.severity == ValidationSeverity.CRITICAL
            ]
        )
        if (
            state.repair_attempts >= 1
            and state.last_critical_issues
            and current_crit_sig == state.last_critical_issues
        ):
            return "build_partial_result"

        return "repair_itinerary"

    # Helper to wrap graph nodes with structured event tracing
    def _wrap_node(node_name: str, node_fn: Any) -> Any:
        def _wrapped(state: TripState) -> dict[str, Any]:
            token_node = set_current_node(node_name)
            emit_event("node_started", node=node_name)
            t0 = time.perf_counter()
            try:
                result = node_fn(state)
                latency_ms = max(0.0, round((time.perf_counter() - t0) * 1000.0, 2))
                res_status = "ok"
                if isinstance(result, dict) and "status" in result and result["status"]:
                    s = result["status"]
                    res_status = s.value if hasattr(s, "value") else str(s)
                emit_event(
                    "node_finished",
                    node=node_name,
                    latency_ms=latency_ms,
                    status=res_status,
                )
                return result
            except Exception as exc:
                latency_ms = max(0.0, round((time.perf_counter() - t0) * 1000.0, 2))
                emit_event(
                    "node_finished",
                    node=node_name,
                    latency_ms=latency_ms,
                    status="failed",
                    error_code=exc.__class__.__name__,
                )
                raise
            finally:
                reset_current_node(token_node)

        return _wrapped

    # 3. Assemble graph nodes
    builder = StateGraph(TripState)
    builder.add_node("parse_request", _wrap_node("parse_request", _node_parse))
    builder.add_node(
        "check_required_fields",
        _wrap_node("check_required_fields", _node_check_fields),
    )
    builder.add_node(
        "ask_clarification", _wrap_node("ask_clarification", _node_clarify)
    )
    builder.add_node("plan_tool_calls", _wrap_node("plan_tool_calls", _node_plan))
    builder.add_node("execute_tools", _wrap_node("execute_tools", _node_execute))
    builder.add_node("draft_itinerary", _wrap_node("draft_itinerary", _node_draft))
    builder.add_node(
        "validate_itinerary", _wrap_node("validate_itinerary", _node_validate)
    )
    builder.add_node("repair_itinerary", _wrap_node("repair_itinerary", _node_repair))
    builder.add_node(
        "build_partial_result",
        _wrap_node("build_partial_result", _node_partial),
    )
    builder.add_node("respond", _wrap_node("respond", _node_respond))

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

    builder.add_conditional_edges(
        "validate_itinerary",
        _route_after_validate,
        {
            "respond": "respond",
            "repair_itinerary": "repair_itinerary",
            "build_partial_result": "build_partial_result",
        },
    )

    builder.add_edge("repair_itinerary", "validate_itinerary")
    builder.add_edge("build_partial_result", "respond")
    builder.add_edge("respond", END)

    return builder


def compile_agent_graph(
    gateway: ModelGateway | None = None,
    tools: dict[str, Any] | None = None,
    max_tool_calls: int = MAX_TOOL_CALLS,
    max_steps: int = AGENT_RECURSION_LIMIT,
    max_repair_attempts: int = MAX_REPAIR_ATTEMPTS,
) -> Any:
    """Compile the configured StateGraph into an executable LangGraph instance."""
    builder = create_agent_graph(
        gateway=gateway,
        tools=tools,
        max_tool_calls=max_tool_calls,
        max_steps=max_steps,
        max_repair_attempts=max_repair_attempts,
    )
    return builder.compile()


def run_workflow(
    initial_state: TripState | dict[str, Any] | str,
    gateway: ModelGateway | None = None,
    tools: dict[str, Any] | None = None,
    recursion_limit: int | None = None,
    max_tool_calls: int | None = None,
    max_steps: int | None = None,
    max_repair_attempts: int | None = None,
) -> TripState:
    """Execute the full agent workflow with step guards and recursion limits.

    Args:
        initial_state: TripState instance, state dict, or prompt string.
        gateway: Optional ModelGateway protocol (defaults to RuleBasedGateway).
        tools: Optional dictionary of tools (defaults to TOOL_REGISTRY).
        recursion_limit: Maximum super-step executions permitted by LangGraph runtime.
        max_tool_calls: Maximum sequential tool calls allowed during execution.
        max_steps: Maximum step count ceiling before step guard halts execution.
        max_repair_attempts: Maximum bounded repair loops before safe degradation.

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
    active_max_repair_attempts = (
        max_repair_attempts
        if max_repair_attempts is not None
        else settings.AGENT_MAX_REPAIR_ATTEMPTS
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
        max_repair_attempts=active_max_repair_attempts,
    )

    t_start = time.perf_counter()
    token_req = set_request_id(state_obj.request_id)
    final_state: TripState | None = None
    try:
        raw_output = compiled.invoke(
            state_obj,
            config={"recursion_limit": active_recursion_limit},
        )
        if isinstance(raw_output, TripState):
            final_state = raw_output
        else:
            final_state = TripState.model_validate(raw_output)
        return final_state

    except GraphRecursionError:
        # Step/recursion limit triggered: return failed state with diagnostic note
        final_state = TripState(
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
        return final_state

    finally:
        total_latency_ms = max(0.0, round((time.perf_counter() - t_start) * 1000.0, 2))
        if final_state is not None:
            tool_counts = {
                "total": len(final_state.tool_results),
                "ok": sum(
                    1 for r in final_state.tool_results if r.status == ToolStatus.OK
                ),
                "failed": sum(
                    1
                    for r in final_state.tool_results
                    if r.status
                    in (
                        ToolStatus.ERROR,
                        ToolStatus.TIMEOUT,
                        ToolStatus.RATE_LIMITED,
                    )
                ),
                "skipped": sum(
                    1
                    for r in final_state.tool_results
                    if r.status == ToolStatus.SKIPPED
                ),
                "empty": sum(
                    1 for r in final_state.tool_results if r.status == ToolStatus.EMPTY
                ),
            }
            emit_event(
                "workflow_finished",
                status=final_state.status.value,
                repair_attempts=final_state.repair_attempts,
                tool_counts=tool_counts,
                latency_ms=total_latency_ms,
            )
        else:
            emit_event(
                "workflow_finished",
                status="failed",
                repair_attempts=0,
                tool_counts={
                    "total": 0,
                    "ok": 0,
                    "failed": 0,
                    "skipped": 0,
                    "empty": 0,
                },
                latency_ms=total_latency_ms,
            )
        reset_request_id(token_req)
