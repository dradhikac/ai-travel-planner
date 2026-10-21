"""Centralized exception handlers ensuring uniform error response shapes."""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

STATUS_CODE_MAP = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    429: "too_many_requests",
    503: "service_unavailable",
}


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Handle standard HTTP exceptions with uniform error shape."""
    code = STATUS_CODE_MAP.get(exc.status_code, f"http_error_{exc.status_code}")
    message = str(exc.detail) if exc.detail else "An HTTP error occurred"
    content = {
        "error": {
            "code": code,
            "message": message,
        }
    }
    return JSONResponse(
        status_code=exc.status_code,
        content=content,
        headers=exc.headers,
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle request validation errors with safe details list."""
    safe_details: list[dict[str, Any]] = []
    for err in exc.errors():
        safe_details.append(
            {
                "loc": [str(loc_item) for loc_item in err.get("loc", [])],
                "msg": str(err.get("msg", "")),
                "type": str(err.get("type", "")),
            }
        )
    content = {
        "error": {
            "code": "validation_error",
            "message": "Request validation failed",
            "details": safe_details,
        }
    }
    return JSONResponse(status_code=422, content=content)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unhandled exceptions without leaking internals or stack traces."""
    logger.exception("Unhandled server exception: %s", exc)
    content = {
        "error": {
            "code": "internal_server_error",
            "message": "An internal server error occurred",
        }
    }
    return JSONResponse(status_code=500, content=content)


def register_error_handlers(app: FastAPI) -> None:
    """Register custom exception handlers on FastAPI application."""
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
