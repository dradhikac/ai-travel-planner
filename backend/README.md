# Backend Service

Python, FastAPI, and Pydantic backend API service for AI Travel Concierge.

Phase 1 foundation: FastAPI modular monolith application factory, health check (`GET /health`), version metadata (`GET /api/version`), centralized error handling, and unit test harness.

---

## Selected Dependency Versions

- **Python**: `3.11` (specifically `3.11.9`)
- **FastAPI**: `0.146.0` (`fastapi~=0.146.0`)
- **Uvicorn (Standard)**: `0.54.0` (`uvicorn[standard]~=0.54.0`)
- **Pydantic Settings**: `2.16.0` (`pydantic-settings~=2.16.0`)
- **Pytest**: `9.1.1` (`pytest~=9.1.1`)
- **HTTPX**: `0.28.1` (`httpx~=0.28.1`)
- **Ruff**: `0.17.1` (`ruff~=0.17.1`)
- **SQLAlchemy**: `2.0.55` (`sqlalchemy~=2.0.55`)
- **Psycopg**: `3.2.13` (`psycopg[binary]~=3.2.13`)
- **Alembic**: `1.14.1` (`alembic~=1.14.1`)

---

## Local Setup & Commands

### 1. Create and Activate Virtual Environment

**PowerShell (Windows 11)**:
```powershell
# From backend directory
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**Bash**:
```bash
# From backend directory
python3.11 -m venv .venv
source .venv/bin/activate
```

### 2. Install Dependencies

**PowerShell & Bash**:
```bash
pip install -r requirements-dev.txt
```

### 3. Run Development Server

**PowerShell & Bash**:
```bash
python -m uvicorn app.main:app --reload --port 8000
```
API endpoints will be available at:
- Health check: [http://localhost:8000/health](http://localhost:8000/health)
- Database readiness: [http://localhost:8000/health/db](http://localhost:8000/health/db)
- Version metadata: [http://localhost:8000/api/version](http://localhost:8000/api/version)
- OpenAPI interactive docs: [http://localhost:8000/docs](http://localhost:8000/docs)

### 4. Run Linter and Formatter Checks

**PowerShell**:
```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

**Bash**:
```bash
./.venv/bin/python -m ruff check .
./.venv/bin/python -m ruff format --check .
```

### 5. Run Test Suite

**PowerShell**:
```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

**Bash**:
```bash
./.venv/bin/python -m pytest -q
```

### 6. Database Migrations (Alembic)

When `DATABASE_URL` is configured in `backend/.env` (and PostgreSQL is running):

**PowerShell & Bash**:
```bash
# Apply migrations to the latest revision:
python -m alembic upgrade head

# Inspect the current migration revision:
python -m alembic current
```

---

## Phase 2 Domain Services

### Deterministic Itinerary Generator (`app.services.itinerary`)

Pure, deterministic rule-based day-by-day itinerary generation engine:
- **Pace constants**: `relaxed` (2 items/day), `balanced` (3 items/day), `packed` (4 items/day).
- **Generic interest templates**: Food, museums, nature, history, shopping, nightlife, and general civic exploration.
- **Strict provenance**: Facts vs suggestions (`retrieved`, `generated_suggestion`, `estimate`, `unknown`).
- **Weather-driven adaptation**: High rain probability (>= 40%) deterministically prioritizes indoor activities ahead of outdoor activities.
- **Budget planning allocation**: Computes rough daily planning allocations labeled `estimate` (not price quotes), with flights and lodging marked `unknown`.
- **Planning warnings**: Missing weather, out-of-horizon dates, mock data notices, low budget per day (< 50/person/day), and packed long-trip fatigue.

---

## Phase 4 Shared Provider Error Model (`app.providers.errors`)

Phase 4 introduces a unified provider exception hierarchy and classification system:
- **`ProviderError`**: Standardized base exception carrying `code` (`ErrorCode`), `retryable` (`bool`), `safe_message` (`str`), `provider` (`str`), optional `http_status`, optional `retry_after_seconds`, and safe `details`.
- **`ErrorCode`**: Taxonomy of standard error codes:
  - `timeout`: Network socket or request read timeouts (retryable: True).
  - `rate_limited`: HTTP 429 response; retryable if `Retry-After <= 4.0s`.
  - `authentication_failed`: Invalid or missing credentials (HTTP 401/403, retryable: False).
  - `invalid_response`: Malformed JSON or schema validation failures (retryable: False).
  - `invalid_request`: Bad request or client input errors (HTTP 4xx, retryable: False).
  - `unknown_failure`: Upstream 5xx outages (retryable: True) or unexpected errors.
  - *Empty results* are handled as normal return values (`empty_result`), not exceptions.
- **Classification Functions**:
  - `classify_http_error(status, body_hint, headers, provider)`: Uniform HTTP error classification across all provider integrations.
  - `classify_exception(exc, provider)`: Maps Python and library exceptions into typed `ProviderError` instances.
- **Safe Message Sanitization**: Automatic stripping of URLs, query parameters, API keys, headers, and stack traces to ensure zero credential leakage in logs or client envelopes.
- **Centralized ToolResult Mapping**: `provider_error_to_tool_result` in `app.agent.tools.contracts` transforms `ProviderError` into normalized `ToolResult` envelopes in one single place.

---

## Architectural Boundaries

- **Modular Monolith**: All application logic is organized in internal module seams.
- **Strict Boundary**: AI Travel Concierge is strictly a discovery and planning assistant, not a booking engine. No booking, payment, reservation, or ticketing mechanisms are implemented.
