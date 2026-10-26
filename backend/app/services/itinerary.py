"""Deterministic itinerary generator service for AI Travel Concierge.

Transforms verified trip intake requests, destination coordinates, and normalized
weather forecasts into structured, daily itineraries with explicit provenance.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Final

from app.schemas.provider import GeocodeResult, Provenance, WeatherDay, WeatherSummary
from app.schemas.trip import (
    Itinerary,
    ItineraryDay,
    ItineraryItem,
    PacePreference,
    TimeOfDay,
    TripRequest,
)

# Documented constants
PACE_ITEM_COUNTS: Final[dict[PacePreference, int]] = {
    PacePreference.RELAXED: 2,
    PacePreference.BALANCED: 3,
    PacePreference.PACKED: 4,
}

LOW_BUDGET_THRESHOLD_PER_DAY: Final[Decimal] = Decimal("50.00")
PACKED_LONG_TRIP_DAYS: Final[int] = 7
RAIN_PROBABILITY_THRESHOLD_PCT: Final[int] = 40
ADVISORY_NOTE: Final[str] = (
    "Opening hours, admission details, and visitor guidelines should be "
    "verified locally or via official venues."
)


@dataclass(frozen=True)
class ActivityTemplate:
    """Generic activity template without vendor-specific names or unverified prices."""

    category: str
    title_template: str
    description_template: str
    is_indoor: bool
    preferred_time: TimeOfDay


# Curated catalog of generic activity templates keyed by traveler interests
GENERIC_TEMPLATES: Final[dict[str, list[ActivityTemplate]]] = {
    "food": [
        ActivityTemplate(
            category="food",
            title_template="Market Stall & Bakery Sampling in {destination}",
            description_template=(
                "Taste freshly prepared morning specialties and local baked goods "
                "at central food market stalls across {destination}."
            ),
            is_indoor=True,
            preferred_time=TimeOfDay.MORNING,
        ),
        ActivityTemplate(
            category="food",
            title_template="Regional Culinary Food Hall Tasting in {destination}",
            description_template=(
                "Experience authentic regional delicacies and artisanal pantry "
                "staples at a community dining hall in {destination}."
            ),
            is_indoor=True,
            preferred_time=TimeOfDay.AFTERNOON,
        ),
        ActivityTemplate(
            category="food",
            title_template="Traditional Dinner Experience in {destination}",
            description_template=(
                "Savour traditional multi-course dining reflecting centuries of local "
                "gastronomic heritage in {destination}."
            ),
            is_indoor=True,
            preferred_time=TimeOfDay.EVENING,
        ),
    ],
    "museums": [
        ActivityTemplate(
            category="museums",
            title_template="Major Art & Cultural Gallery Visit in {destination}",
            description_template=(
                "Admire permanent exhibitions, fine arts collections, and cultural "
                "artifacts at a premier municipal museum in {destination}."
            ),
            is_indoor=True,
            preferred_time=TimeOfDay.MORNING,
        ),
        ActivityTemplate(
            category="museums",
            title_template="Science & Regional History Museum in {destination}",
            description_template=(
                "Explore historical displays, interactive technological models, "
                "and heritage collections in {destination}."
            ),
            is_indoor=True,
            preferred_time=TimeOfDay.AFTERNOON,
        ),
        ActivityTemplate(
            category="museums",
            title_template="Contemporary Arts Exhibition in {destination}",
            description_template=(
                "Discover modern local artwork, photography installations, and "
                "sculpture galleries in {destination}."
            ),
            is_indoor=True,
            preferred_time=TimeOfDay.EVENING,
        ),
    ],
    "nature": [
        ActivityTemplate(
            category="nature",
            title_template="Botanical Gardens & Parkland Stroll in {destination}",
            description_template=(
                "Walk along manicured garden paths, native plant collections, and "
                "quiet green corridors in {destination}."
            ),
            is_indoor=False,
            preferred_time=TimeOfDay.MORNING,
        ),
        ActivityTemplate(
            category="nature",
            title_template="Waterfront & Scenic Viewpoint Walk in {destination}",
            description_template=(
                "Take in panoramic vistas, coastal walkways, and scenic riverside "
                "trails across {destination}."
            ),
            is_indoor=False,
            preferred_time=TimeOfDay.AFTERNOON,
        ),
        ActivityTemplate(
            category="nature",
            title_template="Sunset Parklands Promenade in {destination}",
            description_template=(
                "Enjoy natural sunset light and evening fresh air from an open public "
                "lookout in {destination}."
            ),
            is_indoor=False,
            preferred_time=TimeOfDay.EVENING,
        ),
    ],
    "history": [
        ActivityTemplate(
            category="history",
            title_template="Historic Quarter Walking Exploration in {destination}",
            description_template=(
                "Stroll through historic architectural streets, heritage squares, "
                "and ancient civic monuments in {destination}."
            ),
            is_indoor=False,
            preferred_time=TimeOfDay.MORNING,
        ),
        ActivityTemplate(
            category="history",
            title_template="Heritage Archive & Historical Library in {destination}",
            description_template=(
                "Explore vintage town records, architectural exhibitions, and historic "
                "documents maintained in {destination}."
            ),
            is_indoor=True,
            preferred_time=TimeOfDay.AFTERNOON,
        ),
        ActivityTemplate(
            category="history",
            title_template="Illuminated Heritage Landmarks in {destination}",
            description_template=(
                "View ancient defensive walls, historic gateways, and illuminated "
                "civic edifices in {destination}."
            ),
            is_indoor=False,
            preferred_time=TimeOfDay.EVENING,
        ),
    ],
    "shopping": [
        ActivityTemplate(
            category="shopping",
            title_template="Artisanal Craft Market Browsing in {destination}",
            description_template=(
                "Discover handmade ceramics, woven textiles, and traditional craft "
                "goods made by local artisans in {destination}."
            ),
            is_indoor=True,
            preferred_time=TimeOfDay.MORNING,
        ),
        ActivityTemplate(
            category="shopping",
            title_template="Independent Boutiques & Specialty Shops in {destination}",
            description_template=(
                "Browse local stationery shops, regional pantry shops, and independent "
                "ateliers in {destination}."
            ),
            is_indoor=True,
            preferred_time=TimeOfDay.AFTERNOON,
        ),
        ActivityTemplate(
            category="shopping",
            title_template="Covered Commercial Arcade Exploration in {destination}",
            description_template=(
                "Stroll through protected 19th-century shopping arcades and design "
                "boutiques in {destination}."
            ),
            is_indoor=True,
            preferred_time=TimeOfDay.EVENING,
        ),
    ],
    "nightlife": [
        ActivityTemplate(
            category="nightlife",
            title_template="Acoustic Music & Cultural Performance in {destination}",
            description_template=(
                "Attend evening live musical performances, theatre presentations, "
                "or acoustic recitals in {destination}."
            ),
            is_indoor=True,
            preferred_time=TimeOfDay.EVENING,
        ),
        ActivityTemplate(
            category="nightlife",
            title_template="Social Hospitality & Evening Lounge in {destination}",
            description_template=(
                "Unwind with house-blended infusions, teas, and local refreshments at "
                "a lively evening gathering spot in {destination}."
            ),
            is_indoor=True,
            preferred_time=TimeOfDay.EVENING,
        ),
    ],
    "general": [
        ActivityTemplate(
            category="general",
            title_template="Civic Centre & Main Square Discovery in {destination}",
            description_template=(
                "Get oriented with main avenues, civic architecture, and public plazas "
                "in {destination}."
            ),
            is_indoor=False,
            preferred_time=TimeOfDay.MORNING,
        ),
        ActivityTemplate(
            category="nature",
            title_template="Scenic Public Park Walk in {destination}",
            description_template=(
                "Stroll through civic parks and fountain courtyards in {destination}."
            ),
            is_indoor=False,
            preferred_time=TimeOfDay.MORNING,
        ),
        ActivityTemplate(
            category="general",
            title_template="Cultural Quarter & Neighbourhood Stroll in {destination}",
            description_template=(
                "Wander through vibrant residential districts, public courtyards, and "
                "scenic lanes in {destination}."
            ),
            is_indoor=True,
            preferred_time=TimeOfDay.AFTERNOON,
        ),
        ActivityTemplate(
            category="general",
            title_template="Evening Promenade & Leisure Walk in {destination}",
            description_template=(
                "Join locals on an evening promenade along pedestrian boulevards and "
                "waterfront paths in {destination}."
            ),
            is_indoor=False,
            preferred_time=TimeOfDay.EVENING,
        ),
    ],
}


def _resolve_destination_label(destination: GeocodeResult | str) -> str:
    """Extract human-readable label from destination input."""
    if isinstance(destination, GeocodeResult):
        if destination.admin_region:
            return (
                f"{destination.name}, {destination.admin_region}, {destination.country}"
            )
        return f"{destination.name}, {destination.country}"
    return destination.strip()


def _get_time_slots_for_pace(pace: PacePreference) -> list[TimeOfDay]:
    """Map travel pace to ordered daily time of day slots."""
    if pace == PacePreference.RELAXED:
        return [TimeOfDay.MORNING, TimeOfDay.AFTERNOON]
    if pace == PacePreference.PACKED:
        return [
            TimeOfDay.MORNING,
            TimeOfDay.AFTERNOON,
            TimeOfDay.AFTERNOON,
            TimeOfDay.EVENING,
        ]
    # Default BALANCED
    return [TimeOfDay.MORNING, TimeOfDay.AFTERNOON, TimeOfDay.EVENING]


def _gather_candidate_templates(
    interests: Sequence[str],
) -> list[ActivityTemplate]:
    """Collect templates matching user interests with general fallback."""
    matched: list[ActivityTemplate] = []
    seen_titles: set[str] = set()

    # Normalize user interests
    for interest in interests:
        norm = interest.strip().lower()
        if norm in GENERIC_TEMPLATES:
            for tmpl in GENERIC_TEMPLATES[norm]:
                if tmpl.title_template not in seen_titles:
                    seen_titles.add(tmpl.title_template)
                    matched.append(tmpl)

    # Always ensure fallback templates are available
    for tmpl in GENERIC_TEMPLATES["general"]:
        if tmpl.title_template not in seen_titles:
            seen_titles.add(tmpl.title_template)
            matched.append(tmpl)

    return matched


def _calculate_budget_allocation(
    request: TripRequest,
    total_days: int,
) -> str:
    """Calculate per-day planning allocation or mark unknown."""
    if request.budget_amount is not None and request.currency is not None:
        daily_total = request.budget_amount / Decimal(total_days)
        per_person = daily_total / Decimal(request.party_size)
        return (
            f"Rough planning allocation: ~{daily_total:.2f} {request.currency}/day "
            f"(~{per_person:.2f} {request.currency} per person/day, estimate, not a "
            "price quote). Flights and accommodation are unquoted "
            "(no live rates retrieved)."
        )
    return "unknown (no budget specified; flights and accommodation unquoted)"


def _compile_warnings(
    request: TripRequest,
    total_days: int,
    weather: WeatherSummary | None,
    trip_dates: list[date],
    reference_today: date,
) -> list[str]:
    """Compile comprehensive planning warnings and data limitations."""
    warnings: list[str] = []

    # 1. Weather availability check
    if weather is None:
        warnings.append(
            "Weather forecast could not be retrieved; itinerary generated without "
            "weather context (weather marked unknown)."
        )
    else:
        # Check for mock data in use
        if (
            weather.data_origin == "mock"
            or getattr(weather.source, "data_origin", None) == "mock"
        ):
            warnings.append(
                "Mock weather data in use (data_origin='mock'). Real-time conditions "
                "are not reflected."
            )

        # Check for missing weather on specific dates
        covered_dates = {w.date for w in weather.days}
        missing_dates = [d for d in trip_dates if d not in covered_dates]
        if missing_dates:
            warnings.append(
                f"Weather forecast is missing for {len(missing_dates)} of {total_days} "
                "trip days; weather marked unknown for those dates."
            )

        # Check for out-of-horizon dates note from provider
        if weather.horizon_note:
            warnings.append(f"Weather horizon note: {weather.horizon_note}")
        elif (trip_dates[-1] - reference_today).days > 16:
            warnings.append(
                "Some trip dates exceed the 16-day forecast horizon. Check back closer "
                "to departure for live weather."
            )

    # 2. Budget threshold warning
    if request.budget_amount is not None and request.currency is not None:
        daily_per_person = request.budget_amount / (
            Decimal(total_days) * Decimal(request.party_size)
        )
        if daily_per_person < LOW_BUDGET_THRESHOLD_PER_DAY:
            warnings.append(
                f"Low budget warning: ~{daily_per_person:.2f} {request.currency} per "
                f"person/day is below the standard planning baseline of "
                f"{LOW_BUDGET_THRESHOLD_PER_DAY:.2f} {request.currency}/day. Consider "
                "allocating additional funds for transit and dining."
            )

    # 3. Packed pace with long trip duration warning
    if request.pace == PacePreference.PACKED and total_days > PACKED_LONG_TRIP_DAYS:
        warnings.append(
            f"Pace warning: Packed itinerary schedule spanning {total_days} days may "
            "induce traveler fatigue. Consider adding resting periods."
        )

    return warnings


def generate_itinerary(
    request: TripRequest,
    destination: GeocodeResult | str,
    weather: WeatherSummary | None = None,
    today: date | None = None,
    weather_as_item: bool = False,
) -> Itinerary:
    """Generate a pure, deterministic day-by-day travel itinerary.

    Args:
        request: Validated TripRequest intake model.
        destination: Normalized GeocodeResult or destination name string.
        weather: Optional WeatherSummary forecast from external provider.
        today: Injectable reference date for deterministic testing.
        weather_as_item: If True, prepends a dedicated retrieved weather briefing item.
                         If False (default), integrates weather details into item notes
                         and source references, strictly preserving pace item counts.

    Returns:
        Structured Itinerary instance conforming to Pydantic domain contracts.
    """
    reference_today = today or request.get_today()
    destination_label = _resolve_destination_label(destination)

    # Compute calendar trip dates
    trip_dates: list[date] = []
    curr_date = request.start_date
    while curr_date <= request.end_date:
        trip_dates.append(curr_date)
        curr_date = curr_date + timedelta(days=1)

    total_days = len(trip_dates)
    time_slots = _get_time_slots_for_pace(request.pace)
    required_item_count = PACE_ITEM_COUNTS[request.pace]
    candidate_templates = _gather_candidate_templates(request.interests)
    budget_allocation_text = _calculate_budget_allocation(request, total_days)

    # Weather map for O(1) date lookup
    weather_by_date: dict[date, WeatherDay] = {}
    if weather is not None:
        for w in weather.days:
            weather_by_date[w.date] = w

    # Compile warnings
    warnings = _compile_warnings(
        request=request,
        total_days=total_days,
        weather=weather,
        trip_dates=trip_dates,
        reference_today=reference_today,
    )

    itinerary_days: list[ItineraryDay] = []
    template_cursor = 0

    for day_idx, day_date in enumerate(trip_dates, start=1):
        day_weather = weather_by_date.get(day_date)
        is_rainy = (
            day_weather is not None
            and day_weather.precipitation_probability_pct
            >= RAIN_PROBABILITY_THRESHOLD_PCT
        )

        # Weather note and source attribution
        if day_weather is not None:
            weather_desc = (
                f"Forecast: {day_weather.condition_description}, "
                f"{day_weather.temp_min_c:.1f}°C to {day_weather.temp_max_c:.1f}°C, "
                f"rain chance {day_weather.precipitation_probability_pct}%."
            )
            weather_source_url: str | None = weather.source.url if weather else None
        else:
            weather_desc = (
                "Weather forecast is unknown for this date. "
                "Check closer to departure date."
            )
            weather_source_url = None

        day_items: list[ItineraryItem] = []

        # Optional dedicated weather item
        if weather_as_item:
            w_prov = (
                Provenance.RETRIEVED if day_weather is not None else Provenance.UNKNOWN
            )
            day_items.append(
                ItineraryItem(
                    title=f"Weather Briefing: {destination_label}",
                    time_of_day=TimeOfDay.MORNING,
                    description=weather_desc,
                    provenance=w_prov,
                    source_ref=weather_source_url,
                    note=(
                        f"Retrieved from {weather.source.provider}."
                        if day_weather is not None and weather is not None
                        else "No weather data retrieved."
                    ),
                    cost_estimate=None,
                )
            )

        # Determine activity templates for the day
        day_templates: list[ActivityTemplate] = []
        for _ in range(required_item_count):
            tmpl = candidate_templates[template_cursor % len(candidate_templates)]
            day_templates.append(tmpl)
            template_cursor += 1

        # Rain-driven ordering: prioritize indoor activities on rainy days
        if is_rainy:
            day_templates.sort(key=lambda t: 0 if t.is_indoor else 1)
        else:
            day_templates.sort(key=lambda t: 1 if t.is_indoor else 0)

        # Create scheduled activity items
        for slot_idx, tmpl in enumerate(day_templates):
            time_slot = time_slots[slot_idx % len(time_slots)]
            title = tmpl.title_template.format(destination=destination_label)
            description = tmpl.description_template.format(
                destination=destination_label
            )

            # Build contextual notes without banned booking terms
            item_notes: list[str] = [ADVISORY_NOTE]
            if slot_idx == 0:
                item_notes.append(weather_desc)
                if is_rainy:
                    rain_prob = day_weather.precipitation_probability_pct
                    item_notes.append(
                        f"High rain probability ({rain_prob}%); "
                        "indoor activities prioritized."
                    )

            day_items.append(
                ItineraryItem(
                    title=title,
                    time_of_day=time_slot,
                    description=description,
                    provenance=Provenance.GENERATED_SUGGESTION,
                    source_ref=weather_source_url if slot_idx == 0 else None,
                    note=" ".join(item_notes),
                    cost_estimate=budget_allocation_text,
                )
            )

        itinerary_days.append(
            ItineraryDay(
                day_number=day_idx,
                date=day_date,
                items=day_items,
            )
        )

    start_iso = request.start_date.isoformat()
    summary_text = (
        f"{total_days}-day itinerary for {destination_label} starting {start_iso} "
        f"({request.pace.value} pace, party of {request.party_size}). "
        f"{budget_allocation_text} All activities are generated suggestions."
    )
    if len(summary_text) > 500:
        summary_text = summary_text[:497] + "..."

    return Itinerary(
        days=itinerary_days,
        summary=summary_text,
        warnings=warnings,
    )
