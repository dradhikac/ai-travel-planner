"""Trip intake and response schemas."""

from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from app.schemas.provider import Provenance, SourceInfo, WeatherSummary

ALLOWED_CURRENCIES: frozenset[str] = frozenset(
    {"USD", "EUR", "GBP", "CAD", "AUD", "JPY", "INR", "CHF", "NZD", "SGD"}
)


class PacePreference(StrEnum):
    """Travel pace preference."""

    RELAXED = "relaxed"
    BALANCED = "balanced"
    PACKED = "packed"


class TimeOfDay(StrEnum):
    """Time of day for itinerary scheduling."""

    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"


class TripRequest(BaseModel):
    """Intake request contract for travel research and planning."""

    model_config = ConfigDict(extra="forbid")

    origin: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Departure city or location",
    )
    destination: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Destination city or region",
    )
    start_date: date = Field(..., description="Trip start date (ISO 8601)")
    end_date: date = Field(..., description="Trip end date (ISO 8601)")
    party_size: int = Field(
        default=1,
        ge=1,
        le=20,
        description="Number of travelers",
    )
    budget_amount: Decimal | None = Field(
        default=None,
        gt=Decimal("0"),
        le=Decimal("10000000"),
        description="Total budget amount",
    )
    currency: str | None = Field(
        default=None,
        description="ISO 4217 currency code",
    )
    interests: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Up to 10 travel interests",
    )
    pace: PacePreference = Field(
        default=PacePreference.BALANCED,
        description="Itinerary pace preference",
    )

    # Injectable today reference for deterministic testing
    _test_today: date | None = None

    @classmethod
    def get_today(cls, info: ValidationInfo | None = None) -> date:
        """Return reference today date, supporting test injection and context."""
        if info is not None and info.context and "today" in info.context:
            return info.context["today"]
        if cls._test_today is not None:
            return cls._test_today
        return date.today()

    @classmethod
    def set_test_today(cls, today_date: date | None) -> None:
        """Set or reset reference today date for deterministic testing."""
        cls._test_today = today_date

    @field_validator("origin", "destination", mode="before")
    @classmethod
    def normalize_location_string(cls, v: object) -> object:
        """Trim, collapse consecutive whitespace, and reject blank location strings."""
        if isinstance(v, str):
            collapsed = " ".join(v.strip().split())
            if not collapsed:
                raise ValueError("Location string cannot be empty or whitespace only")
            return collapsed
        return v

    @field_validator("start_date", mode="after")
    @classmethod
    def validate_start_date_not_in_past(cls, v: date, info: ValidationInfo) -> date:
        """Validate that trip start date is not in the past."""
        today = cls.get_today(info)
        if v < today:
            raise ValueError("Start date cannot be in the past")
        return v

    @field_validator("currency", mode="before")
    @classmethod
    def validate_currency(cls, v: object) -> object:
        """Validate and normalize ISO currency code against allow-list."""
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError("Currency must be a string")
        norm = v.strip().upper()
        if norm not in ALLOWED_CURRENCIES:
            sorted_allowed = sorted(ALLOWED_CURRENCIES)
            raise ValueError(
                f"Currency '{v}' is not supported. Allowed: {sorted_allowed}"
            )
        return norm

    @field_validator("interests", mode="before")
    @classmethod
    def normalize_interests(cls, v: object) -> list[str]:
        """Normalize interests: lowercase, collapse whitespace, and limit."""
        if not isinstance(v, list):
            return []
        cleaned: list[str] = []
        seen = set()
        for item in v:
            if isinstance(item, str):
                norm = " ".join(item.strip().split()).lower()
                if norm and len(norm) <= 40 and norm not in seen:
                    seen.add(norm)
                    cleaned.append(norm)
        return cleaned[:10]

    @model_validator(mode="after")
    def validate_trip_boundaries(self) -> "TripRequest":
        """Validate cross-field boundaries, contradictions, and range limits."""
        # 1. Origin and destination contradiction (case-insensitive)
        if self.origin.casefold() == self.destination.casefold():
            raise ValueError("Origin and destination cannot be identical")

        # 2. Date order validation
        if self.end_date < self.start_date:
            raise ValueError("End date must be on or after start date")

        # 3. Maximum trip length (30 days maximum for Phase 2)
        trip_duration_days = (self.end_date - self.start_date).days + 1
        if trip_duration_days > 30:
            msg = (
                f"Trip duration ({trip_duration_days} days) exceeds "
                "maximum limit of 30 days"
            )
            raise ValueError(msg)

        # 4. Currency / Budget coupling
        if self.budget_amount is not None and self.currency is None:
            raise ValueError(
                "Currency must be specified when budget_amount is provided"
            )
        if self.budget_amount is None and self.currency is not None:
            raise ValueError("Currency cannot be specified without budget_amount")

        return self


class ItineraryItem(BaseModel):
    """Scheduled activity item within an itinerary day."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, max_length=150)
    time_of_day: TimeOfDay
    description: str = Field(..., max_length=500)
    provenance: Provenance = Field(default=Provenance.GENERATED_SUGGESTION)
    source_ref: str | None = Field(
        default=None, description="Optional citation or provider reference"
    )
    note: str | None = Field(default=None, description="Helpful tip or scheduling note")
    cost_estimate: str | None = Field(
        default=None,
        description=(
            "Categorized purely as an estimate or unknown. Never claims real-time "
            "booking prices."
        ),
    )

    @field_validator("provenance", mode="after")
    @classmethod
    def validate_item_provenance(cls, v: Provenance | None) -> Provenance:
        """Reject items with missing or invalid provenance."""
        if v is None or not isinstance(v, Provenance):
            raise ValueError("ItineraryItem must specify a valid Provenance")
        return v


class ItineraryDay(BaseModel):
    """Daily itinerary collection of activities."""

    model_config = ConfigDict(extra="forbid")

    day_number: int = Field(..., ge=1)
    date: date
    items: list[ItineraryItem] = Field(default_factory=list)

    @field_validator("items", mode="after")
    @classmethod
    def validate_day_items_provenance(
        cls, v: list[ItineraryItem]
    ) -> list[ItineraryItem]:
        """Validate that each item in day has valid provenance."""
        for item in v:
            if getattr(item, "provenance", None) is None or not isinstance(
                item.provenance, Provenance
            ):
                raise ValueError("ItineraryDay items must specify a valid Provenance")
        return v


class Itinerary(BaseModel):
    """Complete generated itinerary."""

    model_config = ConfigDict(extra="forbid")

    days: list[ItineraryDay] = Field(default_factory=list)
    summary: str = Field(..., max_length=500)

    @model_validator(mode="after")
    def validate_all_items_provenance(self) -> "Itinerary":
        """Ensure every activity item across all days has valid provenance."""
        for day in self.days:
            for item in day.items:
                if getattr(item, "provenance", None) is None or not isinstance(
                    item.provenance, Provenance
                ):
                    raise ValueError("Itinerary items must specify a valid Provenance")
        return self


class TripResponse(BaseModel):
    """Complete trip response contract including itinerary and weather."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    request: TripRequest
    itinerary: Itinerary
    weather: WeatherSummary | None = None
    sources: list[SourceInfo] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime

    @field_validator("created_at", mode="after")
    @classmethod
    def ensure_utc_timezone(cls, v: datetime) -> datetime:
        """Ensure created_at timestamp is timezone-aware UTC."""
        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v.astimezone(UTC)
