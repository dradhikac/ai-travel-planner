"""Integration alias for OpenRouteService routing provider adapter."""

from app.providers.openrouteservice import (
    MAX_DISTANCE_KM,
    PROFILE_MAP,
    OpenRouteServiceClient,
    RouteNotFoundError,
    RouteSummary,
    async_get_route,
    get_route,
    haversine_distance_km,
    validate_route_inputs,
)

__all__ = [
    "MAX_DISTANCE_KM",
    "PROFILE_MAP",
    "OpenRouteServiceClient",
    "RouteNotFoundError",
    "RouteSummary",
    "async_get_route",
    "get_route",
    "haversine_distance_km",
    "validate_route_inputs",
]
