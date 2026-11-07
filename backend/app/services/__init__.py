"""Domain services package for AI Travel Concierge."""

from app.services.itinerary import (
    ADVISORY_NOTE,
    LOW_BUDGET_THRESHOLD_PER_DAY,
    PACE_ITEM_COUNTS,
    PACKED_LONG_TRIP_DAYS,
    RAIN_PROBABILITY_THRESHOLD_PCT,
    generate_itinerary,
)

__all__ = [
    "ADVISORY_NOTE",
    "LOW_BUDGET_THRESHOLD_PER_DAY",
    "PACE_ITEM_COUNTS",
    "PACKED_LONG_TRIP_DAYS",
    "RAIN_PROBABILITY_THRESHOLD_PCT",
    "generate_itinerary",
]
