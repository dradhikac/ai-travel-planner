# Phase 4 Third-Tool Provider Research & Selection Decision

- **Date of Verification**: 2026-11-09
- **Author**: AI Travel Concierge Planning & Reliability Team
- **Role**: Documentation & Planning (`DOCUMENTATION / PLANNING`)
- **Status**: **Recommendation Pending Human Developer Approval**
- **Strict Boundary**: AI Travel Concierge is a travel discovery and planning assistant, **NOT a booking engine**. It never claims to execute bookings, reservations, purchases, tickets, or cancellations. All flight or hotel data ever displayed must carry provider, `fetched_at`, and `"indicative, not bookable here"`.

---

## 1. Overview & Research Objective

Phase 4 introduces a third tool to augment the existing Phase 2 and Phase 3 tools (`geocode_destination` and `weather_forecast`). The primary operational objective of this tool is **route and transit feasibility verification** (`get_route_context`):
1. Compute transit distance (km) and estimated travel duration (minutes) between trip origin and destination, or between daily scheduled points of interest (POIs).
2. Support distinct travel modalities: pedestrian walking (`walking`), cycling (`cycling`), and motor vehicles (`driving`).
3. Maintain zero live external API dependencies for tests by pairing the live client with deterministic offline fixtures (`backend/tests/fixtures/route_fixtures.json`).
4. Ensure absolute credential safety: API keys must never appear in query parameters, URLs, or log strings.
5. Permit local persistence and caching: results must be safely storeable in PostgreSQL (`trips` and `itinerary_versions`) in accordance with provider licensing.

This document evaluates two routing providers (OSRM demo server and OpenRouteService hosted API) and one alternative search/places provider (OpenTripMap) against these criteria.

---

## 2. Candidate 1: OSRM (Open Source Routing Machine) Public Demo Server

- **Provider Category**: Open-source routing engine (Public Demo Server)
- **Status**: **VERIFIED** (Inspected 2026-11-09)
- **Official URLs**:
  - API Specification: [https://project-osrm.org/docs/v5.24.0/api/](https://project-osrm.org/docs/v5.24.0/api/)
  - Demo Server Usage Policy: [https://github.com/Project-OSRM/osrm-backend/wiki/API-Usage-Policy](https://github.com/Project-OSRM/osrm-backend/wiki/API-Usage-Policy)
  - Public Demo Endpoint: `https://router.project-osrm.org` (and `http://router.project-osrm.org`)

### Technical Specification
- **Endpoint Structure**:
  `GET https://router.project-osrm.org/route/v1/{profile}/{coordinates}`
- **Coordinate Order Convention**:
  - Format: `{longitude},{latitude}` pairs separated by semicolons (`;`).
  - Example: `GET /route/v1/driving/2.3522,48.8566;2.2945,48.8584?overview=false`
  - *Order*: **Longitude first, Latitude second**.
- **Transport Profiles**:
  - Engine supports: `driving` (car), `walking` (foot), and `cycling` (bicycle).
  - **CRITICAL DEMO SERVER LIMITATION**: The public demo server at `router.project-osrm.org` is preprocessed and hosted **exclusively for the `driving` profile**. Requests with `/walking/` or `/cycling/` are mapped internally to the driving car dataset, ignoring pedestrian paths and footways.
- **Key Parameters**:
  - `overview`: `simplified`, `full`, or `false` (set `false` to minimize payload).
  - `steps`: `true` or `false` (turn-by-turn maneuvers).
  - `alternatives`: `true` or `false` (default is 1 route).
- **Response Fields & Units**:
  - `code`: String status (`"Ok"` on success).
  - `routes[0].distance`: Float in **meters** (convert: `distance_km = round(distance / 1000.0, 2)`).
  - `routes[0].duration`: Float in **seconds** (convert: `duration_minutes = round(duration / 60.0)`).
  - `waypoints`: Array of snapped road coordinates `[longitude, latitude]`.

### Authentication & Log Safety
- **API Key Required**: **No**. Free anonymous access.
- **Header vs. Query**: No credentials passed.
- **Log Safety**: High. URLs contain only geographic coordinates, so URL logging poses zero secret leakage risk.

### Terms, Rate Limits & Caching
- **Acceptable Use Policy**:
  - Strictly intended for **showcase, testing, and hobby demonstration**.
  - **Explicitly forbidden for production or commercial tools** with active user traffic.
- **Rate Limits & Capacity**:
  - Recommended threshold: **< 1 request per second** per client.
  - Global server ceiling: ~5,000 requests per minute total across all global users.
  - Exceeding bounds results in automated HTTP 429 IP bans.
- **Uptime & SLA**: No SLA. Server can experience unannounced downtime or throttling.
- **Data License & Attribution**:
  - Open Data Commons Open Database License (ODbL).
  - Attribution text required: `"© OpenStreetMap contributors"`.
  - Caching results locally in database is permitted under ODbL terms.

### Error Behavior & Envelopes
- **HTTP 400 Bad Request**:
  - Syntax error: `{"code": "InvalidQuery", "message": "Query string syntax error..."}`
  - No path found: `{"code": "NoRoute", "message": "Impossible route between points"}`
- **HTTP 429 Too Many Requests**: Triggered when client exceeds the request rate threshold.
- **HTTP 500 / 502**: Upstream worker crashes or routing engine timeout.

### Architectural Fit Assessment
- **Fit Score**: **POOR for Hosted Public API / EXCELLENT for Local Docker Self-Hosting**.
- **Pros**: Zero cost, no API keys, standard JSON schema, simple math.
- **Blockers for Production**:
  1. Public demo server only supports driving routes; pedestrian walking durations between tourist spots cannot be retrieved accurately.
  2. Public demo server policy explicitly bans production application use.

---

## 3. Candidate 2: OpenRouteService (ORS) Directions API v2

- **Provider Category**: Hosted Routing API with Developer Tier (HeiGIT gGmbH)
- **Status**: **VERIFIED** (Inspected 2026-11-09)
- **Official URLs**:
  - Main Portal: [https://openrouteservice.org/](https://openrouteservice.org/)
  - API Documentation: [https://openrouteservice.org/dev/#/api-docs/v2/directions/{profile}/post](https://openrouteservice.org/dev/#/api-docs/v2/directions/{profile}/post)
  - Terms of Service: [https://openrouteservice.org/terms-of-service/](https://openrouteservice.org/terms-of-service/)
  - Account Dashboard: [https://account.heigit.org](https://account.heigit.org)
  - Hosted Base URL: `https://api.openrouteservice.org/v2/directions` (and `https://api.heigit.org/openrouteservice/v2/directions`)

### Technical Specification
- **Endpoint Structure**:
  - Standard POST: `POST https://api.openrouteservice.org/v2/directions/{profile}`
  - Simple GET: `GET https://api.openrouteservice.org/v2/directions/{profile}?start={lon1},{lat1}&end={lon2},{lat2}`
- **Coordinate Order Convention**:
  - Format: GeoJSON standard `[longitude, latitude]`.
  - Example POST Payload:
    ```json
    {
      "coordinates": [
        [2.3522, 48.8566],
        [2.2945, 48.8584]
      ],
      "instructions": false,
      "elevation": false
    }
    ```
  - *Order*: **Longitude first, Latitude second**.
- **Transport Profiles**:
  - Full native multi-modal support:
    - `foot-walking`: Pedestrian sidewalks, pedestrian plazas, trails, avoiding highways.
    - `driving-car`: Automobiles respecting one-ways, turn restrictions, and speed limits.
    - `cycling-regular`: Bicycles utilizing bike paths and side streets.
    - `foot-hiking`: Off-road trails and hiking paths.
- **Response Fields & Units**:
  - `routes[0].summary.distance`: Float in **meters** (convert: `distance_km = round(distance / 1000.0, 2)`).
  - `routes[0].summary.duration`: Float in **seconds** (convert: `duration_minutes = round(duration / 60.0)`).
  - `metadata.attribution`: String (`"openrouteservice.org | OpenStreetMap contributors"`).
  - `metadata.timestamp`: UTC timestamp in epoch milliseconds.

### Authentication & Log Safety
- **API Key Required**: **Yes** (Free developer account via HeiGIT account dashboard).
- **Header vs. Query**:
  - Primary Method: Passed via HTTP Request Header:
    ```http
    Authorization: YOUR_ORS_API_KEY
    ```
  - *(Optional query param `?api_key=...` is supported but discouraged).*
- **Log Safety**: **MAXIMAL**. Because the API key is passed strictly in the `Authorization` request header and **NOT** in the URL query string, full request URLs (e.g., `https://api.openrouteservice.org/v2/directions/foot-walking`) can be logged safely without leaking credentials.

### Terms, Rate Limits & Caching
- **Free Tier Allowances**:
  - **8,000 requests per day** (daily quota).
  - **40 requests per minute** (concurrency limit).
  - Max distance per request: 6,000 km for `driving-car` and `foot-walking`.
  - Max waypoints per request: 50 points.
- **Allowed Use**:
  - Permitted for research, educational, developer prototyping, and small production applications.
- **Caching & Storage Policy**:
  - **Client-Side Caching Permitted**: Developers are actively encouraged to cache routing calculations to reduce redundant compute loads on the public servers.
  - Storing route summaries and durations in our PostgreSQL database (`trips` table) is completely compliant with ORS terms.
- **Attribution & Data License**:
  - Open Data Commons Open Database License (ODbL).
  - Mandatory visible attribution: `"openrouteservice.org | OpenStreetMap contributors"`.

### Error Behavior & Envelopes
OpenRouteService provides structured JSON error envelopes:

```json
{
  "error": {
    "code": 2010,
    "message": "Could not find routable point within a radius of 350.0 meters of specified coordinate [2.352200, 48.856600]."
  },
  "info": {
    "engine": { "version": "7.1.0" },
    "timestamp": 1690000000000
  }
}
```

| HTTP Status | ORS Error Code | Cause / Trigger | Safe Mapping |
| :---: | :---: | :--- | :--- |
| **400** | `2003` | Malformed parameter or swapped coordinates. | `ProviderErrorCode.INVALID_REQUEST` |
| **401** | `401` | Missing, unauthorized, or invalid API key. | `ProviderErrorCode.AUTHENTICATION_FAILED` |
| **404** | `2010` | Point >350m from routable network (e.g. ocean). | `ProviderErrorCode.INVALID_REQUEST` |
| **429** | `9001` | Breached 40 RPM limit or 8,000 daily quota. | `ProviderErrorCode.RATE_LIMITED` |
| **500 / 504** | `500` / `504` | Routing engine failure or gateway timeout. | `ProviderErrorCode.TIMEOUT` / `PROVIDER_UNAVAILABLE` |

### Architectural Fit Assessment
- **Fit Score**: **EXCELLENT (Recommended)**.
- **Pros**:
  1. Full native support for `foot-walking` (vital for day itinerary pacing) and `driving-car`.
  2. Header-based authentication (`Authorization: <KEY>`) guarantees zero credential exposure in logs or URLs.
  3. Generous free tier: 8,000 requests/day easily covers local development and testing.
  4. Caching and local persistence are explicitly welcomed by the provider.
  5. Clean, structured JSON error codes for deterministic exception handling.

---

## 4. Candidate 3 (Alternative): OpenTripMap Places API

- **Provider Category**: Points of Interest (POI) & Tourist Attractions Search (Alternative Category)
- **Status**: **VERIFIED** (Inspected 2026-11-09)
- **Official URLs**:
  - Product Information: [https://opentripmap.io/product](https://opentripmap.io/product)
  - Documentation: [https://opentripmap.org/](https://opentripmap.org/)
  - API Catalog: OpenTripMap Developer Portal

### Technical Specification
- **Endpoint Structure**:
  - Radius Search: `GET https://api.opentripmap.com/0.1/{lang}/places/radius`
- **Parameters**:
  - `lat`: Center latitude float.
  - `lon`: Center longitude float.
  - `radius`: Search radius in meters (e.g., `5000`).
  - `kinds`: Comma-separated category filters (e.g., `museums,historic,architecture,cultural`).
  - `rate`: Importance rating filter (`1`, `2`, `3`).
  - `limit`: Maximum items to return (e.g., `10`).
  - `apikey`: API key query parameter.
- **Response Structure**:
  - Returns array of POI objects:
    ```json
    [
      {
        "xid": "W12345678",
        "name": "Musée du Louvre",
        "dist": 142.5,
        "rate": 3,
        "kinds": "museums,cultural,historic",
        "point": { "lon": 2.3364, "lat": 48.8606 }
      }
    ]
    ```

### Authentication & Log Safety
- **API Key Required**: **Yes** (Free account key).
- **Header vs. Query**: Passed as **Query Parameter** (`?apikey=...`).
- **Log Safety**: **MODERATE**. Because the key is passed in the query string, all URL logging utilities must strictly strip `apikey` using `sanitize_url()` to prevent exposing credentials in log files.

### Terms, Rate Limits & Caching
- **Free Tier Allowances**:
  - ~5,000 requests per day.
  - ~10 requests per second rate limit.
- **Caching & Storage Policy**:
  - Governed by Open Data Commons Open Database License (ODbL).
  - Explicitly permits storing, indexing, pre-fetching, and caching data locally.
- **Attribution**: Mandatory attribution to OpenTripMap and OpenStreetMap contributors.

### Architectural Fit Assessment
- **Fit Score**: **STRONG FOR PHASE 5 / OUT OF SCOPE FOR PHASE 4**.
- **Assessment**:
  - OpenTripMap is an outstanding candidate for **destination enrichment and attraction discovery**.
  - However, OpenTripMap does **NOT** compute routes, road networks, or travel durations between two points. It cannot answer: *"How long does it take to walk from the Louvre to the Eiffel Tower?"*
  - Therefore, it cannot fulfill Phase 4's primary requirement of validating itinerary pacing and transit feasibility. It is deferred to Phase 5.

---

## 5. Comparative Evaluation Matrix

| Evaluation Dimension | Candidate 1: OSRM Demo Server | Candidate 2: OpenRouteService (ORS) | Candidate 3: OpenTripMap (Search) |
| :--- | :--- | :--- | :--- |
| **Capability Type** | Point-to-point road routing | Multi-modal directions (walking, cycling, car) | POI & attraction discovery |
| **Walking Support (`foot`)** | ❌ **No** (demo server maps all to car) | ✅ **Yes** (`foot-walking`, `foot-hiking`) | ❌ N/A (search only) |
| **Driving Support (`car`)** | ✅ **Yes** (`driving`) | ✅ **Yes** (`driving-car`) | ❌ N/A (search only) |
| **API Key Needed?** | ❌ No (anonymous) | ✅ Yes (Free registration) | ✅ Yes (Free registration) |
| **Auth Delivery Method** | None | ✅ **Header (`Authorization: <key>`)** | ⚠️ Query param (`?apikey=...`) |
| **URL Log Safety** | ✅ High (no key in URL) | ✅ **High (key strictly in header)** | ⚠️ Medium (requires URL stripping) |
| **Free Tier Quotas** | ~1 req/sec; no SLA | ✅ **8,000 req/day; 40 req/min** | ~5,000 req/day; 10 req/sec |
| **Commercial / Production Use** | ❌ **Banned on demo server** | ✅ **Permitted under free fair-use** | ✅ Permitted under ODbL |
| **Local Persistence & Caching** | Permitted with OSM attribution | ✅ **Permitted & encouraged** | ✅ Permitted under ODbL |
| **Attribution Requirement** | `"© OpenStreetMap contributors"` | `"openrouteservice.org | OSM contributors"` | `"OpenTripMap | OSM contributors"` |
| **Coordinate Ordering** | `[lon, lat]` in URL path | `[lon, lat]` in JSON body / GeoJSON | `lat`, `lon` in query parameters |
| **Error Envelopes** | Basic string codes (`InvalidQuery`) | Detailed JSON codes (`2003`, `2010`, `9001`) | Standard HTTP status codes |
| **Phase 4 Goal Alignment** | ⚠️ Partial (no walking profile) | ⭐ **Complete alignment** | ❌ Solves different goal |

---

## 6. Primary Recommendation & Selection Decision

### Recommendation: OpenRouteService (ORS) Directions API v2
We recommend selecting **OpenRouteService (ORS) Directions API v2** as the third external provider backing the `get_route_context` tool.

### Core Justification:
1. **Multi-Modal Transit for Realistic Itineraries**: AI Travel Concierge itineraries are primarily urban walking tours and local city exploration. ORS provides high-fidelity `foot-walking` routes taking pedestrian footways, plazas, and pedestrianized alleys into account, alongside `driving-car` for inter-city transit. OSRM's public demo server fails here because it only supports car traffic.
2. **Superior Security Posture**: Authentication is delivered via the HTTP `Authorization` header. This ensures API keys are **never** present in request URL paths or query parameters, completely eliminating accidental credential exposure in server logs, browser network traces, or terminal outputs.
3. **Generous, Sustainable Free Quotas**: 8,000 requests per day is more than sufficient for solo developer workflows, staging, and prototype usage without paying for infrastructure.
4. **Explicit Caching Compliance**: ORS's terms explicitly encourage client-side caching to reduce server load, directly supporting our architectural model of storing itinerary versions and route summaries in PostgreSQL.
5. **Deterministic Offline Fallback**: In the absence of an API key or when network access is unavailable, the tool cleanly falls back to deterministic offline fixtures (`backend/tests/fixtures/route_fixtures.json`) and heuristic estimations without failing the application.

### Role of Alternatives:
- **OSRM**: Retained as an architectural option for future **self-hosted on-premise container deployment** via Docker (`docker run -t -p 5000:5000 osrm/osrm-backend`). If user traffic grows beyond ORS free quotas, OSRM can be spun up as an internal container service with zero API key dependencies.
- **OpenTripMap**: Recommended as Candidate 1 for **Phase 5 (Travel Domain Integrations)** to enrich daily itineraries with verified point-of-interest descriptions and cultural ratings.

---

## 7. Configuration Variables Specification (Names Only)

To prevent credential leakage and support seamless switching between live and offline environments, the following typed settings will be added to `backend/app/core/config.py` during implementation:

```python
# OpenRouteService Provider Settings (Names Only - No Secrets)
OPENROUTESERVICE_API_KEY: str | None = None
OPENROUTESERVICE_BASE_URL: str = "https://api.openrouteservice.org/v2/directions"
OPENROUTESERVICE_TIMEOUT_SECONDS: float = 4.0
OPENROUTESERVICE_MAX_RETRIES: int = 1
ROUTING_PROVIDER_MODE: Literal["live", "mock"] = "mock"
```

### Safe Degradation Policy
- If `ROUTING_PROVIDER_MODE="mock"` or `OPENROUTESERVICE_API_KEY` is unset or blank (`None`):
  - The routing adapter operates in **deterministic mock mode**.
  - Requests matching known test coordinates return static fixture entries from `route_fixtures.json`.
  - Unmatched coordinates return deterministic heuristic distance/time calculations labeled with `provenance="estimate"`.
  - The application **never crashes or raises unhandled exceptions** due to a missing API key.

---

## 8. Deterministic Offline Fixture Plan

To ensure that backend unit tests and CI pipelines run 100% offline with zero network latency and zero flake, a deterministic fixture catalog will be established in `backend/tests/fixtures/route_fixtures.json` [PLANNED].

### Fixture Schema & Pre-recorded Pairs
The fixture database will store standardized round-trip and point-to-point routes for all core test destinations:

```json
{
  "fixtures": [
    {
      "id": "route_paris_louvre_to_eiffel",
      "origin": "Musée du Louvre, Paris",
      "destination": "Eiffel Tower, Paris",
      "origin_coords": [2.3364, 48.8606],
      "destination_coords": [2.2945, 48.8584],
      "mode": "foot-walking",
      "distance_km": 3.75,
      "duration_minutes": 48,
      "summary": "Walk along the Seine via Quai Branly",
      "provenance": "retrieved",
      "source": "openrouteservice.org | OpenStreetMap contributors"
    },
    {
      "id": "route_london_bigben_to_tower",
      "origin": "Big Ben, London",
      "destination": "Tower of London",
      "origin_coords": [-0.1246, 51.5007],
      "destination_coords": [-0.0759, 51.5081],
      "mode": "foot-walking",
      "distance_km": 4.12,
      "duration_minutes": 52,
      "summary": "Walk east along the Queen's Walk and Thames Path",
      "provenance": "retrieved",
      "source": "openrouteservice.org | OpenStreetMap contributors"
    },
    {
      "id": "route_tokyo_shinjuku_to_shibuya",
      "origin": "Shinjuku Station, Tokyo",
      "destination": "Shibuya Crossing, Tokyo",
      "origin_coords": [139.7006, 35.6896],
      "destination_coords": [139.7013, 35.6595],
      "mode": "foot-walking",
      "distance_km": 3.40,
      "duration_minutes": 44,
      "summary": "Walk south via Meiji-dori past Yoyogi Park",
      "provenance": "retrieved",
      "source": "openrouteservice.org | OpenStreetMap contributors"
    }
  ]
}
```

---

## 9. Developer Verification Checklist (What the Solo Developer Must Verify)

Before implementing the routing adapter in `feature/phase4-routing-tool`, the human developer should manually verify the following operational items:

1. [ ] **Acquire Free ORS API Key**: Register a free account at [https://account.heigit.org](https://account.heigit.org) and generate a standard API token.
2. [ ] **Local Environment Configuration**: Add `OPENROUTESERVICE_API_KEY=<token>` to your local non-tracked `.env` file (verify `.env` is listed in `.gitignore`).
3. [ ] **Verify Network Reachability**: Run a single curl/PowerShell verification command from your development machine to ensure HeiGIT endpoints are reachable without proxy blocks:
   ```powershell
   # PowerShell Verification Command
   $headers = @{ "Authorization" = "$env:OPENROUTESERVICE_API_KEY"; "Content-Type" = "application/json" }
   $body = '{"coordinates":[[2.3522,48.8566],[2.2945,48.8584]]}'
   Invoke-RestMethod -Uri "https://api.openrouteservice.org/v2/directions/foot-walking" -Method Post -Headers $headers -Body $body
   ```
4. [ ] **Approve Recommendation**: Confirm approval of OpenRouteService (ORS) as the primary provider for `get_route_context` to proceed with implementation.
