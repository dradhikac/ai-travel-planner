"""Pure-ish workflow execution nodes for the Phase 3 LangGraph state machine.

Each node takes TripState (and optional dependencies) and returns a dictionary of
state mutations to be applied by LangGraph. Nodes enforce strict execution bounds,
step guards, provenance attribution, safe clarification handling, and failure policies.
"""

from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from app.agent.errors import ToolErrorCode
from app.agent.gateway import ModelGateway, RuleBasedGateway
from app.agent.state import Intent, RunStatus, TripState
from app.agent.tools.contracts import ToolCall, ToolResult, ToolStatus
from app.agent.tools.registry import TOOL_REGISTRY
from app.core.config import MAX_TOOL_CALLS
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
        else:
            label = res.tool_name.replace("_", " ").title()
            explanation = f"Executed {label} for travel planning."

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
        next_status = RunStatus.PARTIAL

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
            try:
                call.arguments["latitude"] = float(first_candidate["latitude"])
                call.arguments["longitude"] = float(first_candidate["longitude"])
            except (KeyError, TypeError, ValueError):
                results.append(
                    ToolResult(
                        tool_name="get_weather",
                        status=ToolStatus.ERROR,
                        error_code=ToolErrorCode.MALFORMED_RESPONSE,
                        safe_message="Geocoding response missing coordinates.",
                        data_origin="none",
                    )
                )
                executed_count += 1
                continue

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

        trip_response = TripResponse(
            id=uuid4(),
            request=state.trip_request,
            itinerary=state.itinerary_draft,
            weather=weather_summary if not weather_failed else None,
            sources=sources,
            tool_activity=activity_entries,
            warnings=warnings,
            created_at=datetime.now(UTC),
        )

        final_status = RunStatus.PARTIAL if weather_failed else RunStatus.COMPLETED

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
