"""Route context tool wrapping the OpenRouteService provider adapter."""

import asyncio
import concurrent.futures
import inspect
import time
from typing import Any

from pydantic import ValidationError

from app.agent.errors import ToolErrorCode
from app.agent.tools.contracts import (
    RouteArgs,
    ToolResult,
    ToolStatus,
    provider_error_to_tool_result,
)
from app.providers.errors import ProviderError
from app.providers.openrouteservice import OpenRouteServiceClient, RouteNotFoundError


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


async def async_get_route_context(
    args: RouteArgs | dict[str, Any] | None = None,
    client: Any | None = None,
    **kwargs: Any,
) -> ToolResult:
    """Asynchronously retrieve route context via OpenRouteService adapter.

    Calculates travel distance (km) and estimated transit duration (minutes)
    between two coordinates for walking, cycling, or driving.

    Returns:
        ToolResult envelope with normalized payload or safe error classification.
        Never raises an unhandled exception.
    """
    start_time = time.perf_counter()

    # 1. Validate arguments BEFORE making any external call
    validated_args: RouteArgs
    try:
        if isinstance(args, RouteArgs):
            validated_args = args
        elif isinstance(args, dict):
            validated_args = RouteArgs.model_validate(args)
        elif kwargs:
            validated_args = RouteArgs.model_validate(kwargs)
        elif args is None:
            raise ValueError("Missing required arguments for get_route_context")
        else:
            raise ValueError(f"Expected RouteArgs or dict, got {type(args).__name__}")
    except (ValidationError, ValueError, TypeError) as err:
        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        safe_msg = f"Invalid arguments for route context: {err}"
        if len(safe_msg) > 400:
            safe_msg = safe_msg[:397] + "..."
        return ToolResult(
            tool_name="get_route_context",
            status=ToolStatus.ERROR,
            data=None,
            error_code=ToolErrorCode.INVALID_ARGUMENTS,
            safe_message=safe_msg,
            data_origin="none",
            latency_ms=elapsed_ms,
            attempts=1,
        )

    # 2. Invoke adapter with bounded retries and exception mapping
    adapter = client or OpenRouteServiceClient()
    try:
        coro_or_res = adapter.get_route(
            origin=(validated_args.origin_lat, validated_args.origin_lon),
            destination=(validated_args.dest_lat, validated_args.dest_lon),
            mode=validated_args.mode,
        )
        if inspect.isawaitable(coro_or_res):
            summary = await coro_or_res
        else:
            summary = coro_or_res

        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        summary_dict = summary.model_dump(mode="json")

        return ToolResult(
            tool_name="get_route_context",
            status=ToolStatus.OK,
            data=summary_dict,
            error_code=None,
            safe_message=None,
            source=summary.source,
            fetched_at=summary.fetched_at,
            data_origin=summary.data_origin,
            latency_ms=elapsed_ms,
            attempts=1,
        )

    except RouteNotFoundError as err:
        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        fallback_msg = "No routable path found between coordinates."
        return ToolResult(
            tool_name="get_route_context",
            status=ToolStatus.EMPTY,
            data=[],
            error_code=None,
            safe_message=err.safe_message or fallback_msg,
            source=None,
            fetched_at=None,
            data_origin="none",
            latency_ms=elapsed_ms,
            attempts=1,
        )

    except ValueError as err:
        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        safe_msg = f"Invalid route parameters: {err}"
        if len(safe_msg) > 400:
            safe_msg = safe_msg[:397] + "..."
        return ToolResult(
            tool_name="get_route_context",
            status=ToolStatus.ERROR,
            data=None,
            error_code=ToolErrorCode.INVALID_ARGUMENTS,
            safe_message=safe_msg,
            data_origin="none",
            latency_ms=elapsed_ms,
            attempts=1,
        )

    except ProviderError as err:
        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        attempts = getattr(err, "attempts", 1)
        return provider_error_to_tool_result(
            err=err,
            tool_name="get_route_context",
            latency_ms=elapsed_ms,
            attempts=attempts,
        )

    except Exception as err:
        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        safe_msg = f"An unexpected failure occurred while calculating route: {err}"
        return ToolResult(
            tool_name="get_route_context",
            status=ToolStatus.ERROR,
            data=None,
            error_code=ToolErrorCode.EXECUTION_FAILED,
            safe_message=safe_msg,
            data_origin="none",
            latency_ms=elapsed_ms,
            attempts=1,
        )


def get_route_context(
    args: RouteArgs | dict[str, Any] | None = None,
    client: Any | None = None,
    **kwargs: Any,
) -> ToolResult:
    """Synchronously retrieve route context via OpenRouteService adapter.

    Wraps async_get_route_context for environments and callers operating
    in synchronous execution contexts.
    """
    return _run_coroutine_sync(
        async_get_route_context(args=args, client=client, **kwargs)
    )
