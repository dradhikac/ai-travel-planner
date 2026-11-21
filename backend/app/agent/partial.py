"""Safe partial result builder for AI Travel Concierge.

Constructs a safe partial itinerary when repair attempts are exhausted or
unresolvable constraint conflicts occur:
- Preserves valid days and activities
- Prunes or flags invalid activities with explanatory uncertainty notes
- Adds human-readable uncertainty notes explaining omissions without leaking internals
- Attaches sanitized validation issue codes
- Assigns RunStatus.PARTIAL (or RunStatus.FAILED if no valid days remain)
- Guarantees that an itinerary with critical issues is never marked completed
"""

from collections.abc import Sequence
from typing import Final

from app.agent.state import RunStatus
from app.agent.validation import (
    BANNED_BOOKING_REGEX,
    ValidationIssue,
    ValidationSeverity,
    has_critical,
    validate_itinerary,
)
from app.schemas.itinerary_v2 import (
    CostStatus,
    DurationBasis,
    DurationEstimate,
    ItineraryActivityV2,
    ItineraryDayV2,
    ItineraryV2,
    parse_itinerary_payload,
)
from app.schemas.provider import Provenance
from app.schemas.trip import TripRequest

FALLBACK_NOTE: Final[str] = (
    "Certain scheduled activities were omitted to preserve itinerary safety and "
    "validity."
)


def build_safe_partial_result(
    itinerary_or_payload: ItineraryV2 | dict | None,
    request: TripRequest | None = None,
    tool_results: Sequence | None = None,
    issues: Sequence[ValidationIssue] | None = None,
) -> tuple[ItineraryV2 | None, RunStatus, list[str]]:
    """Build a sanitized safe partial itinerary from an exhausted or degraded draft.

    Args:
        itinerary_or_payload: Source itinerary object or raw dictionary payload.
        request: Validated trip request intake context.
        tool_results: Sequence of tool execution results.
        issues: Optional pre-computed validation issues.

    Returns:
        Tuple of (partial_itinerary, terminal_status, sanitized_warning_strings).
    """
    if itinerary_or_payload is None:
        return (
            None,
            RunStatus.FAILED,
            ["Itinerary synthesis failed; no draft available."],
        )

    itinerary = parse_itinerary_payload(itinerary_or_payload)
    current_issues = list(
        issues
        if issues is not None
        else validate_itinerary(itinerary, request=request, tool_results=tool_results)
    )

    # Collect invalid activity IDs from critical issues
    invalid_activity_ids: set[str] = {
        i.activity_id
        for i in current_issues
        if i.severity == ValidationSeverity.CRITICAL and i.activity_id
    }

    # Scrub summary of prohibited booking language
    cleaned_summary = itinerary.summary
    if BANNED_BOOKING_REGEX.search(cleaned_summary):
        cleaned_summary = BANNED_BOOKING_REGEX.sub("suggested", cleaned_summary)

    valid_days: list[ItineraryDayV2] = []
    dropped_activities_count = 0

    start_date = request.start_date if request else None
    end_date = request.end_date if request else None

    for day in itinerary.days:
        # Prune days strictly outside trip date bounds
        if start_date and end_date:
            if day.date < start_date or day.date > end_date:
                continue

        # Filter out invalid activities
        kept_activities: list[ItineraryActivityV2] = []
        for act in day.activities:
            if act.id in invalid_activity_ids:
                dropped_activities_count += 1
                continue

            # Scrub booking words from title/description
            cleaned_title = act.title
            if BANNED_BOOKING_REGEX.search(cleaned_title):
                cleaned_title = BANNED_BOOKING_REGEX.sub("Visit", cleaned_title)

            cleaned_desc = act.description
            if cleaned_desc and BANNED_BOOKING_REGEX.search(cleaned_desc):
                cleaned_desc = BANNED_BOOKING_REGEX.sub("suggested", cleaned_desc)

            # Scrub cost note if it promises live prices
            cleaned_cost_note = act.cost_note
            cleaned_cost_status = act.cost_status
            if cleaned_cost_status == CostStatus.RETRIEVED and not act.source_refs:
                cleaned_cost_status = CostStatus.UNKNOWN

            kept_activities.append(
                act.model_copy(
                    update={
                        "title": cleaned_title,
                        "description": cleaned_desc,
                        "cost_note": cleaned_cost_note,
                        "cost_status": cleaned_cost_status,
                    }
                )
            )

        # Update day notes if activities were dropped
        day_notes = list(day.uncertainty_notes)
        if dropped_activities_count > 0:
            if FALLBACK_NOTE not in day_notes:
                day_notes.append(FALLBACK_NOTE)

        # If day has 0 activities left, insert a safe fallback exploration item
        if not kept_activities:
            kept_activities.append(
                ItineraryActivityV2(
                    id=f"day_{day.day_number}_act_fallback",
                    title="Free Exploration & Sightseeing",
                    description=(
                        "Flexible open time to explore local neighborhoods and "
                        "landmarks at your own pace."
                    ),
                    time_of_day="morning",
                    interest_tags=["relaxation"],
                    location=None,
                    duration_estimate=DurationEstimate(
                        min_minutes=60,
                        max_minutes=180,
                        basis=DurationBasis.HEURISTIC,
                    ),
                    source_refs=[],
                    provenance=Provenance.GENERATED_SUGGESTION,
                    cost_status=CostStatus.UNKNOWN,
                    cost_note=None,
                    uncertainty_notes=[
                        "Self-directed schedule; no commercial reservations required."
                    ],
                )
            )

        valid_days.append(
            day.model_copy(
                update={
                    "day_number": len(valid_days) + 1,
                    "activities": kept_activities,
                    "uncertainty_notes": day_notes,
                }
            )
        )

    if not valid_days:
        return (
            None,
            RunStatus.FAILED,
            ["No valid itinerary days could be preserved after validation failure."],
        )

    # Renumber days sequentially 1..N
    renumbered_days = [
        d.model_copy(update={"day_number": idx})
        for idx, d in enumerate(valid_days, start=1)
    ]

    # Collect critical issue codes for sanitized warning notice
    crit_codes = sorted(
        {
            str(i.code)
            for i in current_issues
            if i.severity == ValidationSeverity.CRITICAL
        }
    )
    extra_warnings = [
        "Itinerary was generated as a safe partial plan due to unresolved "
        "validation constraints."
    ]
    if crit_codes:
        extra_warnings.append(
            f"Validation constraints adjusted: {', '.join(crit_codes)}."
        )

    partial_itinerary = ItineraryV2(
        schema_version=2,
        summary=cleaned_summary,
        sources=list(itinerary.sources),
        warnings=list(itinerary.warnings) + extra_warnings,
        days=renumbered_days,
    )

    # Re-validate the constructed partial itinerary
    remaining_issues = validate_itinerary(
        partial_itinerary, request=request, tool_results=tool_results
    )
    if has_critical(remaining_issues):
        # Still has critical issues (e.g. fatal intake contradiction)
        return partial_itinerary, RunStatus.FAILED, extra_warnings

    return partial_itinerary, RunStatus.PARTIAL, extra_warnings
