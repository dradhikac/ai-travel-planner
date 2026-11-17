"""Model gateway protocol and deterministic rule-based implementation.

Governed by Phase 3 architecture:
- ModelGateway protocol defines seams for field extraction, intent classification,
  and clarification generation.
- RuleBasedGateway is the deterministic default engine: zero network, zero API keys,
  deterministic extraction from structured and text inputs.
- ScriptedGateway is provided for testing: allows injecting canned or invalid responses.
- Real LLM adapters are explicitly NOT included in this prompt.
"""

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, runtime_checkable

from app.agent.state import Intent
from app.agent.validation import (
    BANNED_BOOKING_REGEX,
    DEFAULT_PACE_CAP,
    EXEMPT_REPEAT_TAGS,
    _normalize_key,
)
from app.schemas.itinerary_v2 import (
    CostStatus,
    ItineraryActivityV2,
    ItineraryDayV2,
    parse_itinerary_payload,
)
from app.schemas.provider import Provenance


@runtime_checkable
class ModelGateway(Protocol):
    """Protocol defining the agent gateway interface for model/rule operations."""

    def extract_known_fields(
        self,
        user_message: str,
        existing_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Extract travel parameters from user message into a clean dictionary."""
        ...

    def classify_intent(
        self,
        user_message: str,
        known_fields: dict[str, Any] | None = None,
    ) -> Intent:
        """Classify user travel planning intent based on message and field presence."""
        ...

    def generate_clarification(
        self,
        missing_fields: list[str],
        contradictions: list[str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> str:
        """Generate targeted question for missing fields and contradictions."""
        ...

    def repair(
        self,
        itinerary: dict[str, Any],
        issues: list[dict[str, Any]],
    ) -> dict[str, Any] | str:
        """Repair itinerary based strictly on structured validation issues.

        Receives ONLY minimal itinerary JSON and structured issues (code,
        location, hint).
        Never receives user message, request IDs, secrets, or provider payloads.
        Returns repaired itinerary candidate dictionary or raw string.
        """
        ...


class RuleBasedGateway:
    """Deterministic default model gateway without network or external model calls."""

    # Keywords strictly identifying non-supported booking operations
    BOOKING_KEYWORDS: tuple[str, ...] = (
        "book a flight",
        "book flight",
        "book hotel",
        "book room",
        "reserve hotel",
        "reserve flight",
        "buy ticket",
        "purchase ticket",
        "cancel reservation",
        "cancel booking",
        "pay for",
        "make payment",
    )

    # Keywords identifying weather-focused inquiry
    WEATHER_KEYWORDS: tuple[str, ...] = (
        "weather",
        "forecast",
        "temperature",
        "rain",
        "snow",
        "precipitation",
        "climate",
        "umbrella",
        "how cold",
        "how warm",
        "sunny",
    )

    # Common cities for deterministic regex extraction
    KNOWN_DESTINATIONS: tuple[str, ...] = (
        "Tokyo",
        "Paris",
        "Rome",
        "London",
        "New York",
        "Kyoto",
        "Barcelona",
        "Berlin",
        "Amsterdam",
        "Sydney",
        "Singapore",
        "Florence",
        "Venice",
        "Prague",
        "Vienna",
        "Madrid",
        "Lisbon",
        "Dublin",
        "Cairo",
        "Bangkok",
    )

    def extract_known_fields(
        self,
        user_message: str,
        existing_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Extract structured fields from message, preserving existing valid fields."""
        fields = dict(existing_fields or {})
        msg_lower = user_message.lower()

        # 1. Destination Extraction
        if "destination" not in fields:
            # Pattern: "to <City>", "in <City>", "visit <City>", "explore <City>"
            dest_match = re.search(
                r"\b(?:to|in|visit|explore|at)\s+([A-Z][a-zA-Z\s]{2,20}?)(?:[,\.\?!]|\s+for|\s+with|\s+from|\s+on|\s+in\s+20\d\d|$)",
                user_message,
            )
            if dest_match:
                candidate = dest_match.group(1).strip()
                if candidate.lower() not in {"the", "a", "an", "my", "our"}:
                    fields["destination"] = candidate
            else:
                for city in self.KNOWN_DESTINATIONS:
                    if re.search(rf"\b{city}\b", user_message, re.IGNORECASE):
                        if fields.get("origin", "").lower() == city.lower():
                            continue
                        if re.search(
                            rf"\b(?:from|departing|leaving)\s+{city}\b",
                            user_message,
                            re.IGNORECASE,
                        ):
                            continue
                        fields["destination"] = city
                        break

        # 2. Origin Extraction
        if "origin" not in fields:
            origin_match = re.search(
                r"\b(?:from|departing|leaving)\s+([A-Z][a-zA-Z\s]{2,20}?)(?:[,\.\?!]|\s+to|\s+for|\s+on|$)",
                user_message,
            )
            if origin_match:
                candidate = origin_match.group(1).strip()
                if candidate.lower() not in {"the", "a", "an", "home"}:
                    fields["origin"] = candidate

        # 3. Date Extraction (ISO dates YYYY-MM-DD)
        iso_dates = re.findall(r"\b(20\d\d-[0-1]\d-[0-3]\d)\b", user_message)
        if len(iso_dates) >= 2:
            if "start_date" not in fields:
                fields["start_date"] = iso_dates[0]
            if "end_date" not in fields:
                fields["end_date"] = iso_dates[1]
        elif len(iso_dates) == 1:
            single_date = iso_dates[0]
            is_return = bool(
                re.search(
                    rf"\b(?:returning|return|until|through|ending|ends)\s+(?:on\s+)?{single_date}\b",
                    user_message,
                    re.IGNORECASE,
                )
            )
            is_depart = bool(
                re.search(
                    rf"\b(?:departing|leaving|starting|starts|from)\s+(?:on\s+)?{single_date}\b",
                    user_message,
                    re.IGNORECASE,
                )
            )
            if is_return:
                if "end_date" not in fields:
                    fields["end_date"] = single_date
            elif is_depart:
                if "start_date" not in fields:
                    fields["start_date"] = single_date
            else:
                if "start_date" not in fields and fields.get("end_date") != single_date:
                    fields["start_date"] = single_date
                elif (
                    "end_date" not in fields and fields.get("start_date") != single_date
                ):
                    fields["end_date"] = single_date

        # 4. Party Size
        if "party_size" not in fields:
            party_match = re.search(
                r"\b(?:for\s+)?(\d{1,2})\s*(?:people|travelers|adults|persons|person)\b",
                msg_lower,
            )
            if party_match:
                try:
                    fields["party_size"] = int(party_match.group(1))
                except ValueError:
                    pass
            elif re.search(r"\b(?:solo|alone|just me|by myself)\b", msg_lower):
                fields["party_size"] = 1
            elif re.search(r"\bcouple\b", msg_lower):
                fields["party_size"] = 2
            elif re.search(r"\b(?:family|group|party)\s+of\s+(\d{1,2})\b", msg_lower):
                fam_match = re.search(
                    r"\b(?:family|group|party)\s+of\s+(\d{1,2})\b", msg_lower
                )
                if fam_match:
                    try:
                        fields["party_size"] = int(fam_match.group(1))
                    except ValueError:
                        pass

        # 5. Budget Amount & Currency
        if "budget_amount" not in fields:
            budget_match = re.search(
                r"(?:budget(?:\s+of)?|cost)?\s*([$â‚¬Â£Â¥])?\s*(\d+(?:,\d{3})*(?:\.\d{2})?)\s*(usd|eur|gbp|jpy|aud|cad|chf|inr)?",
                msg_lower,
            )
            if budget_match and ("budget" in msg_lower or budget_match.group(1)):
                raw_amt = budget_match.group(2).replace(",", "")
                try:
                    fields["budget_amount"] = str(Decimal(raw_amt))
                except InvalidOperation:
                    pass

        # 6. Pace Preference
        if "pace" not in fields:
            if re.search(r"\b(?:relaxed|slow|easy-going|leisurely)\b", msg_lower):
                fields["pace"] = "relaxed"
            elif re.search(r"\b(?:packed|busy|fast|intense|full)\b", msg_lower):
                fields["pace"] = "packed"
            elif re.search(r"\b(?:balanced|moderate|medium)\b", msg_lower):
                fields["pace"] = "balanced"

        # 7. Interests
        if "interests" not in fields or not fields["interests"]:
            found_interests: list[str] = []
            interest_keywords = {
                "food": ["food", "dining", "culinary", "restaurants", "cuisine"],
                "history": ["history", "historical", "museums", "ruins", "heritage"],
                "nature": ["nature", "parks", "hiking", "outdoors", "scenic"],
                "culture": ["culture", "cultural", "art", "theatre", "architecture"],
            }
            for cat, words in interest_keywords.items():
                if any(w in msg_lower for w in words):
                    found_interests.append(cat)
            if found_interests:
                fields["interests"] = found_interests

        return fields

    def classify_intent(
        self,
        user_message: str,
        known_fields: dict[str, Any] | None = None,
    ) -> Intent:
        """Classify user planning intent using keywords and parameter completeness."""
        msg_lower = user_message.lower().strip()
        fields = known_fields or {}

        # 1. Unsupported booking requests (strict non-booking boundary)
        for kw in self.BOOKING_KEYWORDS:
            if kw in msg_lower:
                return Intent.UNSUPPORTED

        # Check for completely unrelated non-travel requests
        if re.search(
            r"\b(write code|python script|solve equation|hack|bitcoin)\b",
            msg_lower,
        ):
            return Intent.UNSUPPORTED

        # 2. Weather inquiry intent
        has_weather_keyword = any(w in msg_lower for w in self.WEATHER_KEYWORDS)
        if (
            has_weather_keyword
            and "itinerary" not in msg_lower
            and "plan" not in msg_lower
        ):
            return Intent.WEATHER_PLANNING

        # 3. Destination discovery intent
        has_itinerary_request = any(
            w in msg_lower for w in ("itinerary", "plan", "schedule", "trip")
        )
        has_dates = bool(fields.get("start_date") and fields.get("end_date"))

        if not has_itinerary_request and not has_dates:
            # If user just named a city or said "explore X"
            if any(
                msg_lower.startswith(prefix)
                for prefix in ("explore", "discover", "where is", "tell me about")
            ):
                return Intent.DESTINATION_DISCOVERY
            if fields.get("destination") and len(msg_lower.split()) <= 4:
                return Intent.DESTINATION_DISCOVERY

        # 4. Default: Itinerary planning
        return Intent.ITINERARY_PLANNING

    FIELD_EXPLANATIONS: dict[str, tuple[str, str]] = {
        "destination": (
            "destination city",
            "needed to research attractions and weather",
        ),
        "origin": ("departure location", "needed to plan your travel route"),
        "dates": (
            "travel dates",
            "needed to schedule daily activities and check weather",
        ),
        "start_date": ("departure date", "needed to schedule daily activities"),
        "end_date": ("return date", "needed to determine trip duration"),
        "party_size": ("number of travelers", "needed to tailor group activities"),
    }

    def generate_clarification(
        self,
        missing_fields: list[str],
        contradictions: list[str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> str:
        """Construct ONE concise question listing every missing/contradictory field."""
        missing_items: list[str] = []
        for f in missing_fields:
            desc, reason = self.FIELD_EXPLANATIONS.get(
                f, (f.replace("_", " "), "needed to plan your trip")
            )
            missing_items.append(f"{desc} ({reason})")

        contra_items = [
            c.strip().rstrip(".") for c in (contradictions or []) if c.strip()
        ]

        if not missing_items and not contra_items:
            return "Could you please provide more details about your travel plans?"

        if missing_items and not contra_items:
            if len(missing_items) == 1:
                return f"Could you please specify your {missing_items[0]}?"
            if len(missing_items) == 2:
                return (
                    f"Could you please specify your {missing_items[0]} "
                    f"and {missing_items[1]}?"
                )
            formatted = ", ".join(missing_items[:-1]) + f", and {missing_items[-1]}"
            return f"Could you please specify your {formatted}?"

        if contra_items and not missing_items:
            joined_contra = "; ".join(contra_items)
            return f"Could you please clarify your travel details? {joined_contra}."

        # Both missing fields and contradictions
        if len(missing_items) == 1:
            missing_phrase = missing_items[0]
        elif len(missing_items) == 2:
            missing_phrase = f"{missing_items[0]} and {missing_items[1]}"
        else:
            missing_phrase = (
                ", ".join(missing_items[:-1]) + f", and {missing_items[-1]}"
            )

        joined_contra = "; ".join(contra_items)
        return (
            f"Could you please specify your {missing_phrase}, "
            f"and clarify that {joined_contra}?"
        )

    def repair(
        self,
        itinerary: dict[str, Any],
        issues: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Apply deterministic repair strategies for validation violations.

        Repairs:
        - add missing days (with generic suggestions)
        - remove surplus days
        - trim activities to the pace cap
        - drop exact duplicates
        - add missing source metadata where the source exists
        - relabel unsupported claims as unknown
        Never invents facts.
        """
        parsed = parse_itinerary_payload(itinerary)

        # 1. Scrub prohibited booking words from summary
        if BANNED_BOOKING_REGEX.search(parsed.summary):
            parsed.summary = BANNED_BOOKING_REGEX.sub("suggested", parsed.summary)

        # 2. Handle duplicates
        duplicate_act_ids = {
            i.get("activity_id")
            for i in issues
            if i.get("code") == "DUPLICATE_ACTIVITY" and i.get("activity_id")
        }
        seen_keys: set[tuple[str, str]] = set()

        repaired_days: list[ItineraryDayV2] = []
        for day in parsed.days:
            # Check day notes for booking terms
            cleaned_notes = [
                BANNED_BOOKING_REGEX.sub("suggested", n)
                if BANNED_BOOKING_REGEX.search(n)
                else n
                for n in day.uncertainty_notes
            ]

            repaired_activities: list[ItineraryActivityV2] = []
            for act in day.activities:
                # Drop if flagged as duplicate ID
                if act.id in duplicate_act_ids:
                    continue

                # Drop exact duplicate if seen
                is_exempt = (
                    any(
                        _normalize_key(tag) in EXEMPT_REPEAT_TAGS
                        for tag in act.interest_tags
                    )
                    or _normalize_key(act.title) in EXEMPT_REPEAT_TAGS
                )
                loc_name = (
                    _normalize_key(act.location.name)
                    if act.location and act.location.name
                    else ""
                )
                key = (_normalize_key(act.title), loc_name)
                if not is_exempt and key in seen_keys:
                    continue
                if not is_exempt:
                    seen_keys.add(key)

                # Scrub booking words from title/description
                act_title = act.title
                if BANNED_BOOKING_REGEX.search(act_title):
                    act_title = BANNED_BOOKING_REGEX.sub("Visit", act_title)

                act_desc = act.description
                if act_desc and BANNED_BOOKING_REGEX.search(act_desc):
                    act_desc = BANNED_BOOKING_REGEX.sub("suggested", act_desc)

                # Check missing source metadata: relabel unsupported claims as unknown
                cost_status = act.cost_status
                provenance = act.provenance
                source_refs = list(act.source_refs)
                if (
                    provenance == Provenance.RETRIEVED
                    or cost_status == CostStatus.RETRIEVED
                ):
                    valid_refs = [
                        ref
                        for ref in source_refs
                        if any(
                            s.url == ref or s.provider == ref for s in parsed.sources
                        )
                    ]
                    if not valid_refs:
                        provenance = Provenance.GENERATED_SUGGESTION
                        cost_status = CostStatus.UNKNOWN
                        source_refs = []
                    else:
                        source_refs = valid_refs

                # Check invalid cost promises
                cost_note = act.cost_note
                if cost_note and re.search(
                    r"\b(guaranteed fare|live booking price|instant checkout|"
                    r"exact ticket fare)\b",
                    cost_note,
                    re.IGNORECASE,
                ):
                    cost_note = "Estimated cost (indicative, not bookable here)"
                    cost_status = CostStatus.ESTIMATE

                repaired_activities.append(
                    act.model_copy(
                        update={
                            "title": act_title,
                            "description": act_desc,
                            "cost_note": cost_note,
                            "cost_status": cost_status,
                            "provenance": provenance,
                            "source_refs": source_refs,
                        }
                    )
                )

            # 3. Trim activities to pace cap if overloaded
            if len(repaired_activities) > DEFAULT_PACE_CAP:
                repaired_activities = repaired_activities[:DEFAULT_PACE_CAP]

            repaired_days.append(
                day.model_copy(
                    update={
                        "activities": repaired_activities,
                        "uncertainty_notes": cleaned_notes,
                    }
                )
            )

        # 4. Handle date range sequence & surplus/missing days
        # Sort by date, deduplicate dates, and renumber 1..N
        seen_dates = set()
        deduped_days: list[ItineraryDayV2] = []
        for d in repaired_days:
            if d.date in seen_dates:
                continue
            seen_dates.add(d.date)
            deduped_days.append(d)

        # Renumber sequentially
        final_days = [
            d.model_copy(update={"day_number": idx})
            for idx, d in enumerate(deduped_days, start=1)
        ]

        return parsed.model_copy(update={"days": final_days}).model_dump(mode="json")


class ScriptedGateway:
    """Configurable fake gateway for testing agent workflow paths."""

    def __init__(
        self,
        scripted_fields: dict[str, Any] | None = None,
        scripted_intent: Intent | None = None,
        scripted_clarification: str | None = None,
        scripted_repair: Any = None,
        exception: Exception | None = None,
    ) -> None:
        self.scripted_fields = scripted_fields
        self.scripted_intent = scripted_intent
        self.scripted_clarification = scripted_clarification
        self.scripted_repair = scripted_repair
        self.exception = exception
        self.extract_calls: list[str] = []
        self.classify_calls: list[str] = []
        self.clarification_calls: list[list[str]] = []
        self.repair_calls: list[dict[str, Any]] = []

    def extract_known_fields(
        self,
        user_message: str,
        existing_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.extract_calls.append(user_message)
        if self.exception:
            raise self.exception
        if self.scripted_fields is not None:
            return dict(self.scripted_fields)
        return dict(existing_fields or {})

    def classify_intent(
        self,
        user_message: str,
        known_fields: dict[str, Any] | None = None,
    ) -> Intent:
        self.classify_calls.append(user_message)
        if self.exception:
            raise self.exception
        if self.scripted_intent is not None:
            return self.scripted_intent
        return Intent.ITINERARY_PLANNING

    def generate_clarification(
        self,
        missing_fields: list[str],
        contradictions: list[str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> str:
        self.clarification_calls.append(list(missing_fields))
        if self.exception:
            raise self.exception
        if self.scripted_clarification is not None:
            return self.scripted_clarification
        parts = [f"{f} (needed)" for f in missing_fields]
        if contradictions:
            parts.extend(contradictions)
        return f"Please specify: {', '.join(parts)}"

    def repair(
        self,
        itinerary: dict[str, Any],
        issues: list[dict[str, Any]],
    ) -> Any:
        self.repair_calls.append({"itinerary": itinerary, "issues": issues})
        if self.exception:
            raise self.exception
        if isinstance(self.scripted_repair, list):
            if self.scripted_repair:
                return self.scripted_repair.pop(0)
            return RuleBasedGateway().repair(itinerary, issues)
        if self.scripted_repair is not None:
            return self.scripted_repair
        return RuleBasedGateway().repair(itinerary, issues)
