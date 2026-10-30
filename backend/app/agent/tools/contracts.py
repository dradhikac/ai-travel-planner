"""Tool contracts, argument models, and result envelopes for Phase 3 agent tools."""

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.agent.errors import ToolErrorCode
from app.schemas.provider import SourceInfo


class ToolStatus(StrEnum):
    """Execution status of an agent tool invocation."""

    OK = "ok"
    EMPTY = "empty"
    ERROR = "error"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    SKIPPED = "skipped"


class ToolResult(BaseModel):
    """Structured envelope returned by any agent tool execution.

    Enforces truthfulness and strict invariants: a failed or skipped result
    must be impossible to confuse with a live success.
    """

    model_config = ConfigDict(extra="forbid")

    tool_name: str = Field(
        ..., min_length=1, max_length=100, description="Name of the invoked tool"
    )
    status: ToolStatus = Field(..., description="Execution status outcome")
    data: dict[str, Any] | list[Any] | None = Field(
        default=None,
        description="Normalized structured output payload, or None on failure",
    )
    error_code: ToolErrorCode | None = Field(
        default=None, description="Stable safe error classification"
    )
    safe_message: str | None = Field(
        default=None,
        max_length=500,
        description="Sanitized human-readable diagnostic message",
    )
    source: SourceInfo | None = Field(
        default=None,
        description="External provider attribution metadata",
    )
    fetched_at: datetime | None = Field(
        default=None, description="UTC timestamp when data was retrieved"
    )
    data_origin: Literal["live", "mock", "none"] = Field(
        default="none",
        description="Origin classification of data payload (live, mock, or none)",
    )
    latency_ms: float = Field(
        default=0.0,
        ge=0.0,
        description="Elapsed execution latency in milliseconds",
    )
    attempts: int = Field(
        default=1,
        ge=1,
        description="Number of attempts executed by tool wrapper",
    )

    @field_validator("fetched_at", mode="after")
    @classmethod
    def ensure_utc_timezone(cls, v: datetime | None) -> datetime | None:
        """Ensure fetched_at timestamp is timezone-aware UTC."""
        if v is None:
            return None
        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v.astimezone(UTC)

    @model_validator(mode="after")
    def validate_tool_result_invariants(self) -> "ToolResult":
        """Enforce strict truthfulness invariants between status and data_origin.

        Rule: data_origin must be 'none' unless status is 'ok' or 'empty'.
        Failed or skipped tool results cannot claim 'live' or 'mock' data origin.
        """
        valid_success_statuses = {ToolStatus.OK, ToolStatus.EMPTY}
        if self.status not in valid_success_statuses and self.data_origin != "none":
            raise ValueError(
                f"data_origin must be 'none' for failed or skipped status "
                f"'{self.status.value}', got '{self.data_origin}'."
            )

        # When status is OK, data should not be none unless explicitly allowed
        if self.status == ToolStatus.OK and self.data is None:
            raise ValueError("ToolResult with status 'ok' must contain non-null data.")

        return self


class GeocodeArgs(BaseModel):
    """Validated arguments contract for destination geocoding resolution."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Destination city, region, or landmark to geocode",
    )
    country_code: str | None = Field(
        default=None,
        min_length=2,
        max_length=2,
        description="Optional ISO 3166-1 alpha-2 country code constraint",
    )
    count: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Maximum candidate locations to return (1 to 10)",
    )

    @field_validator("query", mode="before")
    @classmethod
    def normalize_query_string(cls, v: object) -> object:
        """Trim, collapse consecutive whitespace, and reject blank queries."""
        if isinstance(v, str):
            collapsed = " ".join(v.strip().split())
            if not collapsed:
                raise ValueError("Location query cannot be empty or whitespace only")
            return collapsed
        return v

    @field_validator("country_code", mode="before")
    @classmethod
    def normalize_country_code(cls, v: object) -> object:
        """Trim and uppercase 2-letter country code if present."""
        if v is None:
            return None
        if isinstance(v, str):
            trimmed = v.strip().upper()
            if not trimmed:
                return None
            if not trimmed.isalpha() or len(trimmed) != 2:
                raise ValueError("country_code must be a 2-letter alphabetic ISO code")
            return trimmed
        return v


class WeatherArgs(BaseModel):
    """Validated arguments contract for daily weather forecast retrieval."""

    model_config = ConfigDict(extra="forbid")

    latitude: float = Field(
        ...,
        ge=-90.0,
        le=90.0,
        description="Latitude geographical coordinate between -90 and 90",
    )
    longitude: float = Field(
        ...,
        ge=-180.0,
        le=180.0,
        description="Longitude geographical coordinate between -180 and 180",
    )
    start_date: date = Field(..., description="Trip start date (ISO 8601)")
    end_date: date = Field(..., description="Trip end date (ISO 8601)")

    @model_validator(mode="after")
    def validate_date_boundaries(self) -> "WeatherArgs":
        """Validate chronological date ordering and maximum forecast range."""
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")

        duration_days = (self.end_date - self.start_date).days + 1
        if duration_days > 30:
            raise ValueError(
                f"Weather forecast date range ({duration_days} days) "
                "exceeds maximum allowed limit of 30 days"
            )
        return self


class ToolCall(BaseModel):
    """Typed tool call planned or executed by the agent workflow."""

    model_config = ConfigDict(extra="forbid")

    tool_name: str = Field(
        ..., min_length=1, max_length=100, description="Target tool identifier"
    )
    arguments: dict[str, Any] = Field(
        default_factory=dict, description="Validated tool invocation arguments"
    )
    call_id: str | None = Field(
        default=None, description="Optional unique identifier for tracing"
    )

