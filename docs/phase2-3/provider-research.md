# External Provider Research & Adapter Architecture (Phase 2)

This document provides verified technical facts, legal/licensing terms, and architectural adapter specifications for the external geocoding and weather provider (Open-Meteo) utilized in Phase 2 of AI Travel Concierge.

---

## 1. Provider Verification Log

All facts in this section were verified against official documentation pages accessed on **2026-10-24**.

| Resource | Official URL | Verification Status | Date Checked |
| :--- | :--- | :--- | :--- |
| **Terms of Service** | `https://open-meteo.com/en/terms` | **VERIFIED** | 2026-10-24 |
| **Licence & Attribution** | `https://open-meteo.com/en/licence` | **VERIFIED** | 2026-10-24 |
| **Geocoding API Documentation** | `https://open-meteo.com/en/docs/geocoding-api` | **VERIFIED** | 2026-10-24 |
| **Weather Forecast API Documentation** | `https://open-meteo.com/en/docs` | **VERIFIED** | 2026-10-24 |

---

## 2. Technical Specifications & Verified Endpoints

### 2.1 Geocoding API

- **Endpoint**: `https://geocoding-api.open-meteo.com/v1/search`  
  - *Verification*: **VERIFIED** (`https://open-meteo.com/en/docs/geocoding-api`)
- **HTTP Method**: `GET`
- **Authentication**: None required for non-commercial use (`apikey` parameter not needed).
- **Query Parameters**:
  - `name` (*Required*, string): Location name to search (minimum 2 characters).
  - `count` (*Optional*, integer): Maximum number of results to return (default: `10`, recommended for concierge: `1` to `5`).
  - `language` (*Optional*, string): Language code for location names (default: `en`).
  - `format` (*Optional*, string): Output format (default: `json`).
- **Verified Response Structure (Match Found)**:
  ```json
  {
    "results": [
      {
        "id": 2950159,
        "name": "Berlin",
        "latitude": 52.52437,
        "longitude": 13.41053,
        "elevation": 74.0,
        "feature_code": "PPLA",
        "country_code": "DE",
        "admin1_id": 2950157,
        "timezone": "Europe/Berlin",
        "population": 3426354,
        "country_id": 2921044,
        "country": "Germany",
        "admin1": "Berlin"
      }
    ],
    "generationtime_ms": 0.3540516
  }
  ```
- **Exact Fields Consumed by Concierge**:
  - `name`: string (e.g., `"Berlin"`)
  - `country`: string (e.g., `"Germany"`)
  - `admin1`: string | null (e.g., `"Berlin"`, administrative region / state)
  - `latitude`: float (e.g., `52.52437`)
  - `longitude`: float (e.g., `13.41053`)
  - `timezone`: string (e.g., `"Europe/Berlin"`, IANA timezone identifier)
- **Empty Result Structure (No Match Found)**:
  - *Verification*: **VERIFIED** (`https://open-meteo.com/en/docs/geocoding-api`)
  - When no location matches the search query, the `results` key is completely omitted:
    ```json
    {
      "generationtime_ms": 0.125
    }
    ```
  - The adapter must check for the existence of `results` and verify `len(results) > 0`; otherwise, it raises `EmptyResultError`.

---

### 2.2 Weather Forecast API

- **Endpoint**: `https://api.open-meteo.com/v1/forecast`  
  - *Verification*: **VERIFIED** (`https://open-meteo.com/en/docs`)
- **HTTP Method**: `GET`
- **Authentication**: None required for non-commercial use.
- **Query Parameters**:
  - `latitude` (*Required*, float): WGS84 latitude coordinate (-90.0 to 90.0).
  - `longitude` (*Required*, float): WGS84 longitude coordinate (-180.0 to 180.0).
  - `daily` (*Required for daily aggregations*, comma-separated string):  
    `temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,weather_code`
  - `timezone` (*Required when daily variables are requested*, string):  
    Use `auto` to resolve timezone automatically from coordinates (or pass IANA timezone from geocoding result, e.g. `Europe/Paris`).
  - `forecast_days` (*Optional*, integer 0-16): Number of forecast days (default: `7`, maximum: `16`).
  - `start_date` (*Optional*, string `YYYY-MM-DD`): Start date of forecast window.
  - `end_date` (*Optional*, string `YYYY-MM-DD`): End date of forecast window.
  - `temperature_unit` (*Optional*, string): `celsius` (default) or `fahrenheit`.
  - `precipitation_unit` (*Optional*, string): `mm` (default) or `inch`.
  - `timeformat` (*Optional*, string): `iso8601` (default) or `unixtime`.
- **Verified Response Structure**:
  ```json
  {
    "latitude": 52.52,
    "longitude": 13.419,
    "elevation": 44.812,
    "generationtime_ms": 2.2119,
    "utc_offset_seconds": 7200,
    "timezone": "Europe/Berlin",
    "timezone_abbreviation": "CEST",
    "daily_units": {
      "time": "iso8601",
      "temperature_2m_max": "°C",
      "temperature_2m_min": "°C",
      "precipitation_probability_max": "%",
      "precipitation_sum": "mm",
      "weather_code": "wmo code"
    },
    "daily": {
      "time": ["2026-10-24", "2026-10-25", "2026-10-26"],
      "temperature_2m_max": [16.2, 14.8, 13.5],
      "temperature_2m_min": [8.1, 7.4, 6.0],
      "precipitation_probability_max": [15, 65, 80],
      "precipitation_sum": [0.0, 3.2, 7.8],
      "weather_code": [2, 61, 63]
    }
  }
  ```
- **Exact Daily Fields Consumed by Concierge**:
  - `daily.time`: list[str] (ISO 8601 calendar dates `YYYY-MM-DD`)
  - `daily.temperature_2m_max`: list[float] (Daily high in Celsius)
  - `daily.temperature_2m_min`: list[float] (Daily low in Celsius)
  - `daily.precipitation_probability_max`: list[int] (Percentage chance of rain 0-100%)
  - `daily.precipitation_sum`: list[float] (Total liquid precipitation in mm)
  - `daily.weather_code`: list[int] (WMO weather interpretation code)

---

### 2.3 WMO Weather Interpretation Codes

Open-Meteo utilizes World Meteorological Organization (WMO) codes. The concierge maps these codes into human-readable descriptions and UI weather icons:

| WMO Code | Condition Description | Concierge UI Representation |
| :--- | :--- | :--- |
| `0` | Clear sky | ☀️ Sunny / Clear |
| `1` | Mainly clear | 🌤️ Mostly Sunny |
| `2` | Partly cloudy | ⛅ Partly Cloudy |
| `3` | Overcast | ☁️ Overcast |
| `45`, `48` | Fog and depositing rime fog | 🌫️ Foggy |
| `51`, `53`, `55` | Drizzle (light, moderate, dense) | 🌦️ Drizzle |
| `56`, `57` | Freezing drizzle | 🌨️ Freezing Drizzle |
| `61`, `63`, `65` | Rain (slight, moderate, heavy) | 🌧️ Rain |
| `66`, `67` | Freezing rain | 🌨️ Freezing Rain |
| `71`, `73`, `75` | Snow fall (slight, moderate, heavy) | ❄️ Snow |
| `77` | Snow grains | ❄️ Snow Grains |
| `80`, `81`, `82` | Rain showers (slight, moderate, violent) | 🌦️ Showers |
| `85`, `86` | Snow showers (slight, heavy) | 🌨️ Snow Showers |
| `95` | Thunderstorm (slight or moderate) | ⛈️ Thunderstorm |
| `96`, `99` | Thunderstorm with slight or heavy hail | ⛈️ Severe Thunderstorm |

---

## 3. Terms, Licensing, Attribution & Rate Limits

- *Verification*: **VERIFIED** (`https://open-meteo.com/en/terms` and `https://open-meteo.com/en/licence`)

### 3.1 Non-Commercial vs. Commercial Use
- **Non-Commercial Exemption**: Open-Meteo is completely free for non-commercial use, educational projects, open-source applications, and personal portfolio projects without an API key or account registration.
- **Commercial Boundary**: Commercial use (serving paying customers or monetized products) requires a paid subscription via `customer-api.open-meteo.com`. AI Travel Concierge is a non-commercial student portfolio project and qualifies for free tier access.

### 3.2 License & Attribution Requirements
- **License**: Creative Commons Attribution 4.0 International (**CC-BY 4.0**).
- **Geocoding Data Source**: Uses GeoNames data under CC-BY 4.0.
- **Required UI Attribution**:
  - The documentation explicitly mandates clear attribution whenever Open-Meteo data is presented to users.
  - Required HTML/UI snippet:
    ```html
    <a href="https://open-meteo.com/" target="_blank" rel="noopener noreferrer">Weather data by Open-Meteo.com</a>
    ```
  - For geocoding display:
    ```text
    Location data by Open-Meteo and GeoNames (CC-BY 4.0)
    ```

### 3.3 Rate Limits & Fair-Use Limits
- **Hourly Limit**: 5,000 API calls per hour.
- **Daily Limit**: 10,000 API calls per day.
- **Burst Limit**: 600 API calls per minute.
- **Monthly Limit**: 300,000 API calls per month.
- **Enforcement Mechanism**: Returns HTTP `429 Too Many Requests` if limits are exceeded.

---

## 4. Forecast Data Horizon & Truthfulness Rule

### 4.1 Maximum Horizon
- *Verification*: **VERIFIED** (`https://open-meteo.com/en/docs`)
- The Open-Meteo weather forecast API has a maximum forecast horizon of **16 days** (`forecast_days=16`).
- Forecasts beyond 16 days cannot be generated by numerical weather prediction models due to physical atmospheric predictability limits.

### 4.2 Application Behavior Beyond Horizon
To maintain absolute truthfulness and prevent AI or algorithmic hallucinations:
1. **Never Invent Weather**: If user travel dates start beyond 16 days from today, the concierge **must not** generate, simulate, or guess temperature, precipitation, or sky conditions.
2. **Graceful Notice**: The backend returns `WeatherSummary.days = []` with a clear user-facing notice:
   ```text
   "Weather forecast is unavailable for dates beyond the 16-day forecast horizon. Check back closer to your departure date."
   ```
3. **Future Extension Option (Phase 3+)**:
   - The Open-Meteo Historical Weather API (`https://archive-api.open-meteo.com/v1/archive`) or Climate Change API (`https://climate-api.open-meteo.com/v1/climate`) can provide historical climate averages for the same calendar week in previous years.
   - If implemented later, this data **must be explicitly labeled** as `"Historical Climate Average (Past Years)"` and classified as `Provenance.ESTIMATE`, never as an active forecast.

---

## 5. Error Behavior & Response Shapes

### 5.1 HTTP 400 Bad Request
- *Verification*: **VERIFIED** (`https://open-meteo.com/en/docs`)
- Occurs on invalid query parameters (e.g. unknown weather variable, out-of-range coordinates).
- Response shape:
  ```json
  {
    "error": true,
    "reason": "Cannot initialize WeatherVariable from invalid String value invalid_var for key daily"
  }
  ```

### 5.2 HTTP 429 Too Many Requests
- Occurs when burst limit (600/min) or daily fair-use limits are exceeded.
- Response header often contains `Retry-After`. The adapter extracts this header for bounded exponential backoff.

### 5.3 Empty Geocoding Response
- *Verification*: **VERIFIED** (`https://open-meteo.com/en/docs/geocoding-api`)
- Does not return an HTTP 404; returns HTTP 200 with no `results` key:
  ```json
  {
    "generationtime_ms": 0.125
  }
  ```
- The adapter normalizes this into `EmptyResultError` or `None`.

### 5.4 Timezone & Unit Handling
- Open-Meteo defaults to UTC (`GMT+0`) unless `&timezone=auto` or a specific IANA timezone (e.g. `&timezone=America/New_York`) is provided.
- For daily forecasts, `timezone` is **mandatory**. The adapter always supplies the IANA timezone resolved from the geocoding phase, ensuring day boundaries align with the destination's midnight-to-midnight local time.

---

## 6. Provider Decision

### Decision: Keep Open-Meteo
**Status**: **RECOMMENDED & ADOPTED FOR PHASE 2**

#### Rationale:
1. **Zero Authentication Overhead**: No API keys, secrets, or credential rotation required for development, testing, and non-commercial portfolio use.
2. **Combined Ecosystem**: Both geocoding and weather forecasts are served by Open-Meteo with compatible geographic schemas.
3. **Generous Rate Limits**: 10,000 calls/day provides immense headroom for local development and CI test suites without throttling risks.
4. **WMO Standard Compliance**: Uses standard WMO weather interpretation codes, facilitating predictable, deterministic UI icon and text mapping.
5. **Transparency & Openness**: Open-source server implementation with open meteorological data sources (DWD, NOAA, ECMWF, Météo-France).

---

## 7. Adapter Architectural Design

### 7.1 Module Layout

The adapter resides in `backend/app/providers/open_meteo/`:

```text
backend/app/providers/open_meteo/
├── __init__.py           # Public exports (OpenMeteoAdapter, provider exceptions)
├── client.py             # Async HTTP client wrapper using httpx.AsyncClient
├── normalizers.py        # Transformation of raw JSON payloads to domain Pydantic models
├── errors.py             # Provider-specific error hierarchy
├── config.py             # Settings: base URLs, timeouts, retry limits, provider mode
└── fixtures/             # Real recorded payloads used for deterministic mock mode & tests
    ├── geocode_paris.json
    ├── geocode_tokyo.json
    ├── geocode_empty.json
    ├── forecast_paris_7day.json
    └── forecast_error_400.json
```

### 7.2 Error Taxonomy

All provider exceptions inherit from `ProviderError`, enabling the concierge service to catch provider failures uniformly without leaking third-party HTTP details into the core domain:

```python
class ProviderError(Exception):
    """Base exception for all external provider errors."""
    def __init__(self, message: str, provider: str = "Open-Meteo", details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.details = details or {}

class TimeoutError(ProviderError):
    """Raised when external provider request times out."""

class NetworkUnavailableError(ProviderError):
    """Raised on DNS resolution failures or socket connection refusal."""

class HttpError(ProviderError):
    """Raised when provider returns unexpected 4xx or 5xx status codes."""
    def __init__(self, status_code: int, message: str, reason: str | None = None):
        super().__init__(message, details={"status_code": status_code, "reason": reason})
        self.status_code = status_code
        self.reason = reason

class RateLimitExceededError(ProviderError):
    """Raised when HTTP 429 Too Many Requests is received."""
    def __init__(self, retry_after: float | None = None):
        super().__init__("Open-Meteo rate limit exceeded", details={"retry_after": retry_after})
        self.retry_after = retry_after

class MalformedResponseError(ProviderError):
    """Raised when provider response violates expected JSON structure."""

class EmptyResultError(ProviderError):
    """Raised when geocoding search yields no matching locations."""
```

### 7.3 Timeouts & Bounded Retries

- **Timeouts**:
  - Connect Timeout: **3.0 seconds**
  - Read Timeout: **5.0 seconds**
  - Total Request Timeout: **8.0 seconds**
- **Retry Policy**:
  - **Bounded Retries**: Maximum **3 attempts** (1 initial request + up to 2 retries).
  - **Retryable Conditions**:
    - `RateLimitExceededError` (HTTP 429) — wait for `Retry-After` header or exponential backoff.
    - `HTTP 503 Service Unavailable` / `502 Bad Gateway`.
    - Transient connection dropouts (`httpx.ConnectError`).
  - **Non-Retryable Conditions (Fail Immediately)**:
    - HTTP 400 Bad Request (client configuration bug).
    - HTTP 404 Not Found.
    - `EmptyResultError` (no records found).
    - `MalformedResponseError` (unrecoverable schema mismatch).
  - **Backoff Algorithm**: Exponential backoff with full jitter:  
    `sleep_time = min(max_backoff, base_backoff * (2 ** attempt)) + random.uniform(0, 0.5)`

### 7.4 Provider Modes (`PROVIDER_MODE=live|mock`)

The adapter supports dual operating modes configured via environment variable `PROVIDER_MODE`:

1. **`live` Mode**:
   - Executes real HTTP requests over the wire via `httpx.AsyncClient`.
   - Populates `SourceInfo.data_origin = "live"`.
   - Requires internet connectivity; subject to Open-Meteo rate limits.
2. **`mock` Mode**:
   - Intercepts requests and loads pre-recorded JSON responses from `backend/app/providers/open_meteo/fixtures/`.
   - Never makes external network calls.
   - Populates `SourceInfo.data_origin = "mock"`.
   - Enables fast, offline, fully deterministic local development and test execution.

### 7.5 Attribution Construction (`SourceInfo`)

Every normalized model produced by the adapter carries an explicit `SourceInfo` instance:

```python
from datetime import datetime, timezone

def build_source_info(data_origin: str) -> SourceInfo:
    return SourceInfo(
        provider="Open-Meteo",
        url="https://open-meteo.com/",
        attribution="Weather data by Open-Meteo.com (CC-BY 4.0)",
        fetched_at=datetime.now(timezone.utc),
        data_origin=data_origin,
    )
```

In the frontend UI, this attribution is displayed as a subtle link in the footer of every weather forecast and geocoded location card, satisfying Open-Meteo's CC-BY 4.0 license.

### 7.6 Fixture Plan

Fixtures are exact snapshots of real Open-Meteo responses:
1. `geocode_paris.json`: Canonical city geocoding with populated `admin1`, `country`, and `timezone`.
2. `geocode_tokyo.json`: International non-Western destination.
3. `geocode_empty.json`: Search result returning `{"generationtime_ms": 0.1}` (no `results` key) to test graceful empty handling.
4. `forecast_paris_7day.json`: Complete 7-day daily forecast matching Paris coordinates.
5. `forecast_beyond_horizon.json`: Handling for dates > 16 days out.
6. `error_400_invalid_var.json`: Error payload for testing `HttpError` normalization.

### 7.7 Test Plan

The test suite for the adapter consists of three isolated testing tiers:

1. **Unit Tests for Normalizers (`tests/unit/test_open_meteo_normalizers.py`)**:
   - Test transformation of raw JSON fixtures into `GeocodeResult` and `WeatherSummary` Pydantic models.
   - Test fallback when `admin1` is null or missing.
   - Test WMO code mapping for all 15 condition categories.
   - Test horizon note generation when trip dates exceed 16 days.
2. **Unit Tests for Client & Error Handling (`tests/unit/test_open_meteo_client.py`)**:
   - Use `pytest-httpx` or `respx` to simulate network errors, HTTP 400, HTTP 429, and timeouts.
   - Verify proper exception translation into the domain error hierarchy (`RateLimitExceededError`, `TimeoutError`, etc.).
   - Verify retry bounds (maximum 2 retries on 429/503; 0 retries on 400).
3. **Deterministic Mock Mode Tests (`tests/unit/test_open_meteo_mock_mode.py`)**:
   - Verify that when `PROVIDER_MODE=mock`, known queries return corresponding fixture data with `data_origin == "mock"` without network access.
4. **Live Provider Contract Verification (`tests/integration/test_open_meteo_live.py`)**:
   - Gated behind `@pytest.mark.skipif(os.getenv("PROVIDER_MODE") != "live", reason="Live provider tests require PROVIDER_MODE=live")`.
   - Verifies that live Open-Meteo endpoints have not altered their response schemas.
