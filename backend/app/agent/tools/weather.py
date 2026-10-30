"""Weather forecast tool wrapping the Phase 2 Open-Meteo provider adapter."""

import asyncio
import concurrent.futures
import inspect
import time
from typing import Any

from pydantic import ValidationError

from app.agent.errors import ToolErrorCode
from app.agent.tools.contracts import ToolResult, ToolStatus, WeatherArgs
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


async def async_get_weather(
    args: WeatherArgs | dict[str, Any] | None = None,
    client: Any | None = None,
    **kwargs: Any,
) -> ToolResult:
    """Asynchronously retrieve weather forecasts via Open-Meteo adapter."""
    start_time = time.perf_counter()

    # 1. Validate arguments BEFORE making any external call
    validated_args: WeatherArgs
    try:
        if isinstance(args, WeatherArgs):
            validated_args = args
        elif isinstance(args, dict):
            validated_args = WeatherArgs.model_validate(args)
        elif kwargs:
            validated_args = WeatherArgs.model_validate(kwargs)
        elif args is None:
            raise ValueError("Missing required arguments for get_weather")
        else:
            raise ValueError(f"Expected WeatherArgs or dict, got {type(args).__name__}")
    except (ValidationError, ValueError, TypeError) as err:
        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        safe_msg = f"Invalid arguments for weather forecast: {err}"
        if len(safe_msg) > 400:
            safe_msg = safe_msg[:397] + "..."
        return ToolResult(
            tool_name="get_weather",
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
        coro_or_res = adapter.get_daily_forecast(
            latitude=validated_args.latitude,
            longitude=validated_args.longitude,
            start=validated_args.start_date,
            end=validated_args.end_date,
        )
        if inspect.isawaitable(coro_or_res):
            summary = await coro_or_res
        else:
            summary = coro_or_res

        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        summary_dict = summary.model_dump(mode="json")

        # 3. Handle dates completely outside the 16-day forecast horizon
        if not summary.days or summary.horizon_note is not None:
            horizon_msg = summary.horizon_note or (
                "Weather forecast is unavailable for dates beyond "
                "the 16-day forecast horizon."
            )
            return ToolResult(
                tool_name="get_weather",
                status=ToolStatus.EMPTY,
                data=summary_dict,
                error_code=ToolErrorCode.OUT_OF_FORECAST_RANGE,
                safe_message=horizon_msg,
                source=summary.source,
                fetched_at=summary.fetched_at,
                data_origin=summary.data_origin,
                latency_ms=elapsed_ms,
                attempts=getattr(adapter, "last_attempts", 1),
            )

        # 4. Successful normalization inside forecast horizon
        return ToolResult(
            tool_name="get_weather",
            status=ToolStatus.OK,
            data=summary_dict,
            error_code=None,
            safe_message=None,
            source=summary.source,
            fetched_at=summary.fetched_at,
            data_origin=summary.data_origin,
            latency_ms=elapsed_ms,
            attempts=getattr(adapter, "last_attempts", 1),
        )

    except TimeoutError:
        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        return ToolResult(
            tool_name="get_weather",
            status=ToolStatus.TIMEOUT,
            data=None,
            error_code=ToolErrorCode.TIMEOUT,
            safe_message="Weather service timed out. Please try again later.",
            data_origin="none",
            latency_ms=elapsed_ms,
            attempts=getattr(adapter, "last_attempts", 1),
        )

    except RateLimitExceededError:
        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        return ToolResult(
            tool_name="get_weather",
            status=ToolStatus.RATE_LIMITED,
            data=None,
            error_code=ToolErrorCode.RATE_LIMITED,
            safe_message=("Weather service rate limit exceeded. Please retry later."),
            data_origin="none",
            latency_ms=elapsed_ms,
            attempts=getattr(adapter, "last_attempts", 1),
        )

    except MalformedResponseError:
        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        return ToolResult(
            tool_name="get_weather",
            status=ToolStatus.ERROR,
            data=None,
            error_code=ToolErrorCode.MALFORMED_RESPONSE,
            safe_message="Weather service returned an unreadable response format.",
            data_origin="none",
            latency_ms=elapsed_ms,
            attempts=getattr(adapter, "last_attempts", 1),
        )

    except (NetworkUnavailableError, HttpError, ProviderError):
        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        return ToolResult(
            tool_name="get_weather",
            status=ToolStatus.ERROR,
            data=None,
            error_code=ToolErrorCode.PROVIDER_UNAVAILABLE,
            safe_message="Weather service is temporarily unreachable.",
            data_origin="none",
            latency_ms=elapsed_ms,
            attempts=getattr(adapter, "last_attempts", 1),
        )

    except Exception:
        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        return ToolResult(
            tool_name="get_weather",
            status=ToolStatus.ERROR,
            data=None,
            error_code=ToolErrorCode.EXECUTION_FAILED,
            safe_message="An unexpected error occurred while retrieving weather.",
            data_origin="none",
            latency_ms=elapsed_ms,
            attempts=getattr(adapter, "last_attempts", 1),
        )


def get_weather(
    args: WeatherArgs | dict[str, Any] | None = None,
    client: Any | None = None,
    **kwargs: Any,
) -> ToolResult:
    """Synchronously retrieve weather forecasts via Open-Meteo adapter."""
    return _run_coroutine_sync(async_get_weather(args=args, client=client, **kwargs))
