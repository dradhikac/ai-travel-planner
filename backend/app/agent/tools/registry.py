"""LangChain structured tool registration and registry for Phase 3 agent tools.

NOTE ON DELIBERATELY UNREGISTERED TOOLS:
'get_route_context' and 'search_places' are deliberately NOT registered in Phase 3.
No routing or places provider adapters exist in the modular monolith codebase.
In accordance with project truthfulness rules, tools are registered only when backed
by an implemented, verified provider adapter (Open-Meteo geocoding and weather).
"""

from typing import Any

from langchain_core.tools import StructuredTool

from app.agent.tools.contracts import GeocodeArgs, WeatherArgs
from app.agent.tools.geocode import async_geocode_destination, geocode_destination
from app.agent.tools.weather import async_get_weather, get_weather


def create_tool_registry(client: Any | None = None) -> dict[str, StructuredTool]:
    """Construct a dictionary of registered LangChain StructuredTool instances.

    Args:
        client: Optional provider adapter instance for testing/dependency injection.

    Returns:
        Mapping of tool names to StructuredTool instances.
    """

    def _sync_geocode(**kwargs: Any) -> Any:
        return geocode_destination(client=client, **kwargs)

    async def _async_geocode(**kwargs: Any) -> Any:
        return await async_geocode_destination(client=client, **kwargs)

    def _sync_weather(**kwargs: Any) -> Any:
        return get_weather(client=client, **kwargs)

    async def _async_weather(**kwargs: Any) -> Any:
        return await async_get_weather(client=client, **kwargs)

    geocode_tool = StructuredTool.from_function(
        func=_sync_geocode,
        coroutine=_async_geocode,
        name="geocode_destination",
        description=(
            "Resolves a place name or city to geographical coordinates "
            "(latitude and longitude) and country metadata. Does not search "
            "attractions, restaurants, or hotels."
        ),
        args_schema=GeocodeArgs,
    )

    weather_tool = StructuredTool.from_function(
        func=_sync_weather,
        coroutine=_async_weather,
        name="get_weather",
        description=(
            "Fetches daily weather forecast metrics (temperatures, precipitation "
            "probability, and condition descriptions) for coordinates and date "
            "range. Dates beyond 16 days return an empty result with "
            "out_of_forecast_range code."
        ),
        args_schema=WeatherArgs,
    )

    return {
        "geocode_destination": geocode_tool,
        "get_weather": weather_tool,
    }


# Default module-level registry
TOOL_REGISTRY: dict[str, StructuredTool] = create_tool_registry()

# Common aliases recognized for convenience
TOOL_ALIASES: dict[str, str] = {
    "geocode": "geocode_destination",
    "geocode_tool": "geocode_destination",
    "weather": "get_weather",
    "weather_tool": "get_weather",
}


def get_tool(name: str) -> StructuredTool:
    """Retrieve a registered LangChain StructuredTool by exact name or alias.

    Args:
        name: Name or alias of the tool (e.g. 'geocode_destination', 'get_weather').

    Returns:
        StructuredTool instance from TOOL_REGISTRY.

    Raises:
        KeyError: If the tool name is unknown or unregistered.
    """
    if name in TOOL_REGISTRY:
        return TOOL_REGISTRY[name]
    if name in TOOL_ALIASES:
        return TOOL_REGISTRY[TOOL_ALIASES[name]]
    tools_list = sorted(TOOL_REGISTRY.keys())
    raise KeyError(f"Unknown tool '{name}'. Available registered tools: {tools_list}")
