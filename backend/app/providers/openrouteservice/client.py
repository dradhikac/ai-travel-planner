"""OpenRouteService Directions API v2 provider client adapter."""

import asyncio
import concurrent.futures
import json
import logging
import math
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import httpx

from app.core.config import Settings, get_settings
from app.core.retry import RetryPolicy, call_with_retry
from app.providers.errors import ErrorCode, ProviderError, parse_retry_after
from app.schemas.provider import RouteSummary, SourceInfo

logger = logging.getLogger(__name__)

# Profiles supported by OpenRouteService Directions API v2
PROFILE_MAP: Final[dict[str, str]] = {
    "walking": "foot-walking",
    "foot-walking": "foot-walking",
    "cycling": "cycling-regular",
    "cycling-regular": "cycling-regular",
    "driving": "driving-car",
    "driving-car": "driving-car",
}

# Maximum sanity thresholds for distance in kilometers
MAX_DISTANCE_KM: Final[dict[str, float]] = {
    "walking": 500.0,
    "foot-walking": 500.0,
    "cycling": 1000.0,
    "cycling-regular": 1000.0,
    "driving": 10000.0,
    "driving-car": 10000.0,
}

# Location of local offline route fixtures
FIXTURES_PATH: Final[Path] = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "tests"
    / "fixtures"
    / "openrouteservice"
    / "route_fixtures.json"
)


class RouteNotFoundError(ProviderError):
    """Raised when no transit route exists between coordinates."""

    def __init__(
        self,
        message: str = "No routable transit path found between coordinates.",
        provider: str = "OpenRouteService",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code=ErrorCode.UNKNOWN_FAILURE,
            provider=provider,
            retryable=False,
            safe_message=message,
            details=details,
        )


def haversine_distance_km(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    """Compute great-circle distance between two coordinates in kilometers."""
    earth_radius_km = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return earth_radius_km * c


def validate_route_inputs(
    origin: tuple[float, float] | list[float],
    destination: tuple[float, float] | list[float],
    mode: str,
) -> tuple[tuple[float, float], tuple[float, float], str]:
    """Validate routing coordinates, modality, and distance sanity BEFORE requests.

    Args:
        origin: (latitude, longitude) tuple or list.
        destination: (latitude, longitude) tuple or list.
        mode: Modality string ('walking', 'cycling', 'driving').

    Returns:
        Validated ((origin_lat, origin_lon), (dest_lat, dest_lon), canonical_mode).

    Raises:
        ValueError: On invalid bounds, identical endpoints, or distance violations.
    """
    if not isinstance(origin, (tuple, list)) or len(origin) != 2:
        raise ValueError("Origin must be a (latitude, longitude) coordinate pair")
    if not isinstance(destination, (tuple, list)) or len(destination) != 2:
        raise ValueError("Destination must be a (latitude, longitude) coordinate pair")

    try:
        orig_lat, orig_lon = float(origin[0]), float(origin[1])
        dest_lat, dest_lon = float(destination[0]), float(destination[1])
    except (ValueError, TypeError) as err:
        raise ValueError(
            f"Coordinates must be numeric floating-point values: {err}"
        ) from err

    # Validate coordinate ranges & identify coordinate-order mistakes
    if not (-90.0 <= orig_lat <= 90.0):
        raise ValueError(
            f"Origin latitude {orig_lat} out of range [-90.0, 90.0]. "
            "Verify coordinate order is (latitude, longitude)."
        )
    if not (-180.0 <= orig_lon <= 180.0):
        raise ValueError(
            f"Origin longitude {orig_lon} out of range [-180.0, 180.0]. "
            "Verify coordinate order is (latitude, longitude)."
        )
    if not (-90.0 <= dest_lat <= 90.0):
        raise ValueError(
            f"Destination latitude {dest_lat} out of range [-90.0, 90.0]. "
            "Verify coordinate order is (latitude, longitude)."
        )
    if not (-180.0 <= dest_lon <= 180.0):
        raise ValueError(
            f"Destination longitude {dest_lon} out of range [-180.0, 180.0]. "
            "Verify coordinate order is (latitude, longitude)."
        )

    # Origin != destination check
    if abs(orig_lat - dest_lat) < 1e-6 and abs(orig_lon - dest_lon) < 1e-6:
        raise ValueError("Origin and destination coordinates cannot be identical")

    # Mode allow-list check
    canonical_mode = mode.strip().lower()
    if canonical_mode not in PROFILE_MAP:
        raise ValueError(
            f"Invalid transit mode '{mode}'. Allowed modes: walking, cycling, driving."
        )

    # Maximum distance sanity check
    approx_dist = haversine_distance_km(orig_lat, orig_lon, dest_lat, dest_lon)
    max_dist = MAX_DISTANCE_KM.get(canonical_mode, 10000.0)
    if approx_dist > max_dist:
        raise ValueError(
            f"Route distance (~{approx_dist:.1f} km) exceeds maximum sanity "
            f"threshold ({max_dist:.0f} km) for mode '{canonical_mode}'."
        )

    return (orig_lat, orig_lon), (dest_lat, dest_lon), canonical_mode


class OpenRouteServiceClient:
    """Async client adapter for OpenRouteService Directions API v2."""

    def __init__(
        self,
        settings: Settings | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        *,
        retry_policy: RetryPolicy | None = None,
        retry_sleep: Callable[[float], Awaitable[None]] | None = None,
        retry_clock: Callable[[], float] | None = None,
        retry_random: Callable[[float, float], float] | None = None,
        retry_on_event: Callable[[int, str, float], None] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.transport = transport
        self.retry_policy = retry_policy
        self._retry_sleep = retry_sleep
        self._retry_clock = retry_clock
        self._retry_random = retry_random
        self._retry_on_event = retry_on_event

    def _get_http_client(self) -> httpx.AsyncClient:
        """Create configured httpx.AsyncClient instance."""
        timeout_val = self.settings.OPENROUTESERVICE_TIMEOUT_SECONDS
        return httpx.AsyncClient(
            transport=self.transport,
            timeout=httpx.Timeout(timeout_val),
        )

    def _load_fixtures(self) -> list[dict[str, Any]]:
        """Load deterministic offline route fixtures."""
        if not FIXTURES_PATH.exists():
            return []
        try:
            with open(FIXTURES_PATH, encoding="utf-8") as f:
                data = json.load(f)
                return data.get("fixtures", [])
        except Exception as err:
            logger.warning("Failed to load route fixtures: %s", err)
            return []

    def _find_fixture_route(
        self,
        orig: tuple[float, float],
        dest: tuple[float, float],
        mode: str,
    ) -> RouteSummary | None:
        """Find matching deterministic fixture or synthesize offline route."""
        fixtures = self._load_fixtures()
        now = datetime.now(UTC)
        canonical_mode = "walking" if "walk" in mode else mode

        for fix in fixtures:
            fix_orig = fix.get("origin")
            fix_dest = fix.get("destination")
            if (
                fix_orig
                and fix_dest
                and abs(fix_orig[0] - orig[0]) < 0.02
                and abs(fix_orig[1] - orig[1]) < 0.02
                and abs(fix_dest[0] - dest[0]) < 0.02
                and abs(fix_dest[1] - dest[1]) < 0.02
            ):
                source = SourceInfo(
                    provider="OpenRouteService",
                    url="https://openrouteservice.org/",
                    attribution=fix.get(
                        "attribution",
                        "openrouteservice.org | OpenStreetMap contributors",
                    ),
                    fetched_at=now,
                    data_origin="mock",
                )
                return RouteSummary(
                    distance_km=float(fix.get("distance_km", 0.0)),
                    duration_minutes=float(fix.get("duration_minutes", 0.0)),
                    mode=canonical_mode,
                    origin=orig,
                    destination=dest,
                    source=source,
                    attribution=source.attribution,
                    fetched_at=now,
                    data_origin="mock",
                )

        # Synthesize deterministic mock estimate if not in fixtures
        dist_km = round(
            haversine_distance_km(orig[0], orig[1], dest[0], dest[1]) * 1.25, 2
        )
        speed_kmh = 4.5 if "walk" in mode else (15.0 if "cycl" in mode else 50.0)
        duration_mins = round((dist_km / speed_kmh) * 60.0, 1)

        source = SourceInfo(
            provider="OpenRouteService",
            url="https://openrouteservice.org/",
            attribution="openrouteservice.org | OpenStreetMap contributors",
            fetched_at=now,
            data_origin="mock",
        )
        return RouteSummary(
            distance_km=dist_km,
            duration_minutes=duration_mins,
            mode=canonical_mode,
            origin=orig,
            destination=dest,
            source=source,
            attribution=source.attribution,
            fetched_at=now,
            data_origin="mock",
        )

    async def get_route(
        self,
        origin: tuple[float, float] | list[float],
        destination: tuple[float, float] | list[float],
        mode: str = "walking",
    ) -> RouteSummary:
        """Retrieve routing distance and duration via OpenRouteService Directions API.

        Args:
            origin: Origin coordinate pair (latitude, longitude).
            destination: Destination coordinate pair (latitude, longitude).
            mode: Transit mode ('walking', 'cycling', 'driving').

        Returns:
            RouteSummary containing distance, duration, and provenance metadata.

        Raises:
            ValueError: On invalid coordinates or disallowed mode.
            RouteNotFoundError: When no route exists between endpoints.
            ProviderError: On upstream auth, rate-limit, network, or server failures.
        """
        # 1. Validate inputs before any network or fixture interaction
        orig, dest, canonical_mode = validate_route_inputs(origin, destination, mode)
        profile = PROFILE_MAP[canonical_mode]

        # 2. Mock mode handling
        is_mock_mode = (
            self.settings.ROUTING_PROVIDER_MODE == "mock"
            or self.settings.PROVIDER_MODE == "mock"
        )
        if is_mock_mode:
            route = self._find_fixture_route(orig, dest, canonical_mode)
            if route is not None:
                return route

        # 3. Missing key validation (only in live mode)
        api_key = self.settings.OPENROUTESERVICE_API_KEY
        if not api_key:
            raise ProviderError(
                message="OpenRouteService API key is missing or unconfigured.",
                code=ErrorCode.AUTHENTICATION_FAILED,
                provider="OpenRouteService",
                retryable=False,
                safe_message=(
                    "Routing service is unavailable because no API key is configured."
                ),
                details={"reason": "missing_api_key"},
            )

        # 4. Live request execution with bounded retries
        base_url = self.settings.OPENROUTESERVICE_BASE_URL.rstrip("/")
        url = f"{base_url}/{profile}"

        policy = self.retry_policy or RetryPolicy(
            max_retries=self.settings.OPENROUTESERVICE_MAX_RETRIES,
            base_delay_seconds=self.settings.PROVIDER_BACKOFF_BASE_SECONDS,
            backoff_factor=2.0,
            max_delay_seconds=self.settings.PROVIDER_BACKOFF_MAX_SECONDS,
            total_budget_seconds=self.settings.PROVIDER_RETRY_BUDGET_SECONDS,
            jitter=True,
        )

        async with self._get_http_client() as client:

            async def _execute_single_request() -> RouteSummary:
                request_time = datetime.now(UTC)
                # Note: OpenRouteService Directions v2 JSON body expects [lon, lat]
                request_payload = {
                    "coordinates": [
                        [orig[1], orig[0]],
                        [dest[1], dest[0]],
                    ]
                }
                # API Key is passed STRICTLY in Authorization header, NEVER in URL
                headers = {
                    "Authorization": api_key,
                    "Content-Type": "application/json",
                }

                try:
                    response = await client.post(
                        url, json=request_payload, headers=headers
                    )
                except httpx.TimeoutException as err:
                    raise ProviderError(
                        message=f"OpenRouteService request timed out: {err}",
                        code=ErrorCode.TIMEOUT,
                        provider="OpenRouteService",
                        retryable=True,
                        safe_message=(
                            "Routing service timed out while calculating directions."
                        ),
                        details={"exception_type": type(err).__name__},
                    ) from err
                except httpx.NetworkError as err:
                    raise ProviderError(
                        message=f"OpenRouteService network connection failed: {err}",
                        code=ErrorCode.TIMEOUT,
                        provider="OpenRouteService",
                        retryable=True,
                        safe_message=(
                            "Routing service is temporarily unreachable via network."
                        ),
                        details={"exception_type": type(err).__name__},
                    ) from err

                status = response.status_code

                # 4.1 Handle Rate Limiting (429)
                if status == 429:
                    header_retry_after = response.headers.get("Retry-After")
                    retry_after_val = parse_retry_after(header_retry_after)
                    is_retryable = (
                        retry_after_val is not None and retry_after_val <= 4.0
                    )
                    raise ProviderError(
                        message="OpenRouteService rate limit exceeded.",
                        code=ErrorCode.RATE_LIMITED,
                        provider="OpenRouteService",
                        http_status=429,
                        retry_after_seconds=retry_after_val,
                        retryable=is_retryable,
                        safe_message=(
                            "Routing service rate limit exceeded. Please try again."
                        ),
                        details={"status_code": 429, "retry_after": retry_after_val},
                    )

                # 4.2 Handle Authentication / Authorization (401 / 403)
                if status in (401, 403):
                    raise ProviderError(
                        message=f"OpenRouteService unauthorized (HTTP {status}).",
                        code=ErrorCode.AUTHENTICATION_FAILED,
                        provider="OpenRouteService",
                        http_status=status,
                        retryable=False,
                        safe_message=(
                            "Routing service credentials are invalid or unauthorized."
                        ),
                        details={"status_code": status},
                    )

                # 4.3 Handle 404 / 400 (Not Found / Unroutable / Bad Request)
                if status in (400, 404):
                    ors_code: int | None = None
                    ors_msg: str | None = None
                    try:
                        err_payload = response.json()
                        if isinstance(err_payload, dict):
                            err_obj = err_payload.get("error", {})
                            if isinstance(err_obj, dict):
                                ors_code = err_obj.get("code")
                                ors_msg = err_obj.get("message")
                    except Exception:
                        pass

                    # ORS code 2010 indicates point could not be mapped to network
                    if ors_code == 2010 or status == 404:
                        raise RouteNotFoundError(
                            message=ors_msg or "No routable path found between points.",
                            provider="OpenRouteService",
                            details={"status_code": status, "ors_code": ors_code},
                        )

                    raise ProviderError(
                        message=(
                            f"OpenRouteService bad request (HTTP {status}): "
                            f"{ors_msg or response.text}"
                        ),
                        code=ErrorCode.INVALID_REQUEST,
                        provider="OpenRouteService",
                        http_status=status,
                        retryable=False,
                        safe_message=(
                            "Routing service rejected the coordinates as invalid."
                        ),
                        details={"status_code": status, "ors_code": ors_code},
                    )

                # 4.4 Handle 5xx Server Errors
                if 500 <= status < 600:
                    raise ProviderError(
                        message=f"OpenRouteService server error (HTTP {status}).",
                        code=ErrorCode.UNKNOWN_FAILURE,
                        provider="OpenRouteService",
                        http_status=status,
                        retryable=True,
                        safe_message=(
                            "Routing service is temporarily experiencing "
                            "upstream outages."
                        ),
                        details={"status_code": status},
                    )

                # 4.5 Parse Successful 2xx Response
                try:
                    payload = response.json()
                except Exception as err:
                    raise ProviderError(
                        message="OpenRouteService response was not valid JSON.",
                        code=ErrorCode.INVALID_RESPONSE,
                        provider="OpenRouteService",
                        retryable=False,
                        safe_message=(
                            "Routing service returned an unreadable response."
                        ),
                        details={"raw_text": response.text[:200]},
                    ) from err

                if not isinstance(payload, dict):
                    raise ProviderError(
                        message="OpenRouteService JSON payload must be an object.",
                        code=ErrorCode.INVALID_RESPONSE,
                        provider="OpenRouteService",
                        retryable=False,
                    )

                # Extract distance and duration from GeoJSON features or routes
                distance_m: float | None = None
                duration_s: float | None = None

                if "routes" in payload and isinstance(payload["routes"], list):
                    routes_list = payload["routes"]
                    if not routes_list:
                        raise RouteNotFoundError(
                            "OpenRouteService returned zero routes.",
                            provider="OpenRouteService",
                        )
                    first_route = routes_list[0]
                    summary_data = first_route.get("summary", {})
                    distance_m = summary_data.get("distance")
                    duration_s = summary_data.get("duration")

                elif "features" in payload and isinstance(payload["features"], list):
                    features_list = payload["features"]
                    if not features_list:
                        raise RouteNotFoundError(
                            "OpenRouteService returned zero features.",
                            provider="OpenRouteService",
                        )
                    first_feature = features_list[0]
                    props = first_feature.get("properties", {})
                    summary_data = props.get("summary", {})
                    distance_m = summary_data.get("distance")
                    duration_s = summary_data.get("duration")

                if distance_m is None or duration_s is None:
                    raise ProviderError(
                        message="OpenRouteService response missing summary metrics.",
                        code=ErrorCode.INVALID_RESPONSE,
                        provider="OpenRouteService",
                        retryable=False,
                        safe_message=(
                            "Routing service response format did not "
                            "contain expected metrics."
                        ),
                        details={"payload_keys": list(payload.keys())},
                    )

                dist_km = round(float(distance_m) / 1000.0, 2)
                dur_mins = round(float(duration_s) / 60.0, 1)

                meta = payload.get("metadata", {})
                attribution_str = meta.get(
                    "attribution", "openrouteservice.org | OpenStreetMap contributors"
                )

                source = SourceInfo(
                    provider="OpenRouteService",
                    url="https://openrouteservice.org/",
                    attribution=attribution_str,
                    fetched_at=request_time,
                    data_origin="live",
                )

                return RouteSummary(
                    distance_km=dist_km,
                    duration_minutes=dur_mins,
                    mode=canonical_mode,
                    origin=orig,
                    destination=dest,
                    source=source,
                    attribution=attribution_str,
                    fetched_at=request_time,
                    data_origin="live",
                )

            return await call_with_retry(
                _execute_single_request,
                policy=policy,
                sleep=self._retry_sleep,
                clock=self._retry_clock,
                random_source=self._retry_random,
                on_event=self._retry_on_event,
            )

    def get_route_sync(
        self,
        origin: tuple[float, float] | list[float],
        destination: tuple[float, float] | list[float],
        mode: str = "walking",
    ) -> RouteSummary:
        """Synchronously retrieve routing distance and duration."""
        coro = self.get_route(origin=origin, destination=destination, mode=mode)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, coro).result()
        return asyncio.run(coro)


async def async_get_route(
    origin: tuple[float, float] | list[float],
    destination: tuple[float, float] | list[float],
    mode: str = "walking",
    client: OpenRouteServiceClient | None = None,
) -> RouteSummary:
    """Convenience module function for asynchronous routing retrieval."""
    adapter = client or OpenRouteServiceClient()
    return await adapter.get_route(origin=origin, destination=destination, mode=mode)


def get_route(
    origin: tuple[float, float] | list[float],
    destination: tuple[float, float] | list[float],
    mode: str = "walking",
    client: OpenRouteServiceClient | None = None,
) -> RouteSummary:
    """Convenience module function for synchronous routing retrieval."""
    adapter = client or OpenRouteServiceClient()
    return adapter.get_route_sync(origin=origin, destination=destination, mode=mode)
