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
        context: dict[str, Any] | None = None,
    ) -> str:
        """Generate a polite, targeted clarification question for missing fields."""
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
        elif len(iso_dates) == 1 and "start_date" not in fields:
            fields["start_date"] = iso_dates[0]

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

    def generate_clarification(
        self,
        missing_fields: list[str],
        context: dict[str, Any] | None = None,
    ) -> str:
        """Construct a focused clarification query for missing travel parameters."""
        if not missing_fields:
            return "Could you provide more details about your travel plans?"

        clean_fields = [f.replace("_", " ") for f in missing_fields]
        if len(clean_fields) == 1:
            field = clean_fields[0]
            if "destination" in field:
                return "Where would you like to travel?"
            if "origin" in field:
                return "Where will you be departing from?"
            if "date" in field:
                return "What dates are you planning your trip for?"
            return f"Could you please specify your travel {field}?"

        if len(clean_fields) == 2:
            return (
                f"Could you please provide your {clean_fields[0]} "
                f"and {clean_fields[1]}?"
            )

        formatted_list = ", ".join(clean_fields[:-1]) + f", and {clean_fields[-1]}"
        return f"Could you please specify your {formatted_list} to help plan your trip?"


class ScriptedGateway:
    """Configurable fake gateway for testing agent workflow paths."""

    def __init__(
        self,
        scripted_fields: dict[str, Any] | None = None,
        scripted_intent: Intent | None = None,
        scripted_clarification: str | None = None,
        exception: Exception | None = None,
    ) -> None:
        self.scripted_fields = scripted_fields
        self.scripted_intent = scripted_intent
        self.scripted_clarification = scripted_clarification
        self.exception = exception
        self.extract_calls: list[str] = []
        self.classify_calls: list[str] = []
        self.clarification_calls: list[list[str]] = []

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
        context: dict[str, Any] | None = None,
    ) -> str:
        self.clarification_calls.append(list(missing_fields))
        if self.exception:
            raise self.exception
        if self.scripted_clarification is not None:
            return self.scripted_clarification
        return f"Please specify: {', '.join(missing_fields)}"
