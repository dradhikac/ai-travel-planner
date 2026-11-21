"""Pure-ish workflow execution nodes for the Phase 3 LangGraph state machine.

Each node takes TripState (and optional dependencies) and returns a dictionary of
state mutations to be applied by LangGraph. Nodes enforce strict execution bounds,
step guards, provenance attribution, safe clarification handling, and failure policies.
"""

import time
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from app.agent.errors import ToolErrorCode
from app.agent.gateway import ModelGateway, RuleBasedGateway, get_default_gateway
from app.agent.partial import build_safe_partial_result
from app.agent.state import Intent, RunStatus, TripState
from app.agent.tools.contracts import ToolCall, ToolResult, ToolStatus
from app.agent.tools.registry import TOOL_REGISTRY
from app.agent.validation import (
    ValidationSeverity,
    has_critical,
)
from app.agent.validation import (
    validate_itinerary as run_itinerary_validation,
)
from app.core.config import MAX_TOOL_CALLS, Settings, get_settings
from app.core.logging import (
    emit_event,
    emit_tool_call_finished,
    reset_current_tool,
    reset_in_execute_tools,
    set_current_tool,
    set_in_execute_tools,
)
from app.schemas.itinerary_v2 import parse_itinerary_payload
from app.schemas.provider import GeocodeResult, WeatherSummary
from app.schemas.trip import ToolActivity, TripRequest, TripResponse
from app.services.itinerary import generate_itinerary

# Ensure clean class-level initialization of TripRequest reference date
TripRequest.set_test_today(None)


# ==============================================================================
# Helper Functions: URL Sanitization & Tool Activity Auditing
# ==============================================================================


def sanitize_url(raw_url: str | None) -> str | None:
    """Strip query strings and fragments from URLs to prevent leaking parameters."""
    if not raw_url:
        return None
    return raw_url.split("?")[0].split("#")[0].strip()


def build_tool_activity(
    tool_results: list[ToolResult],
    planned_calls: list[ToolCall] | None = None,
    known_fields: dict[str, Any] | None = None,
) -> list[ToolActivity]:
    """Build sanitized human-readable audit entries for client UI."""
    fields = known_fields or {}
    destination = fields.get("destination", "destination")
    activity: list[ToolActivity] = []
    executed_tool_names = set()

    for res in tool_results:
        executed_tool_names.add(res.tool_name)
        if res.tool_name == "geocode_destination":
            label = "Destination Geocoding"
            explanation = f"Resolved geographical coordinates for {destination}."
        elif res.tool_name == "get_weather":
            label = "Weather Forecast"
            explanation = "Retrieved daily meteorological forecast for trip dates."
        elif res.tool_name == "get_route_context":
            label = "Route Context"
            explanation = "Calculated travel distance and estimated transit time."
        else:
            label = res.tool_name.replace("_", " ").title()
            explanation = f"Executed {label} for travel planning."

        if res.status == ToolStatus.SKIPPED and res.safe_message:
            explanation = res.safe_message

        source_name = "Internal"
        if res.source:
            provider = res.source.provider or "External Provider"
            clean_url = sanitize_url(res.source.url)
            if clean_url and clean_url != provider:
                source_name = f"{provider} ({clean_url})"
            else:
                source_name = provider
        elif "geocode" in res.tool_name or "weather" in res.tool_name:
            source_name = "Open-Meteo"
        elif "route" in res.tool_name:
            source_name = "OpenRouteService"

        status_val = res.status.value
        data_origin = (
            res.data_origin
            if res.status in (ToolStatus.OK, ToolStatus.EMPTY)
            else "none"
        )

        activity.append(
            ToolActivity(
                tool_label=label,
                status=status_val,
                source=source_name,
                fetched_at=res.fetched_at,
                data_origin=data_origin,
                explanation=explanation,
            )
        )

    if planned_calls:
        for call in planned_calls:
            if call.tool_name not in executed_tool_names:
                if call.tool_name == "get_weather":
                    label = "Weather Forecast"
                    explanation = (
                        "Weather forecast skipped: geocoding did not resolve "
                        "a usable location."
                    )
                    source_name = "Open-Meteo"
                elif call.tool_name == "get_route_context":
                    label = "Route Context"
                    explanation = (
                        "Route calculation skipped: location coordinates "
                        "could not be resolved."
                    )
                    source_name = "OpenRouteService"
                elif call.tool_name == "geocode_destination":
                    label = "Destination Geocoding"
                    explanation = "Geocoding was scheduled but skipped."
                    source_name = "Open-Meteo"
                else:
                    label = call.tool_name.replace("_", " ").title()
                    explanation = f"{label} was scheduled but skipped."
                    source_name = "Internal"
                activity.append(
                    ToolActivity(
                        tool_label=label,
                        status="skipped",
                        source=source_name,
                        fetched_at=None,
                        data_origin="none",
                        explanation=explanation,
                    )
                )

    return activity


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

    # Classify user planning intent if not explicitly set to a non-default intent
    intent = state.intent
    if intent == Intent.ITINERARY_PLANNING:
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
    """Verify presence and validity of essential travel planning parameters.

    Essential fields for itinerary planning: origin, destination, start_date,
    end_date, party_size. Missing or contradictory parameters trigger clarification.
    Safe defaults are permitted ONLY for pace (balanced), interests (empty list),
    and budget (None), and are announced in warnings.
    """
    missing: list[str] = []
    contradictions: list[str] = []
    warnings: list[str] = list(state.warnings)
    fields = dict(state.known_fields)
    intent = state.intent

    if intent == Intent.DESTINATION_DISCOVERY:
        if not fields.get("destination") or not str(fields["destination"]).strip():
            missing.append("destination")

    elif intent == Intent.WEATHER_PLANNING:
        if not fields.get("destination") or not str(fields["destination"]).strip():
            missing.append("destination")
        has_start = bool(fields.get("start_date") and str(fields["start_date"]).strip())
        has_end = bool(fields.get("end_date") and str(fields["end_date"]).strip())
        if not has_start and not has_end:
            missing.append("dates")
        elif not has_start:
            missing.append("start_date")
        elif not has_end:
            missing.append("end_date")
        else:
            try:
                sd = date.fromisoformat(str(fields["start_date"]))
                ed = date.fromisoformat(str(fields["end_date"]))
                if ed < sd:
                    contradictions.append(
                        "Return date cannot be earlier than departure date"
                    )
            except (ValueError, TypeError):
                contradictions.append(
                    "Travel dates must be valid ISO dates (YYYY-MM-DD)"
                )

    elif intent == Intent.ROUTE_PLANNING:
        if not fields.get("destination") or not str(fields["destination"]).strip():
            missing.append("destination")
        if not fields.get("route_from") or not str(fields["route_from"]).strip():
            missing.append("route_from")
        if not fields.get("route_to") or not str(fields["route_to"]).strip():
            missing.append("route_to")

        # Contradiction: starting location equals arrival destination
        if fields.get("route_from") and fields.get("route_to"):
            from_str = str(fields["route_from"]).strip()
            to_str = str(fields["route_to"]).strip()
            if from_str.casefold() == to_str.casefold():
                contradictions.append(
                    "Starting location and arrival destination cannot be identical"
                )

        # Mode normalization and default announcement
        if not fields.get("route_mode") or str(fields["route_mode"]).strip() == "":
            fields["route_mode"] = "walking"
            mode_msg = (
                "Transit mode was not specified; defaulted to walking directions."
            )
            if mode_msg not in warnings:
                warnings.append(mode_msg)
        else:
            mode_raw = str(fields["route_mode"]).strip().lower()
            if mode_raw in ("walk", "walking", "foot"):
                fields["route_mode"] = "walking"
            elif mode_raw in ("bike", "biking", "cycle", "cycling", "bicycle"):
                fields["route_mode"] = "cycling"
            elif mode_raw in ("drive", "driving", "car"):
                fields["route_mode"] = "driving"
            else:
                fields["route_mode"] = "walking"
                mode_fallback_msg = (
                    f"Transit mode '{mode_raw}' is not supported; "
                    "defaulted to walking directions."
                )
                if mode_fallback_msg not in warnings:
                    warnings.append(mode_fallback_msg)

    elif intent == Intent.ITINERARY_PLANNING:
        # Check essential fields: origin, destination, dates, party_size
        if not fields.get("destination") or not str(fields["destination"]).strip():
            missing.append("destination")
        if not fields.get("origin") or not str(fields["origin"]).strip():
            missing.append("origin")

        has_start = bool(fields.get("start_date") and str(fields["start_date"]).strip())
        has_end = bool(fields.get("end_date") and str(fields["end_date"]).strip())
        if not has_start and not has_end:
            missing.append("dates")
        elif not has_start:
            missing.append("start_date")
        elif not has_end:
            missing.append("end_date")

        if fields.get("party_size") is None or str(fields["party_size"]).strip() == "":
            missing.append("party_size")

        # Contradiction: Origin equals Destination
        if fields.get("origin") and fields.get("destination"):
            orig_str = str(fields["origin"]).strip()
            dest_str = str(fields["destination"]).strip()
            if orig_str.casefold() == dest_str.casefold():
                contradictions.append("Origin and destination cannot be identical")

        # Contradiction: Date boundaries & ordering
        if has_start and has_end:
            try:
                sd = date.fromisoformat(str(fields["start_date"]))
                ed = date.fromisoformat(str(fields["end_date"]))
                if ed < sd:
                    contradictions.append(
                        "Return date cannot be earlier than departure date"
                    )
                else:
                    duration = (ed - sd).days + 1
                    if duration > 30:
                        contradictions.append(
                            f"Trip duration ({duration} days) exceeds "
                            "maximum limit of 30 days"
                        )
                    ref_today = TripRequest.get_today()
                    if sd < ref_today:
                        contradictions.append("Trip start date cannot be in the past")
            except (ValueError, TypeError):
                contradictions.append(
                    "Travel dates must be valid ISO dates (YYYY-MM-DD)"
                )
        elif has_start:
            try:
                sd = date.fromisoformat(str(fields["start_date"]))
                ref_today = TripRequest.get_today()
                if sd < ref_today:
                    contradictions.append("Trip start date cannot be in the past")
            except (ValueError, TypeError):
                contradictions.append(
                    "Start date must be a valid ISO date (YYYY-MM-DD)"
                )
        elif has_end:
            try:
                date.fromisoformat(str(fields["end_date"]))
            except (ValueError, TypeError):
                contradictions.append("End date must be a valid ISO date (YYYY-MM-DD)")

        # Contradiction: Party size validity
        if (
            fields.get("party_size") is not None
            and str(fields["party_size"]).strip() != ""
        ):
            try:
                ps = int(fields["party_size"])
                if ps < 1:
                    contradictions.append("Party size must be at least 1 traveler")
                elif ps > 20:
                    contradictions.append("Party size cannot exceed 20 travelers")
                else:
                    fields["party_size"] = ps
            except (ValueError, TypeError):
                contradictions.append("Party size must be a valid whole number")

        # SAFE DEFAULTS: Only allowed for pace, interests, and budget
        # 1. Pace
        if not fields.get("pace") or str(fields["pace"]).strip() == "":
            fields["pace"] = "balanced"
            pace_msg = "Travel pace was not specified; defaulted to balanced pace."
            if pace_msg not in warnings:
                warnings.append(pace_msg)

        # 2. Interests
        if (
            "interests" not in fields
            or fields["interests"] is None
            or not fields["interests"]
        ):
            fields["interests"] = []
            interests_msg = (
                "Travel interests were not specified; defaulting to general "
                "recommendations."
            )
            if interests_msg not in warnings:
                warnings.append(interests_msg)

        # 3. Budget
        if fields.get("budget_amount") is None:
            fields["budget_amount"] = None
            fields["currency"] = None
            budget_msg = "Budget was not specified; estimated costs will be unknown."
            if budget_msg not in warnings:
                warnings.append(budget_msg)

    # Construct validated TripRequest if all parameters present and non-contradictory
    trip_req: TripRequest | None = None
    if not missing and not contradictions and intent == Intent.ITINERARY_PLANNING:
        try:
            start_date_obj = date.fromisoformat(str(fields["start_date"]))
            trip_req = TripRequest.model_validate(
                {
                    "origin": fields["origin"],
                    "destination": fields["destination"],
                    "start_date": fields["start_date"],
                    "end_date": fields["end_date"],
                    "party_size": int(fields["party_size"]),
                    "budget_amount": fields.get("budget_amount"),
                    "currency": fields.get("currency"),
                    "interests": fields.get("interests", []),
                    "pace": fields.get("pace", "balanced"),
                },
                context={"today": start_date_obj},
            )
        except ValidationError as err:
            trip_req = None
            for e in err.errors():
                msg = e.get("msg", "Validation error")
                if msg not in contradictions:
                    contradictions.append(msg)
        except Exception:
            trip_req = None

    if missing or contradictions:
        next_status = RunStatus.NEEDS_CLARIFICATION
    elif intent == Intent.UNSUPPORTED:
        next_status = RunStatus.FAILED
    else:
        next_status = state.status

    return {
        "step_count": state.step_count + 1,
        "missing_fields": missing,
        "contradictions": contradictions,
        "known_fields": fields,
        "trip_request": trip_req,
        "status": next_status,
        "warnings": warnings,
    }


# ==============================================================================
# 3. Clarification Node
# ==============================================================================


def ask_clarification(
    state: TripState,
    gateway: ModelGateway | None = None,
) -> dict[str, Any]:
    """Format targeted question for missing or contradictory fields."""
    active_gateway = gateway or RuleBasedGateway()
    question = active_gateway.generate_clarification(
        missing_fields=state.missing_fields,
        contradictions=state.contradictions,
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


def is_route_tool_available(
    settings: Settings | None = None,
    tools: dict[str, Any] | None = None,
) -> bool:
    """Check whether routing capability is available and configured."""
    s = settings or get_settings()
    if tools is not None and "get_route_context" not in tools:
        return False
    if s.ROUTING_PROVIDER_MODE == "live" and not s.OPENROUTESERVICE_API_KEY:
        return False
    return True


def plan_tool_calls(
    state: TripState,
    settings: Settings | None = None,
    tools: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Select and schedule tool invocations based strictly on classified intent."""
    planned: list[ToolCall] = []
    tool_results: list[ToolResult] = list(state.tool_results)
    warnings: list[str] = list(state.warnings)
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

    # 2. Weather planning intent: geocode then weather
    elif state.intent == Intent.WEATHER_PLANNING:
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

    # 3. Route planning intent: geocode destination, geocode endpoints, route
    elif state.intent == Intent.ROUTE_PLANNING:
        route_from = fields.get("route_from", "")
        route_to = fields.get("route_to", "")
        mode = fields.get("route_mode", "walking")

        if destination:
            # 1. Geocode destination
            planned.append(
                ToolCall(
                    tool_name="geocode_destination",
                    arguments={"query": destination},
                )
            )
            # 2. Geocode starting point biased to destination
            if route_from:
                planned.append(
                    ToolCall(
                        tool_name="geocode_destination",
                        arguments={"query": f"{route_from}, {destination}"},
                    )
                )
            # 3. Geocode arrival point biased to destination
            if route_to:
                planned.append(
                    ToolCall(
                        tool_name="geocode_destination",
                        arguments={"query": f"{route_to}, {destination}"},
                    )
                )

            # 4. Route context (if available)
            if is_route_tool_available(settings=settings, tools=tools):
                planned.append(
                    ToolCall(
                        tool_name="get_route_context",
                        arguments={
                            "origin_lat": 0.0,
                            "origin_lon": 0.0,
                            "dest_lat": 0.0,
                            "dest_lon": 0.0,
                            "mode": mode,
                        },
                    )
                )
            else:
                # Unavailable tool: never planned; recorded as skipped: unavailable
                skipped_res = ToolResult(
                    tool_name="get_route_context",
                    status=ToolStatus.SKIPPED,
                    safe_message=(
                        "Routing capability is unavailable "
                        "(missing API key or disabled)."
                    ),
                    data_origin="none",
                )
                tool_results.append(skipped_res)
                emit_tool_call_finished(skipped_res, node="plan_tool_calls")
                unavailable_msg = "Routing capability is currently unavailable."
                if unavailable_msg not in warnings:
                    warnings.append(unavailable_msg)

    # 4. Itinerary planning: geocode, weather, and optional route pair
    elif state.intent == Intent.ITINERARY_PLANNING:
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

            # Route only if place pair is supplied
            route_from = fields.get("route_from")
            route_to = fields.get("route_to")
            if route_from and route_to:
                mode = fields.get("route_mode", "walking")
                planned.append(
                    ToolCall(
                        tool_name="geocode_destination",
                        arguments={"query": f"{route_from}, {destination}"},
                    )
                )
                planned.append(
                    ToolCall(
                        tool_name="geocode_destination",
                        arguments={"query": f"{route_to}, {destination}"},
                    )
                )
                if is_route_tool_available(settings=settings, tools=tools):
                    planned.append(
                        ToolCall(
                            tool_name="get_route_context",
                            arguments={
                                "origin_lat": 0.0,
                                "origin_lon": 0.0,
                                "dest_lat": 0.0,
                                "dest_lon": 0.0,
                                "mode": mode,
                            },
                        )
                    )
                else:
                    skipped_res = ToolResult(
                        tool_name="get_route_context",
                        status=ToolStatus.SKIPPED,
                        safe_message=(
                            "Routing capability is unavailable "
                            "(missing API key or disabled)."
                        ),
                        data_origin="none",
                    )
                    tool_results.append(skipped_res)
                    emit_tool_call_finished(skipped_res, node="plan_tool_calls")
                    unavailable_msg = "Routing capability is currently unavailable."
                    if unavailable_msg not in warnings:
                        warnings.append(unavailable_msg)

    # 5. Unsupported intent: zero tools
    elif state.intent == Intent.UNSUPPORTED:
        planned = []

    return {
        "step_count": state.step_count + 1,
        "planned_tool_calls": planned,
        "tool_results": tool_results,
        "warnings": warnings,
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

    Stops planning weather or routes if geocoding did not return a usable location.
    """
    active_tools = tools if tools is not None else TOOL_REGISTRY
    results: list[ToolResult] = list(state.tool_results)
    warnings: list[str] = list(state.warnings)

    dest_geo_res: ToolResult | None = None
    from_geo_res: ToolResult | None = None
    to_geo_res: ToolResult | None = None
    executed_count = 0

    fields = state.known_fields
    route_from = fields.get("route_from", "")
    route_to = fields.get("route_to", "")
    destination = fields.get("destination", "")

    for call in state.planned_tool_calls:
        if executed_count >= max_tool_calls:
            warnings.append(
                f"Tool execution capped by MAX_TOOL_CALLS limit ({max_tool_calls})."
            )
            break

        # Check if geocoding of endpoint should be skipped because destination failed
        if call.tool_name == "geocode_destination":
            query_val = str(call.arguments.get("query", ""))
            is_endpoint = (route_from and route_from in query_val) or (
                route_to and route_to in query_val
            )
            if (
                is_endpoint
                and dest_geo_res is not None
                and (dest_geo_res.status != ToolStatus.OK or not dest_geo_res.data)
            ):
                warnings.append(
                    "Place geocoding skipped: destination location "
                    "could not be resolved."
                )
                continue

        # Dependency check: weather tool requires valid geocoded coordinates
        if call.tool_name == "get_weather":
            if (
                dest_geo_res is None
                or dest_geo_res.status != ToolStatus.OK
                or not dest_geo_res.data
            ):
                # Geocoding failed or returned empty; stop planning/executing weather
                warnings.append(
                    "Weather forecast skipped: geocoding did not resolve "
                    "a usable location."
                )
                continue

            # Populate resolved coordinates from first candidate location
            candidates = dest_geo_res.data
            first_candidate = (
                candidates[0] if isinstance(candidates, list) else candidates
            )
            try:
                call.arguments["latitude"] = float(first_candidate["latitude"])
                call.arguments["longitude"] = float(first_candidate["longitude"])
            except (KeyError, TypeError, ValueError):
                err_res = ToolResult(
                    tool_name="get_weather",
                    status=ToolStatus.ERROR,
                    error_code=ToolErrorCode.MALFORMED_RESPONSE,
                    safe_message="Geocoding response missing coordinates.",
                    data_origin="none",
                )
                results.append(err_res)
                emit_tool_call_finished(err_res, node="execute_tools")
                executed_count += 1
                continue

        # Dependency check: route tool requires coordinates for both endpoints
        if call.tool_name == "get_route_context":
            if (
                from_geo_res is None
                or from_geo_res.status != ToolStatus.OK
                or not from_geo_res.data
            ):
                skipped_res = ToolResult(
                    tool_name="get_route_context",
                    status=ToolStatus.SKIPPED,
                    error_code=None,
                    safe_message=(
                        "Route calculation skipped: location coordinates "
                        "could not be resolved."
                    ),
                    data_origin="none",
                )
                results.append(skipped_res)
                emit_tool_call_finished(skipped_res, node="execute_tools")
                warnings.append(
                    "Route calculation skipped: starting location coordinates "
                    "could not be resolved."
                )
                executed_count += 1
                continue

            if (
                to_geo_res is None
                or to_geo_res.status != ToolStatus.OK
                or not to_geo_res.data
            ):
                skipped_res = ToolResult(
                    tool_name="get_route_context",
                    status=ToolStatus.SKIPPED,
                    error_code=None,
                    safe_message=(
                        "Route calculation skipped: location coordinates "
                        "could not be resolved."
                    ),
                    data_origin="none",
                )
                results.append(skipped_res)
                emit_tool_call_finished(skipped_res, node="execute_tools")
                warnings.append(
                    "Route calculation skipped: arrival destination coordinates "
                    "could not be resolved."
                )
                executed_count += 1
                continue

            from_cand = (
                from_geo_res.data[0]
                if isinstance(from_geo_res.data, list)
                else from_geo_res.data
            )
            to_cand = (
                to_geo_res.data[0]
                if isinstance(to_geo_res.data, list)
                else to_geo_res.data
            )
            try:
                call.arguments["origin_lat"] = float(from_cand["latitude"])
                call.arguments["origin_lon"] = float(from_cand["longitude"])
                call.arguments["dest_lat"] = float(to_cand["latitude"])
                call.arguments["dest_lon"] = float(to_cand["longitude"])
            except (KeyError, TypeError, ValueError):
                err_res = ToolResult(
                    tool_name="get_route_context",
                    status=ToolStatus.ERROR,
                    error_code=ToolErrorCode.MALFORMED_RESPONSE,
                    safe_message="Geocoding response missing coordinates.",
                    data_origin="none",
                )
                results.append(err_res)
                emit_tool_call_finished(err_res, node="execute_tools")
                executed_count += 1
                continue

        # Execute registered tool
        tool_impl = active_tools.get(call.tool_name)
        if tool_impl is None:
            not_found_res = ToolResult(
                tool_name=call.tool_name,
                status=ToolStatus.ERROR,
                error_code=ToolErrorCode.NOT_FOUND,
                safe_message=f"Tool '{call.tool_name}' is not registered.",
                data_origin="none",
            )
            results.append(not_found_res)
            emit_tool_call_finished(not_found_res, node="execute_tools")
            executed_count += 1
            continue

        tok_tool = set_current_tool(call.tool_name)
        tok_in_exec = set_in_execute_tools(True)
        t_tool_0 = time.perf_counter()
        try:
            if hasattr(tool_impl, "invoke"):
                res = tool_impl.invoke(call.arguments)
            elif callable(tool_impl):
                res = tool_impl(call.arguments)
            else:
                raise TypeError(f"Tool '{call.tool_name}' is not callable.")

            if isinstance(res, ToolResult):
                recorded_res = res
            else:
                recorded_res = ToolResult(
                    tool_name=call.tool_name,
                    status=ToolStatus.OK,
                    data=res if isinstance(res, (dict, list)) else {"result": res},
                    data_origin="none",
                )
            if recorded_res.latency_ms is None:
                recorded_res.latency_ms = max(
                    0.0, round((time.perf_counter() - t_tool_0) * 1000.0, 2)
                )
            results.append(recorded_res)
            emit_tool_call_finished(recorded_res, node="execute_tools")

            if call.tool_name == "geocode_destination":
                query_val = str(call.arguments.get("query", ""))
                if dest_geo_res is None and (
                    query_val == destination or (not route_from and not route_to)
                ):
                    dest_geo_res = recorded_res
                elif from_geo_res is None and route_from and route_from in query_val:
                    from_geo_res = recorded_res
                elif to_geo_res is None and route_to and route_to in query_val:
                    to_geo_res = recorded_res
                elif dest_geo_res is None:
                    dest_geo_res = recorded_res
                elif from_geo_res is None:
                    from_geo_res = recorded_res
                else:
                    to_geo_res = recorded_res

        except Exception as err:
            err_res = ToolResult(
                tool_name=call.tool_name,
                status=ToolStatus.ERROR,
                error_code=ToolErrorCode.EXECUTION_FAILED,
                safe_message=f"Error executing tool '{call.tool_name}': {err}",
                data_origin="none",
                latency_ms=max(
                    0.0, round((time.perf_counter() - t_tool_0) * 1000.0, 2)
                ),
            )
            results.append(err_res)
            emit_tool_call_finished(err_res, node="execute_tools")
        finally:
            reset_in_execute_tools(tok_in_exec)
            reset_current_tool(tok_tool)

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
            and fields.get("origin")
            and fields.get("start_date")
            and fields.get("end_date")
            and fields.get("party_size")
        ):
            try:
                trip_req = TripRequest.model_validate(
                    {
                        "origin": fields["origin"],
                        "destination": fields["destination"],
                        "start_date": fields["start_date"],
                        "end_date": fields["end_date"],
                        "party_size": int(fields["party_size"]),
                        "interests": fields.get("interests", []),
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

    draft = state.itinerary_draft or generate_itinerary(
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
# 7. Validation Node (Deterministic Rule Catalog)
# ==============================================================================


def validate_itinerary(state: TripState) -> dict[str, Any]:
    """Validate synthesized itinerary against deterministic validation rules."""
    if state.itinerary_draft is None:
        return {
            "step_count": state.step_count + 1,
            "validation_issues": ["No itinerary draft to validate."],
        }

    issues = run_itinerary_validation(
        state.itinerary_draft,
        request=state.trip_request,
        tool_results=state.tool_results,
    )
    formatted = [
        f"[{issue.severity.value.upper()}] {issue.code}: {issue.message}"
        for issue in issues
    ]
    new_warnings = list(state.warnings)
    if issues:
        critical_count = sum(
            1 for i in issues if i.severity == ValidationSeverity.CRITICAL
        )
        new_warnings.append(
            f"Itinerary validation identified {len(issues)} issue(s) "
            f"({critical_count} critical)."
        )

    return {
        "step_count": state.step_count + 1,
        "validation_issues": formatted,
        "warnings": new_warnings,
    }


# ==============================================================================
# 8. Itinerary Repair Node
# ==============================================================================


def repair_itinerary(
    state: TripState,
    gateway: ModelGateway | None = None,
) -> dict[str, Any]:
    """Execute bounded itinerary repair via model gateway.

    Strict security & privacy bounds:
    - Passes ONLY structured issues and minimal itinerary JSON to gateway.repair.
    - Never passes user message, request IDs, secrets, or raw provider payloads.
    - Treats gateway output as UNTRUSTED: checks payload size, parses schema,
      and re-validates. If unparseable or oversized, candidate is rejected and
      previous draft is retained.
    """
    if state.itinerary_draft is None:
        return {
            "step_count": state.step_count + 1,
            "repair_attempts": state.repair_attempts + 1,
        }

    active_gateway = gateway or get_default_gateway()
    current_issues = run_itinerary_validation(
        state.itinerary_draft,
        request=state.trip_request,
        tool_results=state.tool_results,
    )

    attempt_num = state.repair_attempts + 1
    issue_codes = [str(i.code) for i in current_issues]
    emit_event(
        "repair_attempt",
        node="repair_itinerary",
        attempt=attempt_num,
        issue_codes=issue_codes,
    )

    structured_issues = [
        {
            "code": str(i.code),
            "day_number": i.day_number,
            "activity_id": i.activity_id,
            "repair_hint": i.repair_hint,
            "severity": i.severity.value,
        }
        for i in current_issues
    ]

    minimal_itinerary = state.itinerary_draft.model_dump(mode="json")
    warnings = list(state.warnings)

    try:
        raw_repaired = active_gateway.repair(
            itinerary=minimal_itinerary,
            issues=structured_issues,
        )
        if getattr(active_gateway, "last_warning", None):
            warnings.append(active_gateway.last_warning)

        if isinstance(raw_repaired, str) and len(raw_repaired) > 250_000:
            warnings.append(
                "Repair output exceeded safety size bounds; candidate rejected."
            )
            repaired_draft = None
        elif isinstance(raw_repaired, str):
            import json

            parsed_dict = json.loads(raw_repaired)
            repaired_draft = parse_itinerary_payload(parsed_dict)
        elif isinstance(raw_repaired, dict):
            repaired_draft = parse_itinerary_payload(raw_repaired)
        else:
            repaired_draft = None
    except Exception:
        warnings.append(
            "Repair attempt produced invalid or unparseable output; "
            "retaining previous draft."
        )
        repaired_draft = None

    current_crit_sig = sorted(
        [
            f"{i.code}:{i.day_number}:{i.activity_id}"
            for i in current_issues
            if i.severity == ValidationSeverity.CRITICAL
        ]
    )

    return {
        "step_count": state.step_count + 1,
        "repair_attempts": state.repair_attempts + 1,
        "itinerary_draft": repaired_draft or state.itinerary_draft,
        "last_critical_issues": current_crit_sig,
        "warnings": warnings,
    }


# ==============================================================================
# 9. Safe Partial Result Node
# ==============================================================================


def build_partial_result_node(state: TripState) -> dict[str, Any]:
    """Construct a safe partial itinerary when repair attempts are exhausted."""
    current_issues = run_itinerary_validation(
        state.itinerary_draft,
        request=state.trip_request,
        tool_results=state.tool_results,
    )
    partial_draft, status, extra_warnings = build_safe_partial_result(
        state.itinerary_draft,
        request=state.trip_request,
        tool_results=state.tool_results,
        issues=current_issues,
    )
    new_warnings = list(state.warnings) + extra_warnings
    return {
        "step_count": state.step_count + 1,
        "itinerary_draft": partial_draft,
        "status": status,
        "is_partial": True,
        "warnings": new_warnings,
    }


# ==============================================================================
# 10. Response Packaging Node
# ==============================================================================


def respond(
    state: TripState,
    max_steps: int = 25,
) -> dict[str, Any]:
    """Package final output envelope and assign terminal workflow run status."""
    warnings = list(state.warnings)
    activity_entries = build_tool_activity(
        tool_results=state.tool_results,
        planned_calls=state.planned_tool_calls,
        known_fields=state.known_fields,
    )

    # 1. Step count guard trigger
    if state.step_count >= max_steps:
        warnings.append(
            f"Execution halted: step count guard exceeded threshold ({max_steps})."
        )
        return {
            "step_count": state.step_count + 1,
            "status": RunStatus.FAILED,
            "final_response": None,
            "warnings": warnings,
            "tool_activity": activity_entries,
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
            "final_response": None,
            "warnings": warnings,
            "tool_activity": activity_entries,
        }

    # 3. Needs clarification
    if state.missing_fields or state.contradictions or state.clarification_question:
        return {
            "step_count": state.step_count + 1,
            "status": RunStatus.NEEDS_CLARIFICATION,
            "final_response": None,
            "warnings": warnings,
            "tool_activity": activity_entries,
        }

    # 4. Tool Execution Failure Policy
    geo_res = next(
        (r for r in state.tool_results if r.tool_name == "geocode_destination"),
        None,
    )
    destination = state.known_fields.get("destination", "that location")

    if geo_res is not None:
        if geo_res.status == ToolStatus.EMPTY or (
            geo_res.status == ToolStatus.OK and not geo_res.data
        ):
            msg = (
                f"Could not find that destination ('{destination}'). "
                "Please check the spelling or try a more specific city and "
                "country name."
            )
            if msg not in warnings:
                warnings.append(msg)
            return {
                "step_count": state.step_count + 1,
                "status": RunStatus.FAILED,
                "final_response": None,
                "warnings": warnings,
                "tool_activity": activity_entries,
            }

        elif geo_res.status == ToolStatus.TIMEOUT:
            msg = (
                "Location search timed out while resolving destination coordinates. "
                "Please try again in a few moments."
            )
            if msg not in warnings:
                warnings.append(msg)
            return {
                "step_count": state.step_count + 1,
                "status": RunStatus.FAILED,
                "final_response": None,
                "warnings": warnings,
                "tool_activity": activity_entries,
            }

        elif geo_res.status == ToolStatus.RATE_LIMITED:
            msg = (
                "Location service rate limit reached. "
                "Please wait a moment and try your request again."
            )
            if msg not in warnings:
                warnings.append(msg)
            return {
                "step_count": state.step_count + 1,
                "status": RunStatus.FAILED,
                "final_response": None,
                "warnings": warnings,
                "tool_activity": activity_entries,
            }

        elif geo_res.status != ToolStatus.OK:
            msg = (
                "Destination lookup encountered a temporary error. "
                "Please try again later."
            )
            if msg not in warnings:
                warnings.append(msg)
            return {
                "step_count": state.step_count + 1,
                "status": RunStatus.FAILED,
                "final_response": None,
                "warnings": warnings,
                "tool_activity": activity_entries,
            }

    # 4b. Route Planning Outcome (when destination geocoding was ok)
    if state.intent == Intent.ROUTE_PLANNING:
        route_res = next(
            (r for r in state.tool_results if r.tool_name == "get_route_context"),
            None,
        )
        failed_endpoints = [
            r
            for r in state.tool_results
            if r.tool_name == "geocode_destination"
            and r != geo_res
            and (r.status != ToolStatus.OK or not r.data)
        ]

        if route_res is None or route_res.status != ToolStatus.OK or failed_endpoints:
            if route_res and route_res.status == ToolStatus.TIMEOUT:
                msg = "Route calculation timed out. Geocoded locations preserved."
            elif route_res and route_res.status == ToolStatus.SKIPPED:
                if "unavailable" in (route_res.safe_message or "").lower():
                    msg = (
                        "Routing capability is unavailable "
                        "(missing API key or disabled). Geocoded locations preserved."
                    )
                else:
                    msg = (
                        "Route calculation skipped: location coordinates "
                        "could not be resolved."
                    )
            elif route_res and (
                "auth" in str(route_res.error_code).lower()
                or (
                    route_res.safe_message
                    and (
                        "authentication" in route_res.safe_message.lower()
                        or "api key" in route_res.safe_message.lower()
                    )
                )
            ):
                msg = (
                    "Route calculation failed due to provider authentication error. "
                    "Geocoded locations preserved."
                )
            elif route_res and route_res.status == ToolStatus.EMPTY:
                msg = (
                    "No routable path found between locations. "
                    "Geocoded locations preserved."
                )
            else:
                msg = (
                    "Route calculation encountered an error. "
                    "Geocoded locations preserved."
                )

            if msg not in warnings:
                warnings.append(msg)

            return {
                "step_count": state.step_count + 1,
                "status": RunStatus.PARTIAL,
                "final_response": None,
                "warnings": warnings,
                "tool_activity": activity_entries,
            }

        # Route tool succeeded
        if route_res.data and isinstance(route_res.data, dict):
            dist = route_res.data.get("distance_km")
            dur = route_res.data.get("duration_minutes")
            mode = route_res.data.get("mode", "walking")
            if dist is not None and dur is not None:
                summary_msg = (
                    f"Retrieved {mode} route: {float(dist):.1f} km, "
                    f"~{float(dur):.0f} mins."
                )
                if summary_msg not in warnings:
                    warnings.append(summary_msg)

        return {
            "step_count": state.step_count + 1,
            "status": RunStatus.COMPLETED,
            "final_response": None,
            "warnings": warnings,
            "tool_activity": activity_entries,
        }

    # Check weather outcome (when geocoding was ok)
    weather_res = next(
        (r for r in state.tool_results if r.tool_name == "get_weather"),
        None,
    )
    weather_failed = False
    weather_summary: WeatherSummary | None = None

    if weather_res is not None:
        if weather_res.status == ToolStatus.OK and weather_res.data:
            try:
                weather_summary = WeatherSummary.model_validate(weather_res.data)
            except Exception:
                weather_summary = None
                weather_failed = True
                msg = (
                    "Weather forecast response was malformed; "
                    "itinerary generated without live weather."
                )
                if msg not in warnings:
                    warnings.append(msg)
        else:
            weather_failed = True
            if weather_res.status == ToolStatus.TIMEOUT:
                msg = (
                    "Weather forecast service timed out; "
                    "itinerary generated without live weather."
                )
            elif weather_res.status == ToolStatus.RATE_LIMITED:
                msg = (
                    "Weather forecast service is experiencing high demand; "
                    "itinerary generated without live weather."
                )
            elif (
                weather_res.error_code == ToolErrorCode.OUT_OF_FORECAST_RANGE
                or weather_res.status == ToolStatus.ERROR
            ):
                msg = (
                    "Weather forecast is unavailable for requested dates or location; "
                    "itinerary generated without live weather."
                )
            else:
                msg = (
                    "Weather forecast could not be retrieved; "
                    "itinerary generated without live weather."
                )
            if msg not in warnings:
                warnings.append(msg)

    # 5. Successful or Partial itinerary planning
    if state.itinerary_draft is not None and state.trip_request is not None:
        sources = [
            r.source
            for r in state.tool_results
            if r.status == ToolStatus.OK
            and r.source is not None
            and r.data_origin in ("live", "mock")
        ]

        # Final guard: NEVER return as COMPLETED if critical issues exist!
        current_issues = run_itinerary_validation(
            state.itinerary_draft,
            request=state.trip_request,
            tool_results=state.tool_results,
        )
        has_crit = has_critical(current_issues)

        route_res = next(
            (r for r in state.tool_results if r.tool_name == "get_route_context"),
            None,
        )
        route_failed = route_res is not None and route_res.status != ToolStatus.OK

        if has_crit:
            final_status = (
                RunStatus.FAILED
                if state.status == RunStatus.FAILED
                else RunStatus.PARTIAL
            )
        elif (
            route_failed
            or weather_failed
            or state.is_partial
            or state.status == RunStatus.PARTIAL
        ):
            final_status = RunStatus.PARTIAL
        elif state.status == RunStatus.FAILED:
            final_status = RunStatus.FAILED
        else:
            final_status = RunStatus.COMPLETED

        trip_response = TripResponse(
            id=uuid4(),
            request=state.trip_request,
            itinerary=state.itinerary_draft,
            weather=weather_summary if not weather_failed else None,
            sources=sources,
            tool_activity=activity_entries,
            warnings=warnings,
            metadata={
                "run_status": final_status.value,
                "repair_attempts": state.repair_attempts,
                "step_count": state.step_count,
                "validation_issues_count": len(state.validation_issues),
            },
            created_at=datetime.now(UTC),
        )

        return {
            "step_count": state.step_count + 1,
            "status": final_status,
            "final_response": trip_response,
            "warnings": warnings,
            "tool_activity": activity_entries,
        }

    # 6. Successful destination discovery
    if state.intent == Intent.DESTINATION_DISCOVERY:
        return {
            "step_count": state.step_count + 1,
            "status": RunStatus.COMPLETED,
            "warnings": warnings,
            "tool_activity": activity_entries,
        }

    # 7. Fallback status
    return {
        "step_count": state.step_count + 1,
        "status": state.status,
        "warnings": warnings,
        "tool_activity": activity_entries,
    }
