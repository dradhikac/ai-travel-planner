"""Agent tools package exposing typed contracts, tool functions, and registry."""

from app.agent.tools.contracts import (
    GeocodeArgs,
    RouteArgs,
    ToolCall,
    ToolResult,
    ToolStatus,
    WeatherArgs,
)
from app.agent.tools.geocode import async_geocode_destination, geocode_destination
from app.agent.tools.registry import TOOL_REGISTRY, create_tool_registry, get_tool
from app.agent.tools.route import async_get_route_context, get_route_context
from app.agent.tools.weather import async_get_weather, get_weather

__all__ = [
    "GeocodeArgs",
    "RouteArgs",
    "TOOL_REGISTRY",
    "ToolCall",
    "ToolResult",
    "ToolStatus",
    "WeatherArgs",
    "async_geocode_destination",
    "async_get_route_context",
    "async_get_weather",
    "create_tool_registry",
    "geocode_destination",
    "get_route_context",
    "get_tool",
    "get_weather",
]
