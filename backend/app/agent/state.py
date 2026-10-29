"""Typed agent state machine models, intent classification, and lifecycle states."""

from enum import StrEnum
from typing import Any, Final
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.agent.tools import ToolCall, ToolResult
from app.schemas.trip import Itinerary, TripRequest, TripResponse

FORBIDDEN_SECRET_KEYS: Final[tuple[str, ...]] = (
    "api_key",
    "apikey",
    "token",
    "password",
    "secret",
    "auth",
    "credential",
    "private_key",
)


class Intent(StrEnum):
    """Classified user planning intent governing tool selection and workflow path."""

    DESTINATION_DISCOVERY = "destination_discovery"
    WEATHER_PLANNING = "weather_planning"
    ITINERARY_PLANNING = "itinerary_planning"
    UNSUPPORTED = "unsupported"


class RunStatus(StrEnum):
    """Lifecycle status of an agent workflow run."""

    NEEDS_CLARIFICATION = "needs_clarification"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class TripState(BaseModel):
    """Comprehensive typed state container flowing through the LangGraph workflow.

    Enforces truthfulness, bounded repair cycles, and strict security rules:
    - Secrets, private tokens, passwords, and raw provider payloads must NEVER
      be injected into state fields.
    - All tool outputs are strictly normalized into ToolResult envelopes.
    """

    model_config = ConfigDict(extra="forbid")

    # 1. Intake and Identity
    request_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Unique request correlation ID (never contains credentials)",
    )
    user_message: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Original normalized user message text",
    )
    known_fields: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Accumulated partial trip parameters extracted from conversation. "
            "Rejects any secret-bearing keys like api_key, token, or password."
        ),
    )

    # 2. Domain Validation Seams
    trip_request: TripRequest | None = Field(
        default=None,
        description=(
            "Fully validated Phase 2 TripRequest, or None if parameters incomplete"
        ),
    )
    missing_fields: list[str] = Field(
        default_factory=list,
        description="List of required travel fields missing from user intake",
    )
    contradictions: list[str] = Field(
        default_factory=list,
        description="List of detected logical contradictions in travel constraints",
    )
    clarification_question: str | None = Field(
        default=None,
        max_length=500,
        description="Targeted single clarification question when fields are ambiguous",
    )

    # 3. Intent Routing & Planning Bounds
    intent: Intent = Field(
        default=Intent.ITINERARY_PLANNING,
        description="Classified user travel planning intent",
    )
    low_budget: bool = Field(
        default=False,
        description=(
            "Flag indicating low daily budget per traveler (requires frugal pacing)"
        ),
    )
    planned_tool_calls: list[ToolCall] = Field(
        default_factory=list,
        description="Sequence of tool calls scheduled for execution in current step",
    )
    tool_results: list[ToolResult] = Field(
        default_factory=list,
        description="Immutable audit trail of normalized tool execution results",
    )

    # 4. Itinerary Synthesis & Quality Control
    itinerary_draft: Itinerary | None = Field(
        default=None,
        description="Draft itinerary synthesized by Phase 2 generation service",
    )
    validation_issues: list[str] = Field(
        default_factory=list,
        description=(
            "Rule or constraint violations identified during itinerary validation"
        ),
    )
    repair_attempts: int = Field(
        default=0,
        ge=0,
        description="Number of repair loops attempted (capped by MAX_REPAIR_ATTEMPTS)",
    )
    step_count: int = Field(
        default=0,
        ge=0,
        description=(
            "Number of graph node transitions executed (capped by recursion_limit)"
        ),
    )

    # 5. Output Lifecycle & Diagnostic Warnings
    status: RunStatus = Field(
        default=RunStatus.NEEDS_CLARIFICATION,
        description="Overall lifecycle execution status",
    )
    final_response: TripResponse | None = Field(
        default=None,
        description="Final complete TripResponse document when workflow succeeds",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description=(
            "Aggregated planning warnings, provider fallbacks, or horizon notices"
        ),
    )

    @field_validator("known_fields", mode="after")
    @classmethod
    def reject_secrets_in_known_fields(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Verify known_fields never contains secret-looking keys or credentials.

        Strictly rejects keys named api_key, apikey, token, password, secret,
        auth, credential, or private_key regardless of casing.
        """
        for raw_key in v:
            norm_key = str(raw_key).lower().replace("-", "_").strip()
            for forbidden in FORBIDDEN_SECRET_KEYS:
                if forbidden in norm_key:
                    raise ValueError(
                        f"known_fields rejects forbidden secret-like key '{raw_key}'. "
                        "State must never hold credentials, tokens, or passwords."
                    )
        return v


def create_fresh_trip_state(
    user_message: str,
    request_id: str | None = None,
    initial_known_fields: dict[str, Any] | None = None,
    intent: Intent = Intent.ITINERARY_PLANNING,
) -> TripState:
    """Construct a clean, initialized TripState instance for workflow execution.

    Args:
        user_message: Raw user travel planning prompt.
        request_id: Optional correlation ID; generates a unique UUID if omitted.
        initial_known_fields: Optional initial parameters extracted from intake.
        intent: Initial classified intent (defaults to itinerary planning).

    Returns:
        Pristine, validated TripState conforming to Phase 3 state architecture.
    """
    clean_message = user_message.strip()
    if not clean_message:
        raise ValueError("user_message cannot be empty or whitespace only")

    active_request_id = request_id.strip() if request_id else f"req_{uuid4().hex[:12]}"

    return TripState(
        request_id=active_request_id,
        user_message=clean_message,
        known_fields=initial_known_fields or {},
        intent=intent,
        status=RunStatus.NEEDS_CLARIFICATION,
    )
