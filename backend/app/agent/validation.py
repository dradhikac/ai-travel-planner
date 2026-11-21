"""Deterministic itinerary validation rules catalog, issue models, and registry.

Implements Phase 4 validation specifications from
docs/phase4-5/reliability-contracts.md:
- Rule registry with pure check functions:
  (itinerary, request, tool_results) -> issues
- Deterministic issue ordering (day_number, severity, code, activity_id, message)
- Message sanitization without user text echo beyond short titles
- Strict non-booking concierge policy enforcement (no booking/reservation claims)
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field

from app.agent.state import TripState
from app.agent.tools.contracts import ToolResult, ToolStatus
from app.schemas.itinerary_v2 import (
    CostStatus,
    ItineraryV2,
    parse_itinerary_payload,
)
from app.schemas.provider import Provenance
from app.schemas.trip import PacePreference, TripRequest

# ==============================================================================
# 1. Validation Enums & Data Models
# ==============================================================================


class ValidationSeverity(StrEnum):
    """Severity classification of validation issues."""

    CRITICAL = "critical"
    WARNING = "warning"


class ValidationCode(StrEnum):
    """Deterministic validation rule codes."""

    # Phase 4 core rules
    DATE_RANGE_MISMATCH = "DATE_RANGE_MISMATCH"
    DUPLICATE_ACTIVITY = "DUPLICATE_ACTIVITY"
    MAX_DAILY_ACTIVITIES = "MAX_DAILY_ACTIVITIES"
    MISSING_REQUIRED_INTEREST = "MISSING_REQUIRED_INTEREST"
    MISSING_SOURCE_METADATA = "MISSING_SOURCE_METADATA"
    BUDGET_FLOOR_VIOLATION = "BUDGET_FLOOR_VIOLATION"

    # Phase 3 truthfulness & safety rules
    MISSING_PROVENANCE = "MISSING_PROVENANCE"
    BOOKING_LANGUAGE_DETECTED = "BOOKING_LANGUAGE_DETECTED"
    WEATHER_WITHOUT_TOOL_SUCCESS = "WEATHER_WITHOUT_TOOL_SUCCESS"
    INVALID_COST_STATUS = "INVALID_COST_STATUS"


class ValidationIssue(BaseModel):
    """Normalized validation issue emitted by a rule check."""

    model_config = ConfigDict(extra="forbid")

    code: ValidationCode | str = Field(..., description="Validation rule code")
    severity: ValidationSeverity = Field(..., description="Issue severity")
    message: str = Field(..., description="Sanitized human-readable issue description")
    repair_hint: str = Field(
        ..., description="Deterministic automated repair suggestion"
    )
    day_number: int | None = Field(
        default=None, description="Affected day number if applicable"
    )
    activity_id: str | None = Field(
        default=None, description="Affected activity ID if applicable"
    )


# ==============================================================================
# 2. Shared Constants & Catalogs
# ==============================================================================

# Pace activity maximum caps (synchronized with app.services.itinerary)
# Generators schedule strictly <= cap:
# (relaxed: 2 <= 3, balanced: 3 <= 4, packed: 4 <= 5)
PACE_ACTIVITY_CAPS: Final[dict[PacePreference, int]] = {
    PacePreference.RELAXED: 3,
    PacePreference.BALANCED: 4,
    PacePreference.PACKED: 5,
}
DEFAULT_PACE_CAP: Final[int] = 4

# Documented repeat categories exempt from DUPLICATE_ACTIVITY check
EXEMPT_REPEAT_TAGS: Final[frozenset[str]] = frozenset(
    {
        "food",
        "dining",
        "meal",
        "meals",
        "restaurant",
        "breakfast",
        "lunch",
        "dinner",
        "rest",
        "relaxation",
        "break",
        "free time",
    }
)

# Supported generic template interest categories in app.services.itinerary
SUPPORTED_TEMPLATE_INTERESTS: Final[frozenset[str]] = frozenset(
    {
        "food",
        "museums",
        "culture",
        "nature",
        "history",
        "outdoors",
        "nightlife",
        "shopping",
        "relaxation",
        "general",
    }
)

# Currency-specific daily hard floors per person
# Defined in docs/phase4-5/reliability-contracts.md
CURRENCY_HARD_FLOORS: Final[dict[str, Decimal]] = {
    "USD": Decimal("30.00"),
    "EUR": Decimal("30.00"),
    "GBP": Decimal("25.00"),
    "CAD": Decimal("40.00"),
    "AUD": Decimal("45.00"),
    "JPY": Decimal("4000"),
    "INR": Decimal("2000"),
    "CHF": Decimal("35.00"),
    "NZD": Decimal("50.00"),
    "SGD": Decimal("40.00"),
}

# Regex for prohibited booking/transaction language
BANNED_BOOKING_REGEX: Final[re.Pattern[str]] = re.compile(
    r"\b("
    r"booked|"
    r"booking confirmed|"
    r"confirmed booking|"
    r"reserved|"
    r"reservation confirmed|"
    r"confirmed reservation|"
    r"ticket purchased|"
    r"tickets purchased|"
    r"purchased ticket|"
    r"payment processed|"
    r"cancellation policy|"
    r"instant booking|"
    r"non-refundable|"
    r"ticketed|"
    r"paid reservation"
    r")\b",
    re.IGNORECASE,
)


# ==============================================================================
# 3. Message Sanitization & Normalization Helpers
# ==============================================================================


def sanitize_message_text(text: str, max_length: int = 50) -> str:
    """Sanitize and truncate text embedded in validation messages.

    Strips control characters, newlines, angle brackets, and backticks.
    Prevents prompt injection reflection or sensitive text leakage.
    """
    if not text:
        return ""
    cleaned = " ".join(text.split())
    cleaned = re.sub(r"[\r\n\t<>`]", " ", cleaned)
    cleaned = " ".join(cleaned.split())
    if len(cleaned) > max_length:
        return cleaned[: max_length - 3].rstrip() + "..."
    return cleaned


def _normalize_key(text: str) -> str:
    """Normalize a title or location string for deterministic comparison."""
    return " ".join(text.strip().split()).casefold()


# ==============================================================================
# 4. Pure Rule Check Implementations
# ==============================================================================


def check_date_range_mismatch(
    itinerary: ItineraryV2,
    request: TripRequest | None,
    tool_results: Sequence[ToolResult] | None,
) -> list[ValidationIssue]:
    """Rule 1: DATE_RANGE_MISMATCH (critical).

    Ensures exactly one day per date from start to end inclusive, no extra,
    missing, or duplicate dates, and sequential day_number 1..N.
    """
    issues: list[ValidationIssue] = []

    if not itinerary.days:
        return [
            ValidationIssue(
                code=ValidationCode.DATE_RANGE_MISMATCH,
                severity=ValidationSeverity.CRITICAL,
                message="Itinerary contains no scheduled days.",
                repair_hint="Generate days corresponding to the trip date range.",
            )
        ]

    # Check day_number sequence: strictly 1, 2, ..., N
    seen_day_numbers: set[int] = set()
    for idx, day in enumerate(itinerary.days, start=1):
        if day.day_number in seen_day_numbers:
            issues.append(
                ValidationIssue(
                    code=ValidationCode.DATE_RANGE_MISMATCH,
                    severity=ValidationSeverity.CRITICAL,
                    day_number=day.day_number,
                    message=(
                        f"Duplicate day_number {day.day_number} detected in itinerary."
                    ),
                    repair_hint="Renumber itinerary days sequentially 1..N.",
                )
            )
        seen_day_numbers.add(day.day_number)

        if day.day_number != idx:
            issues.append(
                ValidationIssue(
                    code=ValidationCode.DATE_RANGE_MISMATCH,
                    severity=ValidationSeverity.CRITICAL,
                    day_number=day.day_number,
                    message=(
                        f"Day at index {idx} has day_number {day.day_number}; "
                        f"expected {idx}."
                    ),
                    repair_hint="Renumber itinerary days sequentially 1..N.",
                )
            )

    # If request is provided, compare against explicit start_date and end_date
    if request is not None and request.start_date and request.end_date:
        start_date = request.start_date
        end_date = request.end_date
        expected_days_count = (end_date - start_date).days + 1

        if len(itinerary.days) != expected_days_count:
            issues.append(
                ValidationIssue(
                    code=ValidationCode.DATE_RANGE_MISMATCH,
                    severity=ValidationSeverity.CRITICAL,
                    message=(
                        f"Itinerary day count ({len(itinerary.days)}) does not match "
                        f"trip duration ({expected_days_count} days from {start_date} "
                        f"to {end_date})."
                    ),
                    repair_hint=(
                        "Align itinerary days exactly with requested date range."
                    ),
                )
            )

        seen_dates: set[date] = set()
        for idx, day in enumerate(itinerary.days):
            expected_date = start_date + timedelta(days=idx)
            if day.date in seen_dates:
                issues.append(
                    ValidationIssue(
                        code=ValidationCode.DATE_RANGE_MISMATCH,
                        severity=ValidationSeverity.CRITICAL,
                        day_number=day.day_number,
                        message=f"Duplicate date {day.date} on day {day.day_number}.",
                        repair_hint=(
                            "Ensure each day has a unique date within the trip range."
                        ),
                    )
                )
            seen_dates.add(day.date)

            if day.date < start_date or day.date > end_date:
                issues.append(
                    ValidationIssue(
                        code=ValidationCode.DATE_RANGE_MISMATCH,
                        severity=ValidationSeverity.CRITICAL,
                        day_number=day.day_number,
                        message=(
                            f"Day {day.day_number} date {day.date} is outside trip "
                            f"bounds [{start_date}, {end_date}]."
                        ),
                        repair_hint="Prune days outside the trip date bounds.",
                    )
                )
            elif day.date != expected_date:
                issues.append(
                    ValidationIssue(
                        code=ValidationCode.DATE_RANGE_MISMATCH,
                        severity=ValidationSeverity.CRITICAL,
                        day_number=day.day_number,
                        message=(
                            f"Day {day.day_number} date {day.date} does not match "
                            f"expected sequence date {expected_date}."
                        ),
                        repair_hint=(
                            "Reorder or re-date days so dates sequence strictly from "
                            "start to end."
                        ),
                    )
                )
    else:
        # Request is None: ensure dates strictly advance by 1 day per step
        for i in range(1, len(itinerary.days)):
            prev_d = itinerary.days[i - 1]
            curr_d = itinerary.days[i]
            if curr_d.date <= prev_d.date:
                issues.append(
                    ValidationIssue(
                        code=ValidationCode.DATE_RANGE_MISMATCH,
                        severity=ValidationSeverity.CRITICAL,
                        day_number=curr_d.day_number,
                        message=(
                            f"Day {curr_d.day_number} date {curr_d.date} does not "
                            f"advance past day {prev_d.day_number} date {prev_d.date}."
                        ),
                        repair_hint="Sequence day dates strictly 1 day per day.",
                    )
                )

    return issues


def check_duplicate_activity(
    itinerary: ItineraryV2,
    request: TripRequest | None,
    tool_results: Sequence[ToolResult] | None,
) -> list[ValidationIssue]:
    """Rule 2: DUPLICATE_ACTIVITY (warning, critical if 3 or more duplicates).

    Detects normalized title + location key repeated across the itinerary.
    Documented repeat categories (meals, rest, dining) are exempt by tag/title.
    """
    seen: dict[tuple[str, str], list[tuple[int, str, str]]] = {}
    duplicate_instances: list[tuple[int, str, str, tuple[str, str]]] = []

    for day in itinerary.days:
        for act in day.activities:
            # Check if exempt by tags
            is_exempt = any(
                _normalize_key(tag) in EXEMPT_REPEAT_TAGS for tag in act.interest_tags
            )
            norm_title = _normalize_key(act.title)
            # Check if title itself represents a generic meal or rest activity
            if norm_title in EXEMPT_REPEAT_TAGS:
                is_exempt = True

            if is_exempt:
                continue

            loc_name = ""
            if act.location and act.location.name:
                loc_name = _normalize_key(act.location.name)

            key = (norm_title, loc_name)
            if key in seen:
                duplicate_instances.append((day.day_number, act.id, act.title, key))
                seen[key].append((day.day_number, act.id, act.title))
            else:
                seen[key] = [(day.day_number, act.id, act.title)]

    if not duplicate_instances:
        return []

    # 1-2 duplicates = WARNING; 3 or more duplicates = CRITICAL
    severity = (
        ValidationSeverity.CRITICAL
        if len(duplicate_instances) >= 3
        else ValidationSeverity.WARNING
    )

    issues: list[ValidationIssue] = []
    for day_num, act_id, title, _ in duplicate_instances:
        sanitized_title = sanitize_message_text(title, max_length=40)
        issues.append(
            ValidationIssue(
                code=ValidationCode.DUPLICATE_ACTIVITY,
                severity=severity,
                day_number=day_num,
                activity_id=act_id,
                message=(
                    f"Duplicate activity '{sanitized_title}' scheduled on "
                    f"day {day_num}."
                ),
                repair_hint=(
                    "Remove redundant activity and substitute with an alternative "
                    "activity matching traveler interests."
                ),
            )
        )

    return issues


def check_max_daily_activities(
    itinerary: ItineraryV2,
    request: TripRequest | None,
    tool_results: Sequence[ToolResult] | None,
) -> list[ValidationIssue]:
    """Rule 3: MAX_DAILY_ACTIVITIES (critical).

    Checks that daily activity counts do not exceed configured pace threshold:
    relaxed: 3, balanced: 4, packed: 5.
    """
    pace = (
        request.pace
        if request is not None and request.pace is not None
        else PacePreference.BALANCED
    )
    cap = PACE_ACTIVITY_CAPS.get(pace, DEFAULT_PACE_CAP)
    issues: list[ValidationIssue] = []

    for day in itinerary.days:
        count = len(day.activities)
        if count > cap:
            issues.append(
                ValidationIssue(
                    code=ValidationCode.MAX_DAILY_ACTIVITIES,
                    severity=ValidationSeverity.CRITICAL,
                    day_number=day.day_number,
                    message=(
                        f"Day {day.day_number} has {count} activities, "
                        f"exceeding the '{pace.value}' pace cap of {cap}."
                    ),
                    repair_hint=(
                        f"Prune lowest-priority activities on day {day.day_number} "
                        f"to meet the cap of {cap}."
                    ),
                )
            )

    return issues


def check_missing_required_interest(
    itinerary: ItineraryV2,
    request: TripRequest | None,
    tool_results: Sequence[ToolResult] | None,
) -> list[ValidationIssue]:
    """Rule 4: MISSING_REQUIRED_INTEREST (warning).

    Verifies each requested interest appears on at least one activity tag.
    Note: Interest synonyms are NOT guessed (exact tag match, documented).
    If no template supports an interest, records an uncertainty note instead of failing.
    """
    if request is None or not request.interests:
        return []

    # Collect all scheduled tags across the itinerary
    scheduled_tags: set[str] = set()
    for day in itinerary.days:
        for act in day.activities:
            for tag in act.interest_tags:
                scheduled_tags.add(_normalize_key(tag))

    issues: list[ValidationIssue] = []

    for raw_interest in request.interests:
        norm_interest = _normalize_key(raw_interest)
        if norm_interest not in scheduled_tags:
            sanitized_interest = sanitize_message_text(raw_interest, max_length=40)
            is_supported = norm_interest in SUPPORTED_TEMPLATE_INTERESTS

            if not is_supported:
                # Unsupported interest: record uncertainty note on itinerary
                note = (
                    "No curated activity templates available for requested "
                    f"interest: {sanitized_interest}"
                )
                if note not in itinerary.warnings:
                    itinerary.warnings.append(note)
                if itinerary.days and note not in itinerary.days[0].uncertainty_notes:
                    itinerary.days[0].uncertainty_notes.append(note)

                issues.append(
                    ValidationIssue(
                        code=ValidationCode.MISSING_REQUIRED_INTEREST,
                        severity=ValidationSeverity.WARNING,
                        message=(
                            "No templates support requested interest "
                            f"'{sanitized_interest}'; uncertainty note recorded."
                        ),
                        repair_hint=(
                            "Uncertainty note recorded for unsupported interest; "
                            "no generation repair required."
                        ),
                    )
                )
            else:
                # Supported template exists, but generator omitted it
                issues.append(
                    ValidationIssue(
                        code=ValidationCode.MISSING_REQUIRED_INTEREST,
                        severity=ValidationSeverity.WARNING,
                        message=(
                            f"Requested interest '{sanitized_interest}' "
                            "is not represented in any scheduled activity."
                        ),
                        repair_hint=(
                            "Substitute an activity with one tagged with "
                            f"'{sanitized_interest}'."
                        ),
                    )
                )

    return issues


def check_missing_source_metadata(
    itinerary: ItineraryV2,
    request: TripRequest | None,
    tool_results: Sequence[ToolResult] | None,
) -> list[ValidationIssue]:
    """Rule 5: MISSING_SOURCE_METADATA (critical).

    An activity with provenance 'retrieved' or cost_status 'retrieved' must have
    valid source_refs, each referencing a source that exists in root sources and
    possesses provider, fetched_at, attribution, and data_origin.
    """
    issues: list[ValidationIssue] = []
    sources = itinerary.sources or []

    for day in itinerary.days:
        for act in day.activities:
            needs_source = (
                act.provenance == Provenance.RETRIEVED
                or act.cost_status == CostStatus.RETRIEVED
            )
            if not needs_source:
                continue

            sanitized_title = sanitize_message_text(act.title, max_length=40)

            # Must have non-empty source_refs
            if not act.source_refs:
                issues.append(
                    ValidationIssue(
                        code=ValidationCode.MISSING_SOURCE_METADATA,
                        severity=ValidationSeverity.CRITICAL,
                        day_number=day.day_number,
                        activity_id=act.id,
                        message=(
                            f"Activity '{sanitized_title}' has retrieved status "
                            "but lacks source_refs."
                        ),
                        repair_hint=(
                            "Attach valid source_refs or downgrade provenance to "
                            "'generated_suggestion'."
                        ),
                    )
                )
                continue

            # Every source_ref must resolve to an existing SourceInfo with
            # complete metadata
            for ref in act.source_refs:
                matching_source = next(
                    (s for s in sources if s.url == ref or s.provider == ref),
                    None,
                )
                if matching_source is None:
                    issues.append(
                        ValidationIssue(
                            code=ValidationCode.MISSING_SOURCE_METADATA,
                            severity=ValidationSeverity.CRITICAL,
                            day_number=day.day_number,
                            activity_id=act.id,
                            message=(
                                f"Activity '{sanitized_title}' references source "
                                f"'{sanitize_message_text(ref, 40)}' which does "
                                "not exist in itinerary sources."
                            ),
                            repair_hint=(
                                "Add matching SourceInfo to root itinerary sources "
                                "or update source_refs."
                            ),
                        )
                    )
                else:
                    missing_meta: list[str] = []
                    if (
                        not matching_source.provider
                        or not matching_source.provider.strip()
                    ):
                        missing_meta.append("provider")
                    if matching_source.fetched_at is None:
                        missing_meta.append("fetched_at")
                    if (
                        not matching_source.attribution
                        or not matching_source.attribution.strip()
                    ):
                        missing_meta.append("attribution")
                    if matching_source.data_origin not in ("live", "mock"):
                        missing_meta.append("data_origin")

                    if missing_meta:
                        issues.append(
                            ValidationIssue(
                                code=ValidationCode.MISSING_SOURCE_METADATA,
                                severity=ValidationSeverity.CRITICAL,
                                day_number=day.day_number,
                                activity_id=act.id,
                                message=(
                                    f"Source for activity '{sanitized_title}' lacks "
                                    f"required metadata: {', '.join(missing_meta)}."
                                ),
                                repair_hint=(
                                    "Populate provider, fetched_at, attribution, and "
                                    "data_origin on SourceInfo."
                                ),
                            )
                        )

    return issues


def check_missing_provenance(
    itinerary: ItineraryV2,
    request: TripRequest | None,
    tool_results: Sequence[ToolResult] | None,
) -> list[ValidationIssue]:
    """Rule 6a: MISSING_PROVENANCE (critical, Phase 3).

    Ensures every scheduled activity has an explicit, valid Provenance classification.
    """
    issues: list[ValidationIssue] = []
    for day in itinerary.days:
        for act in day.activities:
            if act.provenance is None or not isinstance(act.provenance, Provenance):
                sanitized_title = sanitize_message_text(act.title, max_length=40)
                issues.append(
                    ValidationIssue(
                        code=ValidationCode.MISSING_PROVENANCE,
                        severity=ValidationSeverity.CRITICAL,
                        day_number=day.day_number,
                        activity_id=act.id,
                        message=(
                            f"Activity '{sanitized_title}' is missing a valid "
                            "Provenance classification."
                        ),
                        repair_hint=(
                            "Assign Provenance (e.g. generated_suggestion) to the "
                            "activity."
                        ),
                    )
                )
    return issues


def check_booking_language(
    itinerary: ItineraryV2,
    request: TripRequest | None,
    tool_results: Sequence[ToolResult] | None,
) -> list[ValidationIssue]:
    """Rule 6b: BOOKING_LANGUAGE_DETECTED (critical, Phase 3).

    Scans itinerary summary, day notes, and activities for prohibited transaction
    terms claiming bookings, reservations, paid tickets, or cancellation policies.
    """
    issues: list[ValidationIssue] = []

    def _scan_text(text: str | None) -> str | None:
        if not text:
            return None
        match = BANNED_BOOKING_REGEX.search(text)
        if match:
            # Exempt explicit non-booking disclaimers (e.g. "not booked")
            span_start = match.start()
            prefix = text[max(0, span_start - 12) : span_start].lower()
            if "not " in prefix or "non-" in prefix or "never " in prefix:
                return None
            return match.group(0)
        return None

    # Check summary
    banned = _scan_text(itinerary.summary)
    if banned:
        issues.append(
            ValidationIssue(
                code=ValidationCode.BOOKING_LANGUAGE_DETECTED,
                severity=ValidationSeverity.CRITICAL,
                message=(
                    f"Summary contains prohibited booking transaction term '{banned}'."
                ),
                repair_hint=(
                    "Remove transaction/reservation language; clarify that activities "
                    "are non-bookable suggestions."
                ),
            )
        )

    # Check day notes and activities
    for day in itinerary.days:
        for note in day.uncertainty_notes:
            banned = _scan_text(note)
            if banned:
                issues.append(
                    ValidationIssue(
                        code=ValidationCode.BOOKING_LANGUAGE_DETECTED,
                        severity=ValidationSeverity.CRITICAL,
                        day_number=day.day_number,
                        message=(
                            f"Day {day.day_number} notes contain prohibited booking "
                            f"term '{banned}'."
                        ),
                        repair_hint="Remove booking references from day notes.",
                    )
                )

        for act in day.activities:
            sanitized_title = sanitize_message_text(act.title, max_length=40)
            for field_val in (
                act.title,
                act.description,
                act.cost_note,
                " ".join(act.uncertainty_notes),
            ):
                banned = _scan_text(field_val)
                if banned:
                    issues.append(
                        ValidationIssue(
                            code=ValidationCode.BOOKING_LANGUAGE_DETECTED,
                            severity=ValidationSeverity.CRITICAL,
                            day_number=day.day_number,
                            activity_id=act.id,
                            message=(
                                f"Activity '{sanitized_title}' contains prohibited "
                                f"booking term '{banned}'."
                            ),
                            repair_hint=(
                                "Remove booking references; state that suggestions "
                                "are indicative and non-bookable."
                            ),
                        )
                    )
                    break

    return issues


def check_weather_without_tool_success(
    itinerary: ItineraryV2,
    request: TripRequest | None,
    tool_results: Sequence[ToolResult] | None,
) -> list[ValidationIssue]:
    """Rule 6c: WEATHER_WITHOUT_TOOL_SUCCESS (critical, Phase 3).

    Ensures that weather forecast claims are backed by a successful weather tool
    invocation.
    """
    weather_claims_found = False

    if re.search(
        r"\b(weather forecast|rain chance|temperatures?|precipitation)\b",
        itinerary.summary,
        re.IGNORECASE,
    ):
        weather_claims_found = True

    if not weather_claims_found:
        for day in itinerary.days:
            for act in day.activities:
                if "weather" in act.interest_tags:
                    weather_claims_found = True
                    break
                if act.provenance == Provenance.RETRIEVED and any(
                    "meteo" in ref.lower() or "weather" in ref.lower()
                    for ref in act.source_refs
                ):
                    weather_claims_found = True
                    break
                if act.description and re.search(
                    r"\bforecast:|\brain chance\b", act.description, re.IGNORECASE
                ):
                    weather_claims_found = True
                    break
            if weather_claims_found:
                break

    if not weather_claims_found:
        return []

    # Check if a weather tool result succeeded with ToolStatus.OK
    has_ok_weather_tool = False
    if tool_results:
        for res in tool_results:
            if (
                res.tool_name in ("get_weather", "weather_forecast")
                and res.status == ToolStatus.OK
            ):
                has_ok_weather_tool = True
                break

    if not has_ok_weather_tool:
        return [
            ValidationIssue(
                code=ValidationCode.WEATHER_WITHOUT_TOOL_SUCCESS,
                severity=ValidationSeverity.CRITICAL,
                message=(
                    "Itinerary contains weather forecast claims without a successful "
                    "weather tool invocation."
                ),
                repair_hint=(
                    "Remove weather forecast claims or ensure weather tool succeeds "
                    "before synthesizing itinerary."
                ),
            )
        ]

    return []


def check_invalid_cost_status(
    itinerary: ItineraryV2,
    request: TripRequest | None,
    tool_results: Sequence[ToolResult] | None,
) -> list[ValidationIssue]:
    """Rule 6d: INVALID_COST_STATUS (critical, Phase 3).

    Ensures cost_status is classified as 'unknown', 'estimate', or 'retrieved',
    and prohibits live guaranteed booking price promises in cost notes.
    """
    issues: list[ValidationIssue] = []

    for day in itinerary.days:
        for act in day.activities:
            sanitized_title = sanitize_message_text(act.title, max_length=40)
            if act.cost_status not in (
                CostStatus.UNKNOWN,
                CostStatus.ESTIMATE,
                CostStatus.RETRIEVED,
            ):
                issues.append(
                    ValidationIssue(
                        code=ValidationCode.INVALID_COST_STATUS,
                        severity=ValidationSeverity.CRITICAL,
                        day_number=day.day_number,
                        activity_id=act.id,
                        message=(
                            f"Activity '{sanitized_title}' has invalid cost_status "
                            f"'{act.cost_status}'."
                        ),
                        repair_hint=(
                            "Cost status must be 'unknown', 'estimate', or 'retrieved'."
                        ),
                    )
                )

            # Disallow live booking price promises in cost_note
            banned_pricing = (
                r"\b(guaranteed fare|live booking price|instant checkout|"
                r"exact ticket fare)\b"
            )
            if act.cost_note and re.search(
                banned_pricing,
                act.cost_note,
                re.IGNORECASE,
            ):
                issues.append(
                    ValidationIssue(
                        code=ValidationCode.INVALID_COST_STATUS,
                        severity=ValidationSeverity.CRITICAL,
                        day_number=day.day_number,
                        activity_id=act.id,
                        message=(
                            f"Activity '{sanitized_title}' claims guaranteed live "
                            "booking prices in cost_note."
                        ),
                        repair_hint=(
                            "State price estimates as non-booking estimates or "
                            "indicative ranges."
                        ),
                    )
                )

    return issues


def check_budget_floor_violation(
    itinerary: ItineraryV2,
    request: TripRequest | None,
    tool_results: Sequence[ToolResult] | None,
) -> list[ValidationIssue]:
    """Rule 7: BUDGET_FLOOR_VIOLATION (critical).

    Flags trip requests whose daily per-person budget is below the configured
    currency hard floor (e.g. $30 USD / €30 EUR / ¥4,000 JPY).
    """
    if request is None or request.budget_amount is None or not request.currency:
        return []

    curr = request.currency.upper()
    floor = CURRENCY_HARD_FLOORS.get(curr)
    if floor is None:
        return []

    trip_days = (request.end_date - request.start_date).days + 1
    if trip_days <= 0 or request.party_size <= 0:
        return []

    daily_per_person = request.budget_amount / Decimal(request.party_size * trip_days)
    if daily_per_person < floor:
        return [
            ValidationIssue(
                code=ValidationCode.BUDGET_FLOOR_VIOLATION,
                severity=ValidationSeverity.CRITICAL,
                message=(
                    f"Budget of {curr} {daily_per_person:.2f}/person/day is below the "
                    f"hard floor of {curr} {floor:.2f}."
                ),
                repair_hint=(
                    "Request user confirmation for low budget or increase the "
                    "budget amount."
                ),
            )
        ]
    return []


# ==============================================================================
# 5. Rule Registry & Entrypoint
# ==============================================================================

RuleCheckFn = Callable[
    [ItineraryV2, TripRequest | None, Sequence[ToolResult] | None],
    list[ValidationIssue],
]


@dataclass(frozen=True)
class ValidationRule:
    """A deterministic validation rule in the rule registry."""

    code: ValidationCode
    default_severity: ValidationSeverity
    repair_hint: str
    description: str
    check: RuleCheckFn


VALIDATION_REGISTRY: Final[list[ValidationRule]] = [
    ValidationRule(
        code=ValidationCode.DATE_RANGE_MISMATCH,
        default_severity=ValidationSeverity.CRITICAL,
        repair_hint=(
            "Align itinerary days exactly with the requested date range and "
            "renumber days 1..N."
        ),
        description=(
            "Verifies exactly one day per date from start to end inclusive, "
            "without missing or duplicate dates."
        ),
        check=check_date_range_mismatch,
    ),
    ValidationRule(
        code=ValidationCode.DUPLICATE_ACTIVITY,
        default_severity=ValidationSeverity.WARNING,
        repair_hint=(
            "Remove redundant activity and substitute with an alternative activity "
            "matching traveler interests."
        ),
        description=(
            "Detects repeated normalized title and location across non-exempt "
            "activities."
        ),
        check=check_duplicate_activity,
    ),
    ValidationRule(
        code=ValidationCode.MAX_DAILY_ACTIVITIES,
        default_severity=ValidationSeverity.CRITICAL,
        repair_hint=(
            "Prune lowest-priority activities on the overloaded day to respect the "
            "pace threshold."
        ),
        description=(
            "Checks that daily activity counts do not exceed configured pace threshold."
        ),
        check=check_max_daily_activities,
    ),
    ValidationRule(
        code=ValidationCode.MISSING_REQUIRED_INTEREST,
        default_severity=ValidationSeverity.WARNING,
        repair_hint=(
            "Substitute a generic activity with an activity tagged with the missing "
            "interest."
        ),
        description=(
            "Verifies that each requested interest appears on at least one activity."
        ),
        check=check_missing_required_interest,
    ),
    ValidationRule(
        code=ValidationCode.MISSING_SOURCE_METADATA,
        default_severity=ValidationSeverity.CRITICAL,
        repair_hint=(
            "Attach source_refs or downgrade provenance to generated_suggestion."
        ),
        description=(
            "Verifies that retrieved claims reference valid SourceInfo objects with "
            "complete attribution metadata."
        ),
        check=check_missing_source_metadata,
    ),
    ValidationRule(
        code=ValidationCode.MISSING_PROVENANCE,
        default_severity=ValidationSeverity.CRITICAL,
        repair_hint="Assign a valid Provenance classification to the activity.",
        description=("Ensures every activity has a defined Provenance classification."),
        check=check_missing_provenance,
    ),
    ValidationRule(
        code=ValidationCode.BOOKING_LANGUAGE_DETECTED,
        default_severity=ValidationSeverity.CRITICAL,
        repair_hint=(
            "Remove transactional booking/reservation claims; state that activities "
            "are non-bookable suggestions."
        ),
        description=(
            "Scans for prohibited transactional booking, reservation, or payment "
            "terminology."
        ),
        check=check_booking_language,
    ),
    ValidationRule(
        code=ValidationCode.WEATHER_WITHOUT_TOOL_SUCCESS,
        default_severity=ValidationSeverity.CRITICAL,
        repair_hint="Remove weather forecast claims or ensure weather tool succeeds.",
        description=(
            "Ensures weather forecast claims are backed by a successful weather "
            "tool invocation."
        ),
        check=check_weather_without_tool_success,
    ),
    ValidationRule(
        code=ValidationCode.INVALID_COST_STATUS,
        default_severity=ValidationSeverity.CRITICAL,
        repair_hint=(
            "Ensure costs are classified as 'estimate' or 'unknown', not live "
            "booking prices."
        ),
        description=(
            "Verifies that activity costs are classified properly and do not claim "
            "live booking prices."
        ),
        check=check_invalid_cost_status,
    ),
    ValidationRule(
        code=ValidationCode.BUDGET_FLOOR_VIOLATION,
        default_severity=ValidationSeverity.CRITICAL,
        repair_hint=(
            "Request user confirmation for low budget or increase budget amount."
        ),
        description=(
            "Flags trip requests whose daily per-person budget is below the "
            "configured currency hard floor."
        ),
        check=check_budget_floor_violation,
    ),
]


def _issue_sort_key(issue: ValidationIssue) -> tuple[int, int, int, str, str, str]:
    """Deterministic sort key for validation issues.

    Order:
    1. day_number: None first (0), then 1, with actual day_number
    2. severity: critical (0) before warning (1)
    3. rule code string
    4. activity_id (empty string if None)
    5. message
    """
    day_flag = 0 if issue.day_number is None else 1
    day_val = issue.day_number if issue.day_number is not None else 0
    sev_val = 0 if issue.severity == ValidationSeverity.CRITICAL else 1
    code_val = str(issue.code)
    act_val = issue.activity_id or ""
    return (day_flag, day_val, sev_val, code_val, act_val, issue.message)


def validate_itinerary(
    itinerary_or_state: ItineraryV2 | TripState | dict[str, Any] | None,
    request: TripRequest | None = None,
    tool_results: Sequence[ToolResult] | None = None,
) -> list[ValidationIssue]:
    """Validate an itinerary against the deterministic validation rules catalog.

    Accepts an ItineraryV2, legacy Itinerary, dictionary payload, or a TripState.
    Returns deterministically sorted validation issues with sanitized messages.
    """
    if itinerary_or_state is None:
        return [
            ValidationIssue(
                code=ValidationCode.DATE_RANGE_MISMATCH,
                severity=ValidationSeverity.CRITICAL,
                message="No itinerary draft provided for validation.",
                repair_hint="Generate an itinerary before invoking validation.",
            )
        ]

    # Handle TripState input
    if isinstance(itinerary_or_state, TripState):
        if itinerary_or_state.itinerary_draft is None:
            return [
                ValidationIssue(
                    code=ValidationCode.DATE_RANGE_MISMATCH,
                    severity=ValidationSeverity.CRITICAL,
                    message="TripState contains no itinerary_draft to validate.",
                    repair_hint="Generate an itinerary before invoking validation.",
                )
            ]
        target_itinerary = parse_itinerary_payload(itinerary_or_state.itinerary_draft)
        target_request = request or itinerary_or_state.trip_request
        target_tool_results = tool_results or itinerary_or_state.tool_results
    elif isinstance(itinerary_or_state, dict):
        target_itinerary = parse_itinerary_payload(itinerary_or_state)
        target_request = request
        target_tool_results = tool_results
    elif isinstance(itinerary_or_state, ItineraryV2):
        target_itinerary = itinerary_or_state
        target_request = request
        target_tool_results = tool_results
    else:
        target_itinerary = parse_itinerary_payload(itinerary_or_state)
        target_request = request
        target_tool_results = tool_results

    issues: list[ValidationIssue] = []
    for rule in VALIDATION_REGISTRY:
        rule_issues = rule.check(target_itinerary, target_request, target_tool_results)
        issues.extend(rule_issues)

    # Sort deterministically
    issues.sort(key=_issue_sort_key)
    return issues


def has_critical(issues: Sequence[ValidationIssue]) -> bool:
    """Return True if any issue in the sequence has CRITICAL severity."""
    return any(issue.severity == ValidationSeverity.CRITICAL for issue in issues)


# Convenience alias for consumers avoiding collisions with agent graph node
run_itinerary_validation = validate_itinerary
