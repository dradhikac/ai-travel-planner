"""Pure-ish workflow execution nodes for the Phase 3 LangGraph state machine.

Each node takes TripState (and optional dependencies) and returns a dictionary of
state mutations to be applied by LangGraph. Nodes enforce strict execution bounds,
step guards, provenance attribution, and safe error handling.
"""

from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from app.agent.errors import ToolErrorCode
from app.agent.gateway import ModelGateway, RuleBasedGateway
from app.agent.state import Intent, RunStatus, TripState
from app.agent.tools.contracts import ToolCall, ToolResult, ToolStatus
from app.agent.tools.registry import TOOL_REGISTRY
from app.core.config import MAX_TOOL_CALLS
from app.schemas.provider import GeocodeResult, WeatherSummary
from app.schemas.trip import TripRequest, TripResponse
from app.services.itinerary import generate_itinerary

# Ensure clean class-level initialization of TripRequest reference date
TripRequest.set_test_today(None)


# ==============================================================================
# 1. Intake & Field Parsing Node
# ==============================================================================


def parse_request(
    state: TripState,
    gateway: ModelGateway | None = None,
) -> dict[str, Any]:
    """Normalize user intake, assign request ID, and extract initial parameters."""
    active_gateway = gateway or RuleBasedGateway()

    # Extract travel parameters from raw message
    extracted = active_gateway.extract_known_fields(
        state.user_message,
        existing_fields=state.known_fields,
    )

    # Classify user planning intent if not already explicitly defined
    intent = state.intent
    if intent == Intent.ITINERARY_PLANNING and not state.known_fields:
        intent = active_gateway.classify_intent(state.user_message, extracted)

    # Determine low-budget flag (threshold: < 50 currency units / traveler-day)
    low_budget = state.low_budget
    if (
        "budget_amount" in extracted
        and "start_date" in extracted
        and "end_date" in extracted
    ):
        try:
            start_d = date.fromisoformat(extracted["start_date"])
            end_d = date.fromisoformat(extracted["end_date"])
            days = max(1, (end_d - start_d).days + 1)
            party = max(1, int(extracted.get("party_size", 1)))
            budget_val = Decimal(str(extracted["budget_amount"]))
            daily_per_person = budget_val / Decimal(days * party)
            if daily_per_person < Decimal("50.0"):
                low_budget = True
        except (ValueError, InvalidOperation):
            pass

    return {
        "step_count": state.step_count + 1,
        "known_fields": extracted,
        "intent": intent,
        "low_budget": low_budget,
    }


# ==============================================================================
# 2. Required Fields Validation Node
# ==============================================================================


def check_required_fields(state: TripState) -> dict[str, Any]:
    """Verify presence of essential fields required to fulfill the classified intent."""
    missing: list[str] = []
    fields = dict(state.known_fields)
    intent = state.intent

    if intent == Intent.DESTINATION_DISCOVERY:
        if not fields.get("destination"):
            missing.append("destination")

    elif intent in (Intent.WEATHER_PLANNING, Intent.ITINERARY_PLANNING):
        if not fields.get("destination"):
            missing.append("destination")
        if not fields.get("start_date") or not fields.get("end_date"):
            missing.append("dates")
        if intent == Intent.ITINERARY_PLANNING and not fields.get("origin"):
            fields["origin"] = "Current Location"

    # Construct validated TripRequest if all parameters present
    trip_req: TripRequest | None = None
    if not missing and intent == Intent.ITINERARY_PLANNING:
        try:
            trip_req = TripRequest.model_validate(
                {
                    "origin": fields.get("origin", "Current Location"),
                    "destination": fields["destination"],
                    "start_date": fields["start_date"],
                    "end_date": fields["end_date"],
                    "party_size": int(fields.get("party_size", 1)),
                    "budget_amount": fields.get("budget_amount"),
                    "currency": fields.get("currency", "USD"),
                    "interests": fields.get("interests", ["general_sightseeing"]),
                    "pace": fields.get("pace", "balanced"),
                },
                context={"today": date.fromisoformat(fields["start_date"])},
            )
        except Exception:
            trip_req = None

    if missing:
        next_status = RunStatus.NEEDS_CLARIFICATION
    elif intent == Intent.UNSUPPORTED:
        next_status = RunStatus.FAILED
    else:
        next_status = RunStatus.PARTIAL

    return {
        "step_count": state.step_count + 1,
        "missing_fields": missing,
        "known_fields": fields,
        "trip_request": trip_req,
        "status": next_status,
    }


# ==============================================================================
# 3. Clarification Seam Placeholder Node (Completed in Prompt 17)
# ==============================================================================


def ask_clarification(
    state: TripState,
    gateway: ModelGateway | None = None,
) -> dict[str, Any]:
    """Format single targeted clarification question for missing required fields.

    NOTE: Completed in Prompt 17. Safely returns question identifying missing fields.
    """
    active_gateway = gateway or RuleBasedGateway()
    question = active_gateway.generate_clarification(
        state.missing_fields,
        context=state.known_fields,
    )

    return {
        "step_count": state.step_count + 1,
        "clarification_question": question,
        "status": RunStatus.NEEDS_CLARIFICATION,
    }


# ==============================================================================
# 4. Tool Planning Node
# ==============================================================================


def plan_tool_calls(state: TripState) -> dict[str, Any]:
    """Select and schedule tool invocations based strictly on classified intent."""
    planned: list[ToolCall] = []
    fields = state.known_fields
    destination = fields.get("destination", "")

    # 1. Destination discovery intent: geocode only
    if state.intent == Intent.DESTINATION_DISCOVERY:
        if destination:
            planned.append(
                ToolCall(
                    tool_name="geocode_destination",
                    arguments={"query": destination},
                )
            )

    # 2. Weather & Itinerary planning: geocode then weather
    elif state.intent in (Intent.WEATHER_PLANNING, Intent.ITINERARY_PLANNING):
        if destination:
            planned.append(
                ToolCall(
                    tool_name="geocode_destination",
                    arguments={"query": destination},
                )
            )
            # Weather call scheduled; coordinates populated after geocode in execution
            if fields.get("start_date") and fields.get("end_date"):
                planned.append(
                    ToolCall(
                        tool_name="get_weather",
                        arguments={
                            "latitude": 0.0,
                            "longitude": 0.0,
                            "start_date": fields["start_date"],
                            "end_date": fields["end_date"],
                        },
                    )
                )

    # 3. Unsupported intent: zero tools
    elif state.intent == Intent.UNSUPPORTED:
        planned = []

    return {
        "step_count": state.step_count + 1,
        "planned_tool_calls": planned,
    }


# ==============================================================================
# 5. Tool Execution Node
# ==============================================================================


def execute_tools(
    state: TripState,
    tools: dict[str, Any] | None = None,
    max_tool_calls: int = MAX_TOOL_CALLS,
) -> dict[str, Any]:
    """Execute planned tools sequentially up to MAX_TOOL_CALLS without looping.

    Stops planning weather if geocoding did not return a usable location.
    """
    active_tools = tools if tools is not None else TOOL_REGISTRY
    results: list[ToolResult] = list(state.tool_results)
    warnings: list[str] = list(state.warnings)

    last_geocode_res: ToolResult | None = None
    executed_count = 0

    for call in state.planned_tool_calls:
        if executed_count >= max_tool_calls:
            warnings.append(
                f"Tool execution capped by MAX_TOOL_CALLS limit ({max_tool_calls})."
            )
            break

        # Dependency check: weather tool requires valid geocoded coordinates
        if call.tool_name == "get_weather":
            if (
                last_geocode_res is None
                or last_geocode_res.status != ToolStatus.OK
                or not last_geocode_res.data
            ):
                # Geocoding failed or returned empty; stop planning/executing weather
                warnings.append(
                    "Weather forecast skipped: geocoding did not resolve "
                    "a usable location."
                )
                continue

            # Populate resolved coordinates from first candidate location
            candidates = last_geocode_res.data
            first_candidate = (
                candidates[0] if isinstance(candidates, list) else candidates
            )
            call.arguments["latitude"] = first_candidate["latitude"]
            call.arguments["longitude"] = first_candidate["longitude"]

        # Execute registered tool
        tool_impl = active_tools.get(call.tool_name)
        if tool_impl is None:
            results.append(
                ToolResult(
                    tool_name=call.tool_name,
                    status=ToolStatus.ERROR,
                    error_code=ToolErrorCode.NOT_FOUND,
                    safe_message=f"Tool '{call.tool_name}' is not registered.",
                    data_origin="none",
                )
            )
            executed_count += 1
            continue

        try:
            if hasattr(tool_impl, "invoke"):
                res = tool_impl.invoke(call.arguments)
            elif callable(tool_impl):
                res = tool_impl(call.arguments)
            else:
                raise TypeError(f"Tool '{call.tool_name}' is not callable.")

            if isinstance(res, ToolResult):
                results.append(res)
                if call.tool_name == "geocode_destination":
                    last_geocode_res = res
            else:
                results.append(
                    ToolResult(
                        tool_name=call.tool_name,
                        status=ToolStatus.OK,
                        data=res if isinstance(res, (dict, list)) else {"result": res},
                        data_origin="none",
                    )
                )
        except Exception as err:
            results.append(
                ToolResult(
                    tool_name=call.tool_name,
                    status=ToolStatus.ERROR,
                    error_code=ToolErrorCode.EXECUTION_FAILED,
                    safe_message=f"Error executing tool '{call.tool_name}': {err}",
                    data_origin="none",
                )
            )

        executed_count += 1

    return {
        "step_count": state.step_count + 1,
        "tool_results": results,
        "warnings": warnings,
    }


# ==============================================================================
# 6. Itinerary Drafting Node
# ==============================================================================


def draft_itinerary(state: TripState) -> dict[str, Any]:
    """Synthesize structured itinerary using the Phase 2 deterministic engine.

    Only passes weather when its ToolResult status is 'ok'.
    """
    trip_req = state.trip_request
    if trip_req is None:
        fields = state.known_fields
        if (
            fields.get("destination")
            and fields.get("start_date")
            and fields.get("end_date")
        ):
            try:
                trip_req = TripRequest.model_validate(
                    {
                        "origin": fields.get("origin", "Current Location"),
                        "destination": fields["destination"],
                        "start_date": fields["start_date"],
                        "end_date": fields["end_date"],
                        "party_size": int(fields.get("party_size", 1)),
                        "interests": fields.get("interests", ["general_sightseeing"]),
                        "pace": fields.get("pace", "balanced"),
                    },
                    context={"today": date.fromisoformat(fields["start_date"])},
                )
            except Exception:
                trip_req = None

    if trip_req is None:
        return {
            "step_count": state.step_count + 1,
            "warnings": list(state.warnings)
            + ["Could not draft itinerary: trip request parameters incomplete."],
        }

    # Extract destination GeocodeResult if available
    geo_res = next(
        (
            r
            for r in state.tool_results
            if r.tool_name == "geocode_destination" and r.status == ToolStatus.OK
        ),
        None,
    )
    dest_arg: GeocodeResult | str = trip_req.destination
    if geo_res and geo_res.data:
        try:
            candidates = geo_res.data
            first_cand = candidates[0] if isinstance(candidates, list) else candidates
            dest_arg = GeocodeResult.model_validate(first_cand)
        except Exception:
            dest_arg = trip_req.destination

    # Extract weather summary ONLY when ToolResult status is 'ok'
    weather_res = next(
        (
            r
            for r in state.tool_results
            if r.tool_name == "get_weather" and r.status == ToolStatus.OK
        ),
        None,
    )
    weather_arg: WeatherSummary | None = None
    if weather_res and weather_res.data:
        try:
            weather_arg = WeatherSummary.model_validate(weather_res.data)
        except Exception:
            weather_arg = None

    draft = generate_itinerary(
        request=trip_req,
        destination=dest_arg,
        weather=weather_arg,
    )

    return {
        "step_count": state.step_count + 1,
        "trip_request": trip_req,
        "itinerary_draft": draft,
    }


# ==============================================================================
# 7. Validation Placeholder Node (Completed in Prompt 18)
# ==============================================================================


def validate_itinerary(state: TripState) -> dict[str, Any]:
    """Validate synthesized itinerary against pacing and constraint rules.

    NOTE: Completed in Prompt 18. Passes through and records validation skipped.
    """
    return {
        "step_count": state.step_count + 1,
        "warnings": list(state.warnings)
        + ["Itinerary validation did not run (placeholder completed in Prompt 18)."],
    }


# ==============================================================================
# 8. Response Packaging Node
# ==============================================================================


def respond(
    state: TripState,
    max_steps: int = 25,
) -> dict[str, Any]:
    """Package final output envelope and assign terminal workflow run status."""
    warnings = list(state.warnings)

    # 1. Step count guard trigger
    if state.step_count >= max_steps:
        warnings.append(
            f"Execution halted: step count guard exceeded threshold ({max_steps})."
        )
        return {
            "step_count": state.step_count + 1,
            "status": RunStatus.FAILED,
            "warnings": warnings,
        }

    # 2. Unsupported intent (strict non-booking boundary)
    if state.intent == Intent.UNSUPPORTED:
        warnings.append(
            "Request cannot be fulfilled: flight/hotel bookings and "
            "transactions are out of scope."
        )
        return {
            "step_count": state.step_count + 1,
            "status": RunStatus.FAILED,
            "warnings": warnings,
        }

    # 3. Needs clarification
    if state.missing_fields or state.clarification_question:
        return {
            "step_count": state.step_count + 1,
            "status": RunStatus.NEEDS_CLARIFICATION,
            "warnings": warnings,
        }

    # 4. Successful itinerary planning
    if state.itinerary_draft is not None and state.trip_request is not None:
        sources = [r.source for r in state.tool_results if r.source is not None]
        weather_res = next(
            (
                r
                for r in state.tool_results
                if r.tool_name == "get_weather" and r.status == ToolStatus.OK
            ),
            None,
        )
        weather_summary: WeatherSummary | None = None
        if weather_res and weather_res.data:
            try:
                weather_summary = WeatherSummary.model_validate(weather_res.data)
            except Exception:
                pass

        trip_response = TripResponse(
            id=uuid4(),
            request=state.trip_request,
            itinerary=state.itinerary_draft,
            weather=weather_summary,
            sources=sources,
            warnings=warnings,
            created_at=datetime.now(UTC),
        )
        return {
            "step_count": state.step_count + 1,
            "status": RunStatus.COMPLETED,
            "final_response": trip_response,
            "warnings": warnings,
        }

    # 5. Successful destination discovery
    if state.intent == Intent.DESTINATION_DISCOVERY:
        return {
            "step_count": state.step_count + 1,
            "status": RunStatus.COMPLETED,
            "warnings": warnings,
        }

    # Fallback status
    return {
        "step_count": state.step_count + 1,
        "status": state.status,
        "warnings": warnings,
    }
