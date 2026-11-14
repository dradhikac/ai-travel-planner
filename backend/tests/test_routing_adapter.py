"""Unit tests for OpenRouteService routing provider adapter and agent tool."""

import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from langchain_core.tools import StructuredTool

from app.agent.errors import ToolErrorCode
from app.agent.tools.contracts import ToolResult, ToolStatus
from app.agent.tools.registry import TOOL_REGISTRY, create_tool_registry
from app.agent.tools.route import get_route_context
from app.core.config import Settings
from app.providers.errors import ErrorCode, ProviderError
from app.providers.openrouteservice.client import (
    OpenRouteServiceClient,
    RouteNotFoundError,
    haversine_distance_km,
    validate_route_inputs,
)
from app.schemas.provider import RouteSummary

# Standard test coordinates (Paris: Louvre to Eiffel Tower)
LOUVRE_COORDS = (48.8606, 2.3364)
EIFFEL_COORDS = (48.8584, 2.2945)

# Standard mock ORS Directions v2 JSON payload
VALID_ORS_RESPONSE: dict[str, Any] = {
    "routes": [
        {
            "summary": {
                "distance": 3752.4,
                "duration": 2880.0,
            },
            "segments": [
                {
                    "distance": 3752.4,
                    "duration": 2880.0,
                }
            ],
            "bbox": [2.2945, 48.8566, 2.3522, 48.8584],
            "way_points": [0, 1],
        }
    ],
    "metadata": {
        "attribution": "openrouteservice.org | OpenStreetMap contributors",
        "service": "routing",
        "timestamp": 1690000000000,
        "query": {
            "coordinates": [[2.3364, 48.8606], [2.2945, 48.8584]],
            "profile": "foot-walking",
        },
    },
}


# ==============================================================================
# 1. Input Validation & Coordinate Bounds
# ==============================================================================


def test_coordinate_order_mistake_rejected_before_request() -> None:
    """Latitude out of range caused by swapping lat/lon is rejected before request."""
    # Longitude (139.7) accidentally passed as latitude
    with pytest.raises(ValueError, match="latitude 139.7 out of range"):
        validate_route_inputs(
            origin=(139.7, 35.6),
            destination=(EIFFEL_COORDS[0], EIFFEL_COORDS[1]),
            mode="walking",
        )


def test_longitude_out_of_range_rejected() -> None:
    """Longitude outside [-180, 180] is rejected before request."""
    with pytest.raises(ValueError, match="longitude 200.0 out of range"):
        validate_route_inputs(
            origin=(48.85, 200.0),
            destination=EIFFEL_COORDS,
            mode="walking",
        )


def test_identical_endpoints_rejected_before_request() -> None:
    """Routing between identical origin and destination coordinates is rejected."""
    with pytest.raises(ValueError, match="cannot be identical"):
        validate_route_inputs(
            origin=LOUVRE_COORDS,
            destination=LOUVRE_COORDS,
            mode="walking",
        )


def test_disallowed_mode_rejected_before_request() -> None:
    """Transit modes outside allow-list (walking, cycling, driving) are rejected."""
    with pytest.raises(ValueError, match="Invalid transit mode 'flying'"):
        validate_route_inputs(
            origin=LOUVRE_COORDS,
            destination=EIFFEL_COORDS,
            mode="flying",
        )


def test_maximum_distance_sanity_check() -> None:
    """Walking route exceeding 500 km sanity limit is rejected before request."""
    # Paris to Rome (~1100 km)
    rome_coords = (41.89, 12.51)
    with pytest.raises(ValueError, match="exceeds maximum sanity threshold"):
        validate_route_inputs(
            origin=LOUVRE_COORDS,
            destination=rome_coords,
            mode="walking",
        )


def test_haversine_distance_computation() -> None:
    """Haversine formula calculates known great-circle distance accurately."""
    # Paris to London is ~343 km
    london_coords = (51.5074, -0.1278)
    dist = haversine_distance_km(
        LOUVRE_COORDS[0], LOUVRE_COORDS[1], london_coords[0], london_coords[1]
    )
    assert 340.0 < dist < 350.0


# ==============================================================================
# 2. Normalization & Successful Response Handling
# ==============================================================================


def test_route_normalization_success() -> None:
    """Successful ORS response normalizes into RouteSummary with correct metrics."""
    captured_auth: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        assert "foot-walking" in str(request.url)
        # Verify key is strictly in Authorization header, never in URL
        captured_auth.append(request.headers.get("Authorization", ""))
        assert "test-secret-key" not in str(request.url)
        return httpx.Response(200, json=VALID_ORS_RESPONSE)

    transport = httpx.MockTransport(_handler)
    settings = Settings(
        ROUTING_PROVIDER_MODE="live",
        OPENROUTESERVICE_API_KEY="test-secret-key",
    )
    client = OpenRouteServiceClient(settings=settings, transport=transport)

    summary = asyncio.run(
        client.get_route(LOUVRE_COORDS, EIFFEL_COORDS, mode="walking")
    )

    assert isinstance(summary, RouteSummary)
    assert summary.distance_km == 3.75
    assert summary.duration_minutes == 48.0
    assert summary.mode == "walking"
    assert summary.origin == LOUVRE_COORDS
    assert summary.destination == EIFFEL_COORDS
    assert summary.data_origin == "live"
    assert summary.source.provider == "OpenRouteService"
    assert "OpenStreetMap" in summary.attribution
    assert isinstance(summary.fetched_at, datetime)
    assert summary.fetched_at.tzinfo == UTC
    assert captured_auth == ["test-secret-key"]


# ==============================================================================
# 3. Empty & Not Found Routing Outcomes
# ==============================================================================


def test_no_route_found_empty_routes_raises_route_not_found() -> None:
    """Empty routes array from ORS raises RouteNotFoundError without crashing."""

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"routes": []})

    transport = httpx.MockTransport(_handler)
    settings = Settings(
        ROUTING_PROVIDER_MODE="live",
        OPENROUTESERVICE_API_KEY="test-secret-key",
    )
    client = OpenRouteServiceClient(settings=settings, transport=transport)

    with pytest.raises(RouteNotFoundError) as exc_info:
        asyncio.run(client.get_route(LOUVRE_COORDS, EIFFEL_COORDS, mode="walking"))

    assert "zero routes" in str(exc_info.value).lower()


def test_unroutable_point_404_raises_route_not_found() -> None:
    """HTTP 404 with ORS code 2010 raises RouteNotFoundError."""

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={
                "error": {
                    "code": 2010,
                    "message": "Could not find routable point within radius.",
                }
            },
        )

    transport = httpx.MockTransport(_handler)
    settings = Settings(
        ROUTING_PROVIDER_MODE="live",
        OPENROUTESERVICE_API_KEY="test-secret-key",
    )
    client = OpenRouteServiceClient(settings=settings, transport=transport)

    with pytest.raises(RouteNotFoundError) as exc_info:
        asyncio.run(client.get_route(LOUVRE_COORDS, EIFFEL_COORDS, mode="walking"))

    assert "routable point" in str(exc_info.value).lower()


# ==============================================================================
# 4. Error Handling: Auth, Rate Limits, Timeouts & Retries
# ==============================================================================


def test_authentication_failure_never_retried() -> None:
    """HTTP 401 raises AUTHENTICATION_FAILED with single attempt."""
    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(401, text="Unauthorized: Invalid Token")

    transport = httpx.MockTransport(_handler)
    settings = Settings(
        ROUTING_PROVIDER_MODE="live",
        OPENROUTESERVICE_API_KEY="invalid-key",
        OPENROUTESERVICE_MAX_RETRIES=2,
    )
    client = OpenRouteServiceClient(settings=settings, transport=transport)

    with pytest.raises(ProviderError) as exc_info:
        asyncio.run(client.get_route(LOUVRE_COORDS, EIFFEL_COORDS))

    err = exc_info.value
    assert call_count == 1
    assert err.code == ErrorCode.AUTHENTICATION_FAILED
    assert err.retryable is False
    assert err.attempts == 1


def test_rate_limited_429_surfaces_rate_limit_error() -> None:
    """HTTP 429 raises RATE_LIMITED with Retry-After parsed."""
    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(429, headers={"Retry-After": "30.0"})

    transport = httpx.MockTransport(_handler)
    settings = Settings(
        ROUTING_PROVIDER_MODE="live",
        OPENROUTESERVICE_API_KEY="valid-key",
    )
    client = OpenRouteServiceClient(settings=settings, transport=transport)

    with pytest.raises(ProviderError) as exc_info:
        asyncio.run(client.get_route(LOUVRE_COORDS, EIFFEL_COORDS))

    err = exc_info.value
    assert err.code == ErrorCode.RATE_LIMITED
    assert err.retry_after_seconds == 30.0


def test_timeout_then_success_bounded_retry() -> None:
    """Transient timeout on attempt 1 succeeds on retry attempt 2."""
    call_count = 0
    sleep_calls: list[float] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise httpx.ReadTimeout("Read timed out")
        return httpx.Response(200, json=VALID_ORS_RESPONSE)

    async def _fake_sleep(d: float) -> None:
        sleep_calls.append(d)

    transport = httpx.MockTransport(_handler)
    settings = Settings(
        ROUTING_PROVIDER_MODE="live",
        OPENROUTESERVICE_API_KEY="valid-key",
        OPENROUTESERVICE_MAX_RETRIES=1,
    )
    client = OpenRouteServiceClient(
        settings=settings,
        transport=transport,
        retry_sleep=_fake_sleep,
        retry_random=lambda low, high: high,
    )

    summary = asyncio.run(client.get_route(LOUVRE_COORDS, EIFFEL_COORDS))
    assert call_count == 2
    assert len(sleep_calls) == 1
    assert summary.distance_km == 3.75


def test_malformed_json_response_raises_invalid_response() -> None:
    """Non-JSON response raises INVALID_RESPONSE without retrying."""
    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, text="<html>502 Bad Gateway</html>")

    transport = httpx.MockTransport(_handler)
    settings = Settings(
        ROUTING_PROVIDER_MODE="live",
        OPENROUTESERVICE_API_KEY="valid-key",
    )
    client = OpenRouteServiceClient(settings=settings, transport=transport)

    with pytest.raises(ProviderError) as exc_info:
        asyncio.run(client.get_route(LOUVRE_COORDS, EIFFEL_COORDS))

    assert call_count == 1
    assert exc_info.value.code == ErrorCode.INVALID_RESPONSE
    assert exc_info.value.retryable is False


# ==============================================================================
# 5. Missing Key & Deterministic Mock Mode
# ==============================================================================


def test_missing_api_key_in_live_mode_reports_unavailable() -> None:
    """When API key is missing in live mode, raises auth failure cleanly."""
    settings = Settings(
        ROUTING_PROVIDER_MODE="live",
        OPENROUTESERVICE_API_KEY=None,
    )
    client = OpenRouteServiceClient(settings=settings)

    with pytest.raises(ProviderError) as exc_info:
        asyncio.run(client.get_route(LOUVRE_COORDS, EIFFEL_COORDS))

    err = exc_info.value
    assert err.code == ErrorCode.AUTHENTICATION_FAILED
    assert "unavailable because no api key" in err.safe_message.lower()


def test_mock_mode_returns_deterministic_fixture_labeled_mock() -> None:
    """Mock mode returns deterministic fixture with data_origin=mock."""
    settings = Settings(ROUTING_PROVIDER_MODE="mock")
    client = OpenRouteServiceClient(settings=settings)

    summary = asyncio.run(
        client.get_route(LOUVRE_COORDS, EIFFEL_COORDS, mode="walking")
    )

    assert isinstance(summary, RouteSummary)
    assert summary.data_origin == "mock"
    assert summary.distance_km == 3.75
    assert summary.duration_minutes == 48.0
    assert "OpenStreetMap" in summary.attribution


def test_mock_mode_synthesizes_unlisted_route_deterministically() -> None:
    """Coordinates not in fixtures synthesize deterministic calculation labeled mock."""
    settings = Settings(ROUTING_PROVIDER_MODE="mock")
    client = OpenRouteServiceClient(settings=settings)

    # Some arbitrary coordinates in London
    coord_a = (51.52, -0.10)
    coord_b = (51.53, -0.09)
    summary = asyncio.run(client.get_route(coord_a, coord_b, mode="cycling"))

    assert summary.data_origin == "mock"
    assert summary.distance_km > 0.0
    assert summary.duration_minutes > 0.0
    assert summary.mode == "cycling"


# ==============================================================================
# 6. Agent Tool Function Parity & Envelope Invariants
# ==============================================================================


def test_get_route_context_success_returns_tool_result() -> None:
    """get_route_context returns ToolResult with status OK and RouteSummary data."""
    settings = Settings(ROUTING_PROVIDER_MODE="mock")
    client = OpenRouteServiceClient(settings=settings)

    result = get_route_context(
        origin_lat=LOUVRE_COORDS[0],
        origin_lon=LOUVRE_COORDS[1],
        dest_lat=EIFFEL_COORDS[0],
        dest_lon=EIFFEL_COORDS[1],
        mode="walking",
        client=client,
    )

    assert isinstance(result, ToolResult)
    assert result.status == ToolStatus.OK
    assert result.tool_name == "get_route_context"
    assert result.data_origin == "mock"
    assert isinstance(result.data, dict)
    assert result.data.get("distance_km") == 3.75
    assert result.data.get("duration_minutes") == 48.0
    assert result.error_code is None


def test_get_route_context_empty_when_no_route_found() -> None:
    """When client raises RouteNotFoundError, get_route_context returns EMPTY status."""

    class _AlwaysEmptyClient:
        async def get_route(self, *args: Any, **kwargs: Any) -> Any:
            raise RouteNotFoundError("No routable path across ocean")

    result = get_route_context(
        origin_lat=LOUVRE_COORDS[0],
        origin_lon=LOUVRE_COORDS[1],
        dest_lat=EIFFEL_COORDS[0],
        dest_lon=EIFFEL_COORDS[1],
        client=_AlwaysEmptyClient(),
    )

    assert result.status == ToolStatus.EMPTY
    assert result.data == []
    assert result.data_origin == "none"
    assert "no routable path" in result.safe_message.lower()


def test_get_route_context_missing_key_returns_provider_unavailable() -> None:
    """Missing API key in live mode returns PROVIDER_UNAVAILABLE safely."""
    settings = Settings(
        ROUTING_PROVIDER_MODE="live",
        OPENROUTESERVICE_API_KEY=None,
    )
    client = OpenRouteServiceClient(settings=settings)

    result = get_route_context(
        origin_lat=LOUVRE_COORDS[0],
        origin_lon=LOUVRE_COORDS[1],
        dest_lat=EIFFEL_COORDS[0],
        dest_lon=EIFFEL_COORDS[1],
        client=client,
    )

    assert result.status == ToolStatus.ERROR
    assert result.error_code == ToolErrorCode.PROVIDER_UNAVAILABLE
    assert result.data is None
    assert result.data_origin == "none"
    assert "unavailable because no api key" in result.safe_message.lower()


def test_get_route_context_invalid_arguments_returns_error_envelope() -> None:
    """Invalid arguments (identical endpoints) returns ToolStatus.ERROR with code."""
    result = get_route_context(
        origin_lat=48.0,
        origin_lon=2.0,
        dest_lat=48.0,
        dest_lon=2.0,
    )

    assert result.status == ToolStatus.ERROR
    assert result.error_code == ToolErrorCode.INVALID_ARGUMENTS
    assert "identical" in result.safe_message.lower()


# ==============================================================================
# 7. Tool Registry Parity (Three Tools Registered)
# ==============================================================================


def test_registry_contains_three_tools() -> None:
    """TOOL_REGISTRY contains geocode_destination, get_weather, get_route_context."""
    assert set(TOOL_REGISTRY.keys()) == {
        "geocode_destination",
        "get_weather",
        "get_route_context",
    }


def test_invoking_registered_tool_returns_same_result() -> None:
    """Invoking get_route_context via StructuredTool yields identical result."""
    settings = Settings(ROUTING_PROVIDER_MODE="mock")
    mock_client = OpenRouteServiceClient(settings=settings)

    registry = create_tool_registry(client=mock_client)
    route_tool = registry["get_route_context"]
    assert isinstance(route_tool, StructuredTool)

    # 1. Direct call
    direct_result = get_route_context(
        origin_lat=LOUVRE_COORDS[0],
        origin_lon=LOUVRE_COORDS[1],
        dest_lat=EIFFEL_COORDS[0],
        dest_lon=EIFFEL_COORDS[1],
        mode="walking",
        client=mock_client,
    )

    # 2. Registered tool invocation
    tool_input = {
        "origin_lat": LOUVRE_COORDS[0],
        "origin_lon": LOUVRE_COORDS[1],
        "dest_lat": EIFFEL_COORDS[0],
        "dest_lon": EIFFEL_COORDS[1],
        "mode": "walking",
    }
    invoked_result = route_tool.invoke(tool_input)

    assert isinstance(invoked_result, ToolResult)
    assert invoked_result.status == direct_result.status
    assert invoked_result.data_origin == direct_result.data_origin
    assert invoked_result.tool_name == "get_route_context"
    # Verify payload metrics match without millisecond timestamp diff
    assert isinstance(invoked_result.data, dict)
    assert isinstance(direct_result.data, dict)
    assert invoked_result.data["distance_km"] == direct_result.data["distance_km"]
    assert (
        invoked_result.data["duration_minutes"]
        == direct_result.data["duration_minutes"]
    )
    assert invoked_result.data["mode"] == direct_result.data["mode"]
