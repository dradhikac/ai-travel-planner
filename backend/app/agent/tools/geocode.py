"""Geocoding tool wrapping the Phase 2 Open-Meteo provider adapter."""

import asyncio
import concurrent.futures
import inspect
import time
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from app.agent.errors import ToolErrorCode
from app.agent.tools.contracts import GeocodeArgs, ToolResult, ToolStatus
from app.providers.open_meteo import (
    HttpError,
    MalformedResponseError,
    NetworkUnavailableError,
    OpenMeteoClient,
    ProviderError,
    RateLimitExceededError,
    TimeoutError,
)


def _run_coroutine_sync(coro: Any) -> Any:
    """Execute a coroutine synchronously, handling active and idle event loops."""
    if not inspect.isawaitable(coro):
        return coro
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


async def async_geocode_destination(
    args: GeocodeArgs | dict[str, Any] | None = None,
    client: Any | None = None,
    **kwargs: Any,
) -> ToolResult:
    """Asynchronously resolve destination coordinates via Open-Meteo adapter."""
    start_time = time.perf_counter()

    # 1. Validate arguments BEFORE making any external call
    validated_args: GeocodeArgs
    try:
        if isinstance(args, GeocodeArgs):
            validated_args = args
        elif isinstance(args, dict):
            validated_args = GeocodeArgs.model_validate(args)
        elif kwargs:
            validated_args = GeocodeArgs.model_validate(kwargs)
        elif args is None:
            raise ValueError("Missing required arguments for geocode_destination")
        else:
            raise ValueError(f"Expected GeocodeArgs or dict, got {type(args).__name__}")
    except (ValidationError, ValueError, TypeError) as err:
        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        safe_msg = f"Invalid arguments for geocoding: {err}"
        if len(safe_msg) > 400:
            safe_msg = safe_msg[:397] + "..."
        return ToolResult(
            tool_name="geocode_destination",
            status=ToolStatus.ERROR,
            data=None,
            error_code=ToolErrorCode.INVALID_ARGUMENTS,
            safe_message=safe_msg,
            data_origin="none",
            latency_ms=elapsed_ms,
            attempts=1,
        )

    # 2. Invoke adapter with bounded retries and exception mapping
    adapter = client or OpenMeteoClient()
    try:
        coro_or_res = adapter.search_destination(
            name=validated_args.query,
            count=validated_args.count,
        )
        if inspect.isawaitable(coro_or_res):
            results = await coro_or_res
        else:
            results = coro_or_res

        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

        # 3. Handle empty geocoding results (not an error)
        if not results:
            return ToolResult(
                tool_name="geocode_destination",
                status=ToolStatus.EMPTY,
                data=[],
                error_code=None,
                safe_message=f"No locations found for query '{validated_args.query}'.",
                source=None,
                fetched_at=datetime.now(UTC),
                data_origin="none",
                latency_ms=elapsed_ms,
                attempts=getattr(adapter, "last_attempts", 1),
            )

        # 4. Successful normalization
        first = results[0]
        data = [r.model_dump(mode="json") for r in results]
        return ToolResult(
            tool_name="geocode_destination",
            status=ToolStatus.OK,
            data=data,
            error_code=None,
            safe_message=None,
            source=first.source,
            fetched_at=first.fetched_at,
            data_origin=first.source.data_origin,
            latency_ms=elapsed_ms,
            attempts=getattr(adapter, "last_attempts", 1),
        )

    except TimeoutError:
        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        return ToolResult(
            tool_name="geocode_destination",
            status=ToolStatus.TIMEOUT,
            data=None,
            error_code=ToolErrorCode.TIMEOUT,
            safe_message="Geocoding service timed out. Please try again later.",
            data_origin="none",
            latency_ms=elapsed_ms,
            attempts=getattr(adapter, "last_attempts", 1),
        )

    except RateLimitExceededError:
        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        return ToolResult(
            tool_name="geocode_destination",
            status=ToolStatus.RATE_LIMITED,
            data=None,
            error_code=ToolErrorCode.RATE_LIMITED,
            safe_message=("Geocoding service rate limit exceeded. Please retry later."),
            data_origin="none",
            latency_ms=elapsed_ms,
            attempts=getattr(adapter, "last_attempts", 1),
        )

    except MalformedResponseError:
        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        return ToolResult(
            tool_name="geocode_destination",
            status=ToolStatus.ERROR,
            data=None,
            error_code=ToolErrorCode.MALFORMED_RESPONSE,
            safe_message="Geocoding service returned an unreadable response format.",
            data_origin="none",
            latency_ms=elapsed_ms,
            attempts=getattr(adapter, "last_attempts", 1),
        )

    except (NetworkUnavailableError, HttpError, ProviderError):
        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        return ToolResult(
            tool_name="geocode_destination",
            status=ToolStatus.ERROR,
            data=None,
            error_code=ToolErrorCode.PROVIDER_UNAVAILABLE,
            safe_message="Geocoding service is temporarily unreachable.",
            data_origin="none",
            latency_ms=elapsed_ms,
            attempts=getattr(adapter, "last_attempts", 1),
        )

    except Exception:
        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        return ToolResult(
            tool_name="geocode_destination",
            status=ToolStatus.ERROR,
            data=None,
            error_code=ToolErrorCode.EXECUTION_FAILED,
            safe_message="An unexpected error occurred during geocoding.",
            data_origin="none",
            latency_ms=elapsed_ms,
            attempts=getattr(adapter, "last_attempts", 1),
        )


def geocode_destination(
    args: GeocodeArgs | dict[str, Any] | None = None,
    client: Any | None = None,
    **kwargs: Any,
) -> ToolResult:
    """Synchronously resolve destination coordinates via Open-Meteo adapter."""
    return _run_coroutine_sync(
        async_geocode_destination(args=args, client=client, **kwargs)
    )
