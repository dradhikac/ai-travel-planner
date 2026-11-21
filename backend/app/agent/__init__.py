"""Phase 3 Agent state machine, contracts, workflow graph, and error definitions."""

from app.agent.errors import (
    AgentError,
    SecurityViolationError,
    ToolContractError,
    ToolErrorCode,
)
from app.agent.gateway import (
    LLMRepairGateway,
    ModelGateway,
    RuleBasedGateway,
    ScriptedGateway,
    get_default_gateway,
)
from app.agent.graph import compile_agent_graph, create_agent_graph, run_workflow
from app.agent.nodes import (
    ask_clarification,
    build_partial_result_node,
    build_tool_activity,
    check_required_fields,
    draft_itinerary,
    execute_tools,
    parse_request,
    plan_tool_calls,
    repair_itinerary,
    respond,
    sanitize_url,
    validate_itinerary,
)
from app.agent.partial import build_safe_partial_result
from app.agent.state import Intent, RunStatus, TripState, create_fresh_trip_state
from app.agent.tools import (
    TOOL_REGISTRY,
    GeocodeArgs,
    ToolCall,
    ToolResult,
    ToolStatus,
    WeatherArgs,
    geocode_destination,
    get_tool,
    get_weather,
)
from app.agent.validation import (
    VALIDATION_REGISTRY,
    ValidationCode,
    ValidationIssue,
    ValidationRule,
    ValidationSeverity,
    has_critical,
)
from app.agent.validation import (
    validate_itinerary as validate_itinerary_rules,
)
from app.schemas.trip import ToolActivity

__all__ = [
    "AgentError",
    "GeocodeArgs",
    "Intent",
    "LLMRepairGateway",
    "ModelGateway",
    "RuleBasedGateway",
    "RunStatus",
    "ScriptedGateway",
    "SecurityViolationError",
    "TOOL_REGISTRY",
    "ToolActivity",
    "ToolCall",
    "ToolContractError",
    "ToolErrorCode",
    "ToolResult",
    "ToolStatus",
    "TripState",
    "VALIDATION_REGISTRY",
    "ValidationCode",
    "ValidationIssue",
    "ValidationRule",
    "ValidationSeverity",
    "WeatherArgs",
    "ask_clarification",
    "build_partial_result_node",
    "build_safe_partial_result",
    "build_tool_activity",
    "check_required_fields",
    "compile_agent_graph",
    "create_agent_graph",
    "create_fresh_trip_state",
    "draft_itinerary",
    "execute_tools",
    "geocode_destination",
    "get_default_gateway",
    "get_tool",
    "get_weather",
    "has_critical",
    "parse_request",
    "plan_tool_calls",
    "repair_itinerary",
    "respond",
    "run_workflow",
    "sanitize_url",
    "validate_itinerary",
    "validate_itinerary_rules",
]
