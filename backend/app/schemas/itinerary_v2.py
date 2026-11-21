"""Structured Itinerary Schema v2 and in-memory v1 upgrader.

Implements Schema v2 specifications from docs/phase4-5/reliability-contracts.md.
Provides fine-grained activity identification, duration estimates, explicit
provenance, uncertainty tracking, and structured cost statuses.
"""

import json
from datetime import date
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.provider import Provenance, SourceInfo


class DurationBasis(StrEnum):
    """Source basis for an activity duration estimate."""

    PROVIDER = "provider"
    HEURISTIC = "heuristic"
    UNKNOWN = "unknown"


class CostStatus(StrEnum):
    """Status classification of activity cost."""

    UNKNOWN = "unknown"
    ESTIMATE = "estimate"
    RETRIEVED = "retrieved"  # Strictly requires at least one matching source_ref


class ActivityLocation(BaseModel):
    """Geographic location details for an activity."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=150)
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)
    source_ref: str | None = Field(
        default=None, description="Key into root sources list"
    )


# Canonical alias
Location = ActivityLocation


class DurationEstimate(BaseModel):
    """Estimated duration of an activity."""

    model_config = ConfigDict(extra="forbid")

    min_minutes: int | None = Field(default=None, ge=5, le=1440)
    max_minutes: int | None = Field(default=None, ge=5, le=1440)
    basis: DurationBasis = Field(default=DurationBasis.HEURISTIC)

    @model_validator(mode="after")
    def validate_duration_range(self) -> "DurationEstimate":
        if (
            self.min_minutes is not None
            and self.max_minutes is not None
            and self.min_minutes > self.max_minutes
        ):
            raise ValueError("min_minutes cannot exceed max_minutes")
        return self


class ItineraryActivityV2(BaseModel):
    """Activity entry within an itinerary day (Schema v2)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        ..., min_length=1, max_length=64, description="Unique ID within version"
    )
    title: str = Field(..., min_length=1, max_length=150)
    description: str | None = Field(
        default=None,
        max_length=500,
        description="Detailed activity description",
    )
    time_of_day: str | None = Field(
        default=None,
        description="Optional time of day (morning, afternoon, evening)",
    )
    interest_tags: list[str] = Field(default_factory=list, max_length=10)
    location: ActivityLocation | None = None
    duration_estimate: DurationEstimate | None = None
    source_refs: list[str] = Field(
        default_factory=list,
        description="Keys into root sources list for retrieved claims",
    )
    provenance: Provenance = Field(default=Provenance.GENERATED_SUGGESTION)
    cost_status: CostStatus = Field(default=CostStatus.UNKNOWN)
    cost_note: str | None = Field(
        default=None,
        description="Non-booking cost notes or price tier estimates.",
    )
    uncertainty_notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_retrieved_claims_have_sources(self) -> "ItineraryActivityV2":
        if self.cost_status == CostStatus.RETRIEVED and not self.source_refs:
            msg = (
                "Activity with cost_status='retrieved' must specify at least "
                "one source_ref"
            )
            raise ValueError(msg)
        if self.provenance == Provenance.RETRIEVED and not self.source_refs:
            msg = (
                "Activity with provenance='retrieved' must specify at least "
                "one source_ref"
            )
            raise ValueError(msg)
        return self

    # Backward compatibility properties for code expecting Phase 2 ItineraryItem
    @property
    def source_ref(self) -> str | None:
        """First source reference if available."""
        return self.source_refs[0] if self.source_refs else None

    @property
    def cost_estimate(self) -> str | None:
        """Alias for cost_note."""
        return self.cost_note

    @property
    def note(self) -> str | None:
        """Joined uncertainty notes."""
        return " ".join(self.uncertainty_notes) if self.uncertainty_notes else None


# Canonical aliases
Activity = ItineraryActivityV2
ItineraryActivity = ItineraryActivityV2


class ItineraryDayV2(BaseModel):
    """Day itinerary containing v2 activities."""

    model_config = ConfigDict(extra="forbid")

    day_number: int = Field(..., ge=1)
    date: date
    activities: list[ItineraryActivityV2] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def populate_activities_from_items(cls, data: Any) -> Any:
        """Allow initializing with 'items' for v1 backward compatibility."""
        if isinstance(data, dict) and "items" in data and "activities" not in data:
            raw_items = data.get("items", [])
            day_num = data.get("day_number", 1)
            activities: list[dict[str, Any]] = []
            for idx, item in enumerate(raw_items, start=1):
                if hasattr(item, "model_dump"):
                    item = item.model_dump(mode="python")
                elif not isinstance(item, dict):
                    continue

                act_id = item.get("id") or f"day_{day_num}_act_{idx}"
                s_ref = item.get("source_ref")
                s_refs = item.get("source_refs") or ([s_ref] if s_ref else [])
                c_est = item.get("cost_estimate") or item.get("cost_note")
                c_stat = item.get("cost_status")
                prov = (
                    item["provenance"]
                    if "provenance" in item
                    else Provenance.GENERATED_SUGGESTION
                )
                if not c_stat:
                    if c_est and prov == Provenance.RETRIEVED and s_refs:
                        c_stat = CostStatus.RETRIEVED
                    elif c_est or prov == Provenance.ESTIMATE:
                        c_stat = CostStatus.ESTIMATE
                    else:
                        c_stat = CostStatus.UNKNOWN

                u_notes = item.get("uncertainty_notes") or []
                if not u_notes and item.get("note"):
                    u_notes = [item["note"]]

                dur = item.get("duration_estimate")
                if not dur:
                    dur = DurationEstimate(
                        min_minutes=60,
                        max_minutes=180,
                        basis=DurationBasis.HEURISTIC,
                    )

                activities.append(
                    {
                        "id": act_id,
                        "title": item.get("title", "Activity"),
                        "description": item.get("description"),
                        "time_of_day": (
                            str(item["time_of_day"].value)
                            if hasattr(item.get("time_of_day"), "value")
                            else item.get("time_of_day")
                        ),
                        "interest_tags": item.get("interest_tags", []),
                        "location": item.get("location"),
                        "duration_estimate": dur,
                        "source_refs": s_refs,
                        "provenance": prov,
                        "cost_status": c_stat,
                        "cost_note": c_est,
                        "uncertainty_notes": u_notes,
                    }
                )
            data = {k: v for k, v in data.items() if k != "items"}
            data["activities"] = activities
        return data

    @property
    def items(self) -> list[ItineraryActivityV2]:
        """Backward compatibility alias returning activities."""
        return self.activities


# Canonical alias
ItineraryDay = ItineraryDayV2


class ItineraryV2(BaseModel):
    """Root generated itinerary contract (Schema v2)."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2] = 2
    summary: str = Field(..., min_length=1, max_length=500)
    sources: list[SourceInfo] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    days: list[ItineraryDayV2] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def set_default_schema_version(cls, data: Any) -> Any:
        if isinstance(data, dict) and "schema_version" not in data:
            data = {**data, "schema_version": 2}
        return data

    @model_validator(mode="after")
    def validate_all_activities_provenance(self) -> "ItineraryV2":
        for day in self.days:
            for act in day.activities:
                if act.provenance is None or not isinstance(act.provenance, Provenance):
                    raise ValueError(
                        "Itinerary activities must specify a valid Provenance"
                    )
        return self


# Canonical alias
Itinerary = ItineraryV2


def upgrade_itinerary_v1_to_v2(v1: dict[str, Any]) -> ItineraryV2:
    """Convert a stored Phase 2 Itinerary v1 dict to ItineraryV2 in memory.

    Non-destructive: does not modify or persist back to the database.
    - items -> activities
    - item source_ref -> source_refs
    - location -> null
    - duration -> heuristic
    - cost_status -> derived from provenance & cost_estimate
    - uncertainty notes -> carried from item notes
    """
    v2_days: list[ItineraryDayV2] = []
    for day in v1.get("days", []):
        day_num = day.get("day_number", 1)
        raw_date = day.get("date")
        if isinstance(raw_date, str):
            day_date = date.fromisoformat(raw_date)
        elif isinstance(raw_date, date):
            day_date = raw_date
        else:
            day_date = date.today()

        v2_activities: list[ItineraryActivityV2] = []
        raw_items = day.get("items", []) or day.get("activities", [])
        for idx, item in enumerate(raw_items, start=1):
            if hasattr(item, "model_dump"):
                item = item.model_dump(mode="python")
            elif not isinstance(item, dict):
                continue

            act_id = item.get("id") or f"day_{day_num}_act_{idx}"
            title = item.get("title", "Activity")
            description = item.get("description")
            time_of_day = (
                str(item["time_of_day"].value)
                if hasattr(item.get("time_of_day"), "value")
                else item.get("time_of_day")
            )

            source_ref = item.get("source_ref")
            source_refs = item.get("source_refs") or (
                [str(source_ref)] if source_ref else []
            )

            duration = item.get("duration_estimate")
            if duration is None:
                duration = DurationEstimate(
                    min_minutes=60,
                    max_minutes=180,
                    basis=DurationBasis.HEURISTIC,
                )
            elif isinstance(duration, dict):
                duration = DurationEstimate.model_validate(duration)

            raw_prov = item.get("provenance", Provenance.GENERATED_SUGGESTION)
            if isinstance(raw_prov, str):
                try:
                    prov = Provenance(raw_prov)
                except ValueError:
                    prov = Provenance.GENERATED_SUGGESTION
            elif isinstance(raw_prov, Provenance):
                prov = raw_prov
            else:
                prov = Provenance.GENERATED_SUGGESTION

            # Safety fallback: retrieved claims require source references
            if prov == Provenance.RETRIEVED and not source_refs:
                prov = Provenance.GENERATED_SUGGESTION

            cost_est = item.get("cost_estimate") or item.get("cost_note")
            raw_cost_stat = item.get("cost_status")
            if raw_cost_stat:
                try:
                    cost_status = CostStatus(raw_cost_stat)
                except ValueError:
                    cost_status = CostStatus.UNKNOWN
            elif cost_est and prov == Provenance.RETRIEVED and source_refs:
                cost_status = CostStatus.RETRIEVED
            elif cost_est or prov == Provenance.ESTIMATE:
                cost_status = CostStatus.ESTIMATE
            else:
                cost_status = CostStatus.UNKNOWN

            if cost_status == CostStatus.RETRIEVED and not source_refs:
                cost_status = CostStatus.ESTIMATE if cost_est else CostStatus.UNKNOWN

            uncertainty_notes: list[str] = []
            if item.get("uncertainty_notes"):
                uncertainty_notes.extend(item["uncertainty_notes"])
            elif item.get("note"):
                uncertainty_notes.append(item["note"])

            v2_activities.append(
                ItineraryActivityV2(
                    id=act_id,
                    title=title,
                    description=description,
                    time_of_day=time_of_day,
                    interest_tags=item.get("interest_tags", []),
                    location=None,
                    duration_estimate=duration,
                    source_refs=source_refs,
                    provenance=prov,
                    cost_status=cost_status,
                    cost_note=cost_est,
                    uncertainty_notes=uncertainty_notes,
                )
            )

        day_uncertainty = list(day.get("uncertainty_notes", []))
        v2_days.append(
            ItineraryDayV2(
                day_number=day_num,
                date=day_date,
                activities=v2_activities,
                uncertainty_notes=day_uncertainty,
            )
        )

    return ItineraryV2(
        schema_version=2,
        summary=v1.get("summary", ""),
        sources=v1.get("sources", []),
        warnings=v1.get("warnings", []),
        days=v2_days,
    )


def parse_itinerary_payload(payload: Any) -> ItineraryV2:
    """Parse an itinerary payload directly if v2 or upgrade from v1 in memory.

    Accepts dict, JSON string, ItineraryV2, or legacy Itinerary objects.
    Raises ValueError on invalid input or unsupported schema versions.
    Never writes the upgraded form back to the database.
    """
    if isinstance(payload, ItineraryV2):
        return payload

    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception as exc:
            raise ValueError(
                f"Invalid JSON string payload for itinerary: {exc}"
            ) from exc

    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="python")

    if not isinstance(payload, dict):
        got_type = type(payload).__name__
        msg = (
            f"Expected dictionary or JSON string for itinerary payload, got {got_type}"
        )
        raise ValueError(msg)

    if "schema_version" in payload:
        raw_version = payload["schema_version"]
        try:
            version_int = int(raw_version)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"Unsupported itinerary schema version: {raw_version}"
            ) from exc

        if version_int == 2:
            return ItineraryV2.model_validate(payload)
        elif version_int == 1:
            return upgrade_itinerary_v1_to_v2(payload)
        else:
            raise ValueError(f"Unsupported itinerary schema version: {raw_version}")
    else:
        # Absence of schema_version indicates stored v1 payload from Phase 2
        return upgrade_itinerary_v1_to_v2(payload)
