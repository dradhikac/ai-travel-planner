"""Error response schemas."""

from typing import Any

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: list[dict[str, Any]] | None = Field(default=None)


class ErrorResponse(BaseModel):
    error: ErrorDetail
