"""Error response schemas."""

from typing import Any

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: list[dict[str, Any]] | None = Field(default=None)


class ErrorResponse(BaseModel):
    error: ErrorDetail


def pydantic_validation_error_to_error_response(
    exc: Any,
) -> ErrorResponse:
    """Map a Pydantic ValidationError onto the uniform 422 error shape."""
    details: list[dict[str, Any]] = []
    if hasattr(exc, "errors"):
        for err in exc.errors():
            details.append(
                {
                    "loc": [str(loc_item) for loc_item in err.get("loc", [])],
                    "msg": str(err.get("msg", "")),
                    "type": str(err.get("type", "")),
                }
            )
    return ErrorResponse(
        error=ErrorDetail(
            code="validation_error",
            message="Request validation failed",
            details=details if details else None,
        )
    )
