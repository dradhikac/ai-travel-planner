"""Unit tests for Phase 3 agent tool functions and LangChain tool registration.

Verifies:
- Input validation occurs BEFORE any external/adapter call.
- Fake adapter is never called on invalid arguments.
- Result normalization with attribution, UTC fetched_at, and data_origin.
- Empty geocoding results map to status 'empty' (not error).
- Out-of-forecast weather maps to status 'empty' with error_code.
- Adapter exceptions map safely to ToolResult without exposing URLs or traces.
- Tool registry exposes exactly the registered tools with accurate descriptions.
- Invoking registered tools via LangChain interface returns identical contracts.
- Unknown tool names raise KeyError with clear error messages.
"""

import asyncio
from datetime import UTC, date, datetime
from typing import Any

import pytest
from langchain_core.tools import StructuredTool

from app.agent.errors import ToolErrorCode
from app.agent.tools import (
    TOOL_REGISTRY,
    GeocodeArgs,
    ToolResult,
    ToolStatus,
    WeatherArgs,
    async_geocode_destination,
    async_get_weather,
    create_tool_registry,
    geocode_destination,
    get_tool,
    get_weather,
)
from app.providers.open_meteo.errors import (
    HttpError,
    MalformedResponseError,
    NetworkUnavailableError,
    ProviderError,
    RateLimitExceededError,
    TimeoutError,
)
from app.schemas.provider import GeocodeResult, SourceInfo, WeatherDay, WeatherSummary

# ==============================================================================
# Offline Fake Adapter for Strict Isolation
# ==============================================================================


class FakeOpenMeteoAdapter:
    """Configurable fake provider adapter recording invocations without sockets."""

    def __init__(self) -> None:
        self.search_calls: list[dict[str, Any]] = []
        self.weather_calls: list[dict[str, Any]] = []
        self.last_attempts: int = 1
        self.geocode_return_value: list[GeocodeResult] | None = None
        self.geocode_exception: Exception | None = None
        self.weather_return_value: WeatherSummary | None = None
        self.weather_exception: Exception | None = None

    async def search_destination(
        self,
        name: str,
        count: int = 5,
    ) -> list[GeocodeResult]:
        self.search_calls.append({"name": name, "count": count})
        if self.geocode_exception is not None:
            raise self.geocode_exception
        if self.geocode_return_value is not None:
            return self.geocode_return_value
        return []

    async def get_daily_forecast(
        self,
        latitude: float,
        longitude: float,
        start: date,
        end: date,
    ) -> WeatherSummary:
        self.weather_calls.append(
            {
                "latitude": latitude,
                "longitude": longitude,
                "start": start,
                "end": end,
            }
        )
        if self.weather_exception is not None:
            raise self.weather_exception
        if self.weather_return_value is not None:
            return self.weather_return_value
        raise RuntimeError("No weather return value configured on fake adapter")


@pytest.fixture
def sample_source_info() -> SourceInfo:
    return SourceInfo(
        provider="Open-Meteo",
        url="https://open-meteo.com/",
        attribution="Weather data by Open-Meteo.com",
        fetched_at=datetime(2026, 10, 30, 12, 0, 0, tzinfo=UTC),
        data_origin="mock",
    )


@pytest.fixture
def sample_geocode_results(sample_source_info: SourceInfo) -> list[GeocodeResult]:
    return [
        GeocodeResult(
            name="Tokyo",
            country="Japan",
            admin_region="Tokyo",
            latitude=35.6762,
            longitude=139.6503,
            timezone="Asia/Tokyo",
            source=sample_source_info,
            fetched_at=sample_source_info.fetched_at,
        ),
        GeocodeResult(
            name="Tokyo Skytree",
            country="Japan",
            admin_region="Tokyo",
            latitude=35.7101,
            longitude=139.8107,
            timezone="Asia/Tokyo",
            source=sample_source_info,
            fetched_at=sample_source_info.fetched_at,
        ),
    ]


@pytest.fixture
def sample_weather_summary(sample_source_info: SourceInfo) -> WeatherSummary:
    return WeatherSummary(
        location="Tokyo, Japan",
        days=[
            WeatherDay(
                date=date(2026, 11, 1),
                temp_min_c=12.0,
                temp_max_c=19.5,
                precipitation_probability_pct=10,
                precipitation_sum_mm=0.0,
                weather_code=1,
                condition_description="Mainly clear",
            ),
            WeatherDay(
                date=date(2026, 11, 2),
                temp_min_c=11.5,
                temp_max_c=18.0,
                precipitation_probability_pct=40,
                precipitation_sum_mm=1.8,
                weather_code=61,
                condition_description="Slight rain",
            ),
        ],
        units={"temperature": "celsius", "precipitation": "mm"},
        source=sample_source_info,
        fetched_at=sample_source_info.fetched_at,
        data_origin="mock",
        horizon_note=None,
    )


@pytest.fixture
def out_of_horizon_weather_summary(
    sample_source_info: SourceInfo,
) -> WeatherSummary:
    return WeatherSummary(
        location="Tokyo, Japan",
        days=[],
        units={"temperature": "celsius", "precipitation": "mm"},
        source=sample_source_info,
        fetched_at=sample_source_info.fetched_at,
        data_origin="mock",
        horizon_note=(
            "Weather forecast is unavailable for dates beyond "
            "the 16-day forecast horizon."
        ),
    )


# ==============================================================================
# 1. Geocoding Tool Unit Tests
# ==============================================================================


def test_geocode_valid_args_success(
    sample_geocode_results: list[GeocodeResult],
) -> None:
    """Valid geocode query resolves to normalized success ToolResult."""
    adapter = FakeOpenMeteoAdapter()
    adapter.geocode_return_value = sample_geocode_results
    adapter.last_attempts = 1

    args = GeocodeArgs(query="Tokyo", count=2)
    result = geocode_destination(args=args, client=adapter)

    assert result.tool_name == "geocode_destination"
    assert result.status == ToolStatus.OK
    assert result.error_code is None
    assert result.safe_message is None
    assert result.data_origin == "mock"
    assert result.latency_ms >= 0.0
    assert result.attempts == 1
    assert result.source is not None
    assert result.source.provider == "Open-Meteo"
    assert result.fetched_at.tzinfo is not None

    # Verify normalized list data payload
    assert isinstance(result.data, list)
    assert len(result.data) == 2
    assert result.data[0]["name"] == "Tokyo"
    assert result.data[0]["latitude"] == 35.6762

    # Verify adapter was called with expected sanitized parameters
    assert len(adapter.search_calls) == 1
    assert adapter.search_calls[0] == {"name": "Tokyo", "count": 2}


def test_async_geocode_valid_args_success(
    sample_geocode_results: list[GeocodeResult],
) -> None:
    """Async geocode function resolves with matching result."""
    adapter = FakeOpenMeteoAdapter()
    adapter.geocode_return_value = sample_geocode_results

    result = asyncio.run(
        async_geocode_destination(args={"query": "Tokyo", "count": 2}, client=adapter)
    )
    assert result.status == ToolStatus.OK
    assert len(result.data) == 2
    assert len(adapter.search_calls) == 1


@pytest.mark.parametrize(
    "invalid_input",
    [
        None,
        {},
        {"query": ""},
        {"query": "   "},
        {"query": "Paris", "count": 0},
        {"query": "Paris", "count": 11},
        {"query": "Paris", "country_code": "USA"},  # 3 chars
        {"query": "Paris", "country_code": "12"},  # non-alpha
    ],
)
def test_geocode_invalid_args_rejects_without_adapter_call(
    invalid_input: Any,
) -> None:
    """Invalid arguments return error ToolResult and NEVER invoke adapter."""
    adapter = FakeOpenMeteoAdapter()
    result = geocode_destination(args=invalid_input, client=adapter)

    assert result.tool_name == "geocode_destination"
    assert result.status == ToolStatus.ERROR
    assert result.error_code == ToolErrorCode.INVALID_ARGUMENTS
    assert result.data is None
    assert result.data_origin == "none"
    assert result.safe_message is not None
    assert "Invalid arguments" in result.safe_message

    # Strict invariant: adapter was never called
    assert len(adapter.search_calls) == 0


def test_geocode_empty_results_returns_empty_status() -> None:
    """Geocoding returning zero results returns status 'empty' (not error)."""
    adapter = FakeOpenMeteoAdapter()
    adapter.geocode_return_value = []

    result = geocode_destination(args={"query": "NonexistentPlace9876"}, client=adapter)

    assert result.tool_name == "geocode_destination"
    assert result.status == ToolStatus.EMPTY
    assert result.error_code is None
    assert result.data == []
    assert result.data_origin == "none"
    assert "No locations found" in (result.safe_message or "")
    assert len(adapter.search_calls) == 1


@pytest.mark.parametrize(
    ("exception", "expected_status", "expected_code"),
    [
        (TimeoutError("Read timed out"), ToolStatus.TIMEOUT, ToolErrorCode.TIMEOUT),
        (
            RateLimitExceededError("Rate limit reached"),
            ToolStatus.RATE_LIMITED,
            ToolErrorCode.RATE_LIMITED,
        ),
        (
            MalformedResponseError("Missing results key"),
            ToolStatus.ERROR,
            ToolErrorCode.MALFORMED_RESPONSE,
        ),
        (
            NetworkUnavailableError("DNS error"),
            ToolStatus.ERROR,
            ToolErrorCode.PROVIDER_UNAVAILABLE,
        ),
        (
            HttpError(status_code=503, message="Unavailable"),
            ToolStatus.ERROR,
            ToolErrorCode.PROVIDER_UNAVAILABLE,
        ),
        (
            ProviderError("Generic provider issue"),
            ToolStatus.ERROR,
            ToolErrorCode.PROVIDER_UNAVAILABLE,
        ),
        (
            RuntimeError("Unexpected unhandled glitch"),
            ToolStatus.ERROR,
            ToolErrorCode.EXECUTION_FAILED,
        ),
    ],
)
def test_geocode_adapter_exceptions_map_safely(
    exception: Exception,
    expected_status: ToolStatus,
    expected_code: ToolErrorCode,
) -> None:
    """Adapter exceptions map safely to ToolResult without leaking URLs/traces."""
    adapter = FakeOpenMeteoAdapter()
    adapter.geocode_exception = exception

    result = geocode_destination(args={"query": "Paris"}, client=adapter)

    assert result.tool_name == "geocode_destination"
    assert result.status == expected_status
    assert result.error_code == expected_code
    assert result.data is None
    assert result.data_origin == "none"
    assert result.safe_message is not None
    # Ensure no internal raw URL or stack trace leaked into safe_message
    assert "http" not in result.safe_message.lower()
    assert "traceback" not in result.safe_message.lower()


# ==============================================================================
# 2. Weather Tool Unit Tests
# ==============================================================================


def test_weather_valid_args_success(sample_weather_summary: WeatherSummary) -> None:
    """Valid weather query resolves to normalized success ToolResult."""
    adapter = FakeOpenMeteoAdapter()
    adapter.weather_return_value = sample_weather_summary
    adapter.last_attempts = 1

    args = WeatherArgs(
        latitude=35.6762,
        longitude=139.6503,
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 2),
    )
    result = get_weather(args=args, client=adapter)

    assert result.tool_name == "get_weather"
    assert result.status == ToolStatus.OK
    assert result.error_code is None
    assert result.safe_message is None
    assert result.data_origin == "mock"
    assert result.latency_ms >= 0.0
    assert result.attempts == 1
    assert result.source is not None
    assert result.source.provider == "Open-Meteo"

    # Verify normalized dict data payload
    assert isinstance(result.data, dict)
    assert result.data["location"] == "Tokyo, Japan"
    assert len(result.data["days"]) == 2

    # Verify adapter called with parsed arguments
    assert len(adapter.weather_calls) == 1
    call = adapter.weather_calls[0]
    assert call["latitude"] == 35.6762
    assert call["longitude"] == 139.6503
    assert call["start"] == date(2026, 11, 1)
    assert call["end"] == date(2026, 11, 2)


def test_async_weather_valid_args_success(
    sample_weather_summary: WeatherSummary,
) -> None:
    """Async weather function resolves with matching result."""
    adapter = FakeOpenMeteoAdapter()
    adapter.weather_return_value = sample_weather_summary

    result = asyncio.run(
        async_get_weather(
            args={
                "latitude": 35.6762,
                "longitude": 139.6503,
                "start_date": "2026-11-01",
                "end_date": "2026-11-02",
            },
            client=adapter,
        )
    )
    assert result.status == ToolStatus.OK
    assert isinstance(result.data, dict)
    assert len(adapter.weather_calls) == 1


@pytest.mark.parametrize(
    "invalid_input",
    [
        None,
        {},
        {
            "latitude": 95.0,
            "longitude": 0.0,
            "start_date": "2026-11-01",
            "end_date": "2026-11-02",
        },
        {
            "latitude": -95.0,
            "longitude": 0.0,
            "start_date": "2026-11-01",
            "end_date": "2026-11-02",
        },
        {
            "latitude": 0.0,
            "longitude": 190.0,
            "start_date": "2026-11-01",
            "end_date": "2026-11-02",
        },
        {
            "latitude": 0.0,
            "longitude": -190.0,
            "start_date": "2026-11-01",
            "end_date": "2026-11-02",
        },
        # Inverted dates
        {
            "latitude": 0.0,
            "longitude": 0.0,
            "start_date": "2026-11-05",
            "end_date": "2026-11-01",
        },
        # Range exceeding 30 days
        {
            "latitude": 0.0,
            "longitude": 0.0,
            "start_date": "2026-11-01",
            "end_date": "2026-12-05",
        },
    ],
)
def test_weather_invalid_args_rejects_without_adapter_call(
    invalid_input: Any,
) -> None:
    """Invalid arguments return error ToolResult and NEVER invoke adapter."""
    adapter = FakeOpenMeteoAdapter()
    result = get_weather(args=invalid_input, client=adapter)

    assert result.tool_name == "get_weather"
    assert result.status == ToolStatus.ERROR
    assert result.error_code == ToolErrorCode.INVALID_ARGUMENTS
    assert result.data is None
    assert result.data_origin == "none"
    assert result.safe_message is not None
    assert "Invalid arguments" in result.safe_message

    # Strict invariant: adapter was never called
    assert len(adapter.weather_calls) == 0


def test_weather_out_of_forecast_range_returns_empty_status(
    out_of_horizon_weather_summary: WeatherSummary,
) -> None:
    """Trip dates outside horizon return status empty with OUT_OF_FORECAST_RANGE."""
    adapter = FakeOpenMeteoAdapter()
    adapter.weather_return_value = out_of_horizon_weather_summary

    result = get_weather(
        args={
            "latitude": 35.6762,
            "longitude": 139.6503,
            "start_date": "2026-11-20",
            "end_date": "2026-11-25",
        },
        client=adapter,
    )

    assert result.tool_name == "get_weather"
    assert result.status == ToolStatus.EMPTY
    assert result.error_code == ToolErrorCode.OUT_OF_FORECAST_RANGE
    assert result.safe_message is not None
    assert "16-day" in result.safe_message
    assert result.data_origin == "mock"
    assert isinstance(result.data, dict)
    assert len(adapter.weather_calls) == 1


@pytest.mark.parametrize(
    ("exception", "expected_status", "expected_code"),
    [
        (TimeoutError("Read timed out"), ToolStatus.TIMEOUT, ToolErrorCode.TIMEOUT),
        (
            RateLimitExceededError("Rate limit reached"),
            ToolStatus.RATE_LIMITED,
            ToolErrorCode.RATE_LIMITED,
        ),
        (
            MalformedResponseError("Missing daily key"),
            ToolStatus.ERROR,
            ToolErrorCode.MALFORMED_RESPONSE,
        ),
        (
            NetworkUnavailableError("DNS error"),
            ToolStatus.ERROR,
            ToolErrorCode.PROVIDER_UNAVAILABLE,
        ),
        (
            HttpError(status_code=502, message="Bad gateway"),
            ToolStatus.ERROR,
            ToolErrorCode.PROVIDER_UNAVAILABLE,
        ),
        (
            ProviderError("Generic provider issue"),
            ToolStatus.ERROR,
            ToolErrorCode.PROVIDER_UNAVAILABLE,
        ),
        (
            RuntimeError("Unexpected unhandled glitch"),
            ToolStatus.ERROR,
            ToolErrorCode.EXECUTION_FAILED,
        ),
    ],
)
def test_weather_adapter_exceptions_map_safely(
    exception: Exception,
    expected_status: ToolStatus,
    expected_code: ToolErrorCode,
) -> None:
    """Adapter exceptions map safely to ToolResult without leaking internal details."""
    adapter = FakeOpenMeteoAdapter()
    adapter.weather_exception = exception

    result = get_weather(
        args={
            "latitude": 35.6762,
            "longitude": 139.6503,
            "start_date": "2026-11-01",
            "end_date": "2026-11-02",
        },
        client=adapter,
    )

    assert result.tool_name == "get_weather"
    assert result.status == expected_status
    assert result.error_code == expected_code
    assert result.data is None
    assert result.data_origin == "none"
    assert result.safe_message is not None
    assert "http" not in result.safe_message.lower()
    assert "traceback" not in result.safe_message.lower()


# ==============================================================================
# 3. Tool Registry & LangChain Integration Tests
# ==============================================================================


def test_tool_registry_contains_exactly_registered_tools() -> None:
    """TOOL_REGISTRY contains exactly 'geocode_destination' and 'get_weather'."""
    assert set(TOOL_REGISTRY.keys()) == {"geocode_destination", "get_weather"}

    for name, tool in TOOL_REGISTRY.items():
        assert isinstance(tool, StructuredTool)
        assert tool.name == name
        assert tool.args_schema is not None
        assert tool.description is not None
        assert len(tool.description) > 10

    # Explicitly confirm absence of future/unimplemented tools
    assert "get_route_context" not in TOOL_REGISTRY
    assert "search_places" not in TOOL_REGISTRY


def test_tool_registry_descriptions_contain_expected_boundaries() -> None:
    """Tool descriptions accurately communicate scope and boundaries."""
    geocode_tool = TOOL_REGISTRY["geocode_destination"]
    assert "coordinates" in geocode_tool.description.lower()
    assert "does not search attractions" in geocode_tool.description.lower()

    weather_tool = TOOL_REGISTRY["get_weather"]
    assert "forecast" in weather_tool.description.lower()
    assert "16 days" in weather_tool.description.lower()


def test_get_tool_success_and_aliases() -> None:
    """get_tool retrieves tools by canonical name and documented aliases."""
    canonical_geocode = get_tool("geocode_destination")
    assert canonical_geocode.name == "geocode_destination"
    assert get_tool("geocode") is canonical_geocode
    assert get_tool("geocode_tool") is canonical_geocode

    canonical_weather = get_tool("get_weather")
    assert canonical_weather.name == "get_weather"
    assert get_tool("weather") is canonical_weather
    assert get_tool("weather_tool") is canonical_weather


def test_get_tool_unknown_raises_clear_key_error() -> None:
    """Requesting an unregistered tool raises KeyError with available tools."""
    with pytest.raises(KeyError) as exc_info:
        get_tool("get_route_context")

    msg = str(exc_info.value)
    assert "Unknown tool 'get_route_context'" in msg
    assert "geocode_destination" in msg
    assert "get_weather" in msg


def test_langchain_interface_parity_with_direct_call(
    sample_geocode_results: list[GeocodeResult],
    sample_weather_summary: WeatherSummary,
) -> None:
    """Invoking tools via LangChain .invoke() returns identical ToolResult."""
    adapter = FakeOpenMeteoAdapter()
    adapter.geocode_return_value = sample_geocode_results
    adapter.weather_return_value = sample_weather_summary

    registry = create_tool_registry(client=adapter)
    geocode_tool = registry["geocode_destination"]
    weather_tool = registry["get_weather"]

    # 1. Geocode invocation via LangChain .invoke()
    langchain_geo_res = geocode_tool.invoke({"query": "Tokyo", "count": 2})
    assert isinstance(langchain_geo_res, ToolResult)
    assert langchain_geo_res.status == ToolStatus.OK
    assert langchain_geo_res.tool_name == "geocode_destination"
    assert len(langchain_geo_res.data) == 2

    # 2. Weather invocation via LangChain .invoke()
    langchain_weather_res = weather_tool.invoke(
        {
            "latitude": 35.6762,
            "longitude": 139.6503,
            "start_date": "2026-11-01",
            "end_date": "2026-11-02",
        }
    )
    assert isinstance(langchain_weather_res, ToolResult)
    assert langchain_weather_res.status == ToolStatus.OK
    assert langchain_weather_res.tool_name == "get_weather"
    assert isinstance(langchain_weather_res.data, dict)


def test_langchain_interface_async_ainvoke_parity(
    sample_geocode_results: list[GeocodeResult],
    sample_weather_summary: WeatherSummary,
) -> None:
    """Invoking tools via LangChain .ainvoke() returns valid ToolResult."""
    adapter = FakeOpenMeteoAdapter()
    adapter.geocode_return_value = sample_geocode_results
    adapter.weather_return_value = sample_weather_summary

    registry = create_tool_registry(client=adapter)
    geocode_tool = registry["geocode_destination"]
    weather_tool = registry["get_weather"]

    async def _run() -> tuple[ToolResult, ToolResult]:
        geo = await geocode_tool.ainvoke({"query": "Tokyo", "count": 2})
        w = await weather_tool.ainvoke(
            {
                "latitude": 35.6762,
                "longitude": 139.6503,
                "start_date": "2026-11-01",
                "end_date": "2026-11-02",
            }
        )
        return geo, w

    geo_res, weather_res = asyncio.run(_run())
    assert isinstance(geo_res, ToolResult)
    assert geo_res.status == ToolStatus.OK
    assert isinstance(weather_res, ToolResult)
    assert weather_res.status == ToolStatus.OK
