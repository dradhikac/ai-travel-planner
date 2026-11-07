"""Async HTTP client adapter for Open-Meteo geocoding and weather forecast APIs."""

import json
import logging
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.providers.open_meteo.errors import (
    HttpError,
    MalformedResponseError,
    NetworkUnavailableError,
    RateLimitExceededError,
    TimeoutError,
)
from app.providers.open_meteo.normalizers import (
    normalize_forecast_response,
    normalize_geocoding_response,
)
from app.schemas.provider import GeocodeResult, WeatherSummary

logger = logging.getLogger(__name__)

# Base path for local mock fixtures
FIXTURES_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "tests"
    / "fixtures"
    / "open_meteo"
)


class OpenMeteoClient:
    """Async client adapter for Open-Meteo communication and normalization."""

    def __init__(
        self,
        settings: Settings | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.transport = transport

    def _get_http_client(self) -> httpx.AsyncClient:
        """Create configured httpx.AsyncClient instance."""
        connect_timeout = self.settings.OPEN_METEO_CONNECT_TIMEOUT_SECONDS
        read_timeout = self.settings.OPEN_METEO_READ_TIMEOUT_SECONDS
        total_timeout = connect_timeout + read_timeout

        timeout = httpx.Timeout(
            timeout=total_timeout,
            connect=connect_timeout,
            read=read_timeout,
        )
        return httpx.AsyncClient(
            transport=self.transport,
            timeout=timeout,
        )

    async def _send_request_with_retries(
        self,
        url: str,
        params: dict[str, Any],
    ) -> tuple[dict[str, Any], datetime]:
        """Execute HTTP GET request with bounded retries on transient errors."""
        max_retries = self.settings.OPEN_METEO_MAX_RETRIES
        attempts = 1 + max(0, max_retries)

        async with self._get_http_client() as client:
            last_exception: Exception | None = None

            for attempt in range(1, attempts + 1):
                request_time = datetime.now(UTC)
                try:
                    response = await client.get(url, params=params)

                    # 1. Handle Rate Limiting (429) -> NEVER retry, surface Retry-After
                    if response.status_code == 429:
                        retry_after_header = response.headers.get("Retry-After")
                        retry_after_val: float | None = None
                        if retry_after_header:
                            try:
                                retry_after_val = float(retry_after_header)
                            except ValueError:
                                retry_after_val = None
                        raise RateLimitExceededError(
                            retry_after=retry_after_val,
                            message=(
                                "Open-Meteo rate limit exceeded. Please retry later."
                            ),
                        )

                    # 2. Handle HTTP 5xx Server Errors -> Retryable if attempts remain
                    if response.status_code >= 500:
                        if attempt < attempts:
                            logger.warning(
                                "Open-Meteo 5xx error (%d) attempt %d/%d; retrying...",
                                response.status_code,
                                attempt,
                                attempts,
                            )
                            continue
                        raise HttpError(
                            status_code=response.status_code,
                            message=(
                                f"Open-Meteo server error: HTTP {response.status_code}"
                            ),
                        )

                    # 3. Handle HTTP 4xx Client Errors -> NEVER retry
                    if response.status_code >= 400:
                        reason: str | None = None
                        try:
                            error_payload = response.json()
                            if isinstance(error_payload, dict):
                                reason = error_payload.get("reason")
                        except Exception:
                            reason = None

                        raise HttpError(
                            status_code=response.status_code,
                            message=(
                                f"Open-Meteo request error: HTTP {response.status_code}"
                            ),
                            reason=reason,
                        )

                    # 4. Successful 2xx response -> Parse JSON
                    try:
                        data = response.json()
                    except Exception as err:
                        raise MalformedResponseError(
                            "Open-Meteo response could not be parsed as JSON"
                        ) from err

                    if not isinstance(data, dict):
                        raise MalformedResponseError(
                            "Open-Meteo JSON response must be an object"
                        )

                    return data, request_time

                except (RateLimitExceededError, HttpError, MalformedResponseError):
                    # Do not swallow or retry non-retryable errors
                    raise

                except httpx.TimeoutException as err:
                    last_exception = err
                    if attempt < attempts:
                        logger.warning(
                            "Open-Meteo timeout on attempt %d/%d; retrying...",
                            attempt,
                            attempts,
                        )
                        continue
                    raise TimeoutError(
                        "Open-Meteo request timed out while communicating with provider"
                    ) from err

                except httpx.NetworkError as err:
                    last_exception = err
                    if attempt < attempts:
                        logger.warning(
                            "Open-Meteo network error on attempt %d/%d; retrying...",
                            attempt,
                            attempts,
                        )
                        continue
                    raise NetworkUnavailableError(
                        "Open-Meteo network service is unavailable"
                    ) from err

            if isinstance(last_exception, httpx.TimeoutException):
                raise TimeoutError("Open-Meteo request timed out") from last_exception
            raise NetworkUnavailableError(
                "Open-Meteo network service is unavailable"
            ) from last_exception

    def _load_mock_fixture(self, filename: str) -> dict[str, Any]:
        """Load deterministic fixture from local disk in mock mode."""
        fixture_path = FIXTURES_DIR / filename
        if not fixture_path.exists():
            raise MalformedResponseError(f"Mock fixture not found: {filename}")
        with open(fixture_path, encoding="utf-8") as f:
            return json.load(f)

    async def search_destination(
        self,
        name: str,
        count: int = 5,
    ) -> list[GeocodeResult]:
        """Search for a destination by name and return normalized geocoding results."""
        # 1. Validate inputs before any request
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Location name cannot be empty")
        if not (1 <= count <= 100):
            raise ValueError("Count must be between 1 and 100")

        trimmed_name = name.strip()

        # 2. Mock mode handling
        if self.settings.PROVIDER_MODE == "mock":
            normalized_query = trimmed_name.lower()
            if "tokyo" in normalized_query:
                raw_data = self._load_mock_fixture("geocode_tokyo.json")
            elif "empty" in normalized_query or "nonexistent" in normalized_query:
                raw_data = self._load_mock_fixture("geocode_empty.json")
            else:
                raw_data = self._load_mock_fixture("geocode_paris.json")
            return normalize_geocoding_response(
                raw_data,
                data_origin="mock",
                fetched_at=datetime.now(UTC),
            )

        # 3. Live HTTP call
        params = {
            "name": trimmed_name,
            "count": count,
            "language": "en",
            "format": "json",
        }
        raw_data, fetch_time = await self._send_request_with_retries(
            self.settings.OPEN_METEO_GEOCODING_URL,
            params=params,
        )
        return normalize_geocoding_response(
            raw_data,
            data_origin="live",
            fetched_at=fetch_time,
        )

    async def get_daily_forecast(
        self,
        latitude: float,
        longitude: float,
        start: date,
        end: date,
        location_name: str = "Destination",
    ) -> WeatherSummary:
        """Fetch daily weather forecast for geographical coordinates and date range."""
        # 1. Validate inputs before any request
        if not (-90.0 <= latitude <= 90.0):
            raise ValueError("Latitude must be between -90 and 90")
        if not (-180.0 <= longitude <= 180.0):
            raise ValueError("Longitude must be between -180 and 180")
        if end < start:
            raise ValueError("End date must be on or after start date")

        # 2. Mock mode handling
        if self.settings.PROVIDER_MODE == "mock":
            # Check if trip is completely beyond horizon (> 16 days from today)
            today = date.today()
            if (start - today).days > 16:
                raw_data = self._load_mock_fixture("forecast_beyond_horizon.json")
            else:
                raw_data = self._load_mock_fixture("forecast_paris_7day.json")
                daily = raw_data.get("daily", {})
                fixture_times = daily.get("time", [])
                if fixture_times and start.isoformat() not in fixture_times:
                    shifted_times = []
                    curr = start
                    for _ in range(len(fixture_times)):
                        shifted_times.append(curr.isoformat())
                        curr = date.fromordinal(curr.toordinal() + 1)
                    raw_data["daily"]["time"] = shifted_times

            return normalize_forecast_response(
                raw_data,
                location_name=location_name,
                start=start,
                end=end,
                data_origin="mock",
                fetched_at=datetime.now(UTC),
            )

        # 3. Live HTTP call
        daily_vars = (
            "temperature_2m_max,"
            "temperature_2m_min,"
            "precipitation_probability_max,"
            "precipitation_sum,"
            "weather_code"
        )
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "daily": daily_vars,
            "timezone": "auto",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        }
        raw_data, fetch_time = await self._send_request_with_retries(
            self.settings.OPEN_METEO_FORECAST_URL,
            params=params,
        )
        return normalize_forecast_response(
            raw_data,
            location_name=location_name,
            start=start,
            end=end,
            data_origin="live",
            fetched_at=fetch_time,
        )


# Global default client functions for direct public imports
async def search_destination(
    name: str,
    count: int = 5,
    client: OpenMeteoClient | None = None,
) -> list[GeocodeResult]:
    """Search destination coordinates using Open-Meteo geocoding."""
    adapter = client or OpenMeteoClient()
    return await adapter.search_destination(name=name, count=count)


async def get_daily_forecast(
    latitude: float,
    longitude: float,
    start: date,
    end: date,
    location_name: str = "Destination",
    client: OpenMeteoClient | None = None,
) -> WeatherSummary:
    """Get daily weather forecast from Open-Meteo."""
    adapter = client or OpenMeteoClient()
    return await adapter.get_daily_forecast(
        latitude=latitude,
        longitude=longitude,
        start=start,
        end=end,
        location_name=location_name,
    )
