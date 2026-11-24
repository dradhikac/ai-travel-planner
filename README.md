# AI Travel Concierge

AI Travel Concierge is an AI-powered travel research and planning web application that assists travelers in discovering destinations, researching points of interest, calculating travel routes, and organizing itineraries. The application is strictly a travel discovery and planning assistant, **NOT a booking engine**. It never claims to make reservations, execute transactions, process payments, or book flights and accommodations.

**Current Status**: **Phases 1, 2, 3, and 4 Complete (Multi-Tool Reliability v0.4.0)**. The repository includes a production-grade FastAPI backend, a Next.js 16 (React 19) frontend shell, a deterministic itinerary generation engine, meteorological and routing integrations (Open-Meteo, OpenRouteService), a controlled LangGraph agent workflow with multi-tool routing, bounded retries with exponential backoff and jitter, Itinerary Schema v2, deterministic validation rules, bounded repair loops with safe partial fallback, structured JSON event logging, PostgreSQL containerization, and comprehensive regression test suites.

---

## 1. Problem Statement

Travel planning today is tedious, inefficient, and fragmented:
- **Fragmented Workflows**: Travelers juggle dozens of browser tabs across review sites, forums, blogs, map services, and booking engines to piece together an itinerary.
- **Unsupported & Hallucinated Chatbot Answers**: Generic LLM chatbots often invent outdated business hours, fabricate non-existent transport connections, or lack verified citations.
- **High-Pressure Booking Funnels**: Commercial travel apps prioritize aggressive reservation commissions, ads, and urgency nudges over honest, personalized research and exploratory planning.

AI Travel Concierge resolves these issues by providing a structured, verifiable planning workspace powered by specialized workflows that surface actionable, context-aware travel recommendations with provenance tracking, deterministic validation, bounded repair, and transparent failure handling.

---

## 2. Implemented vs. Planned

| Area | Implemented (Phases 1–4) | Planned (Phase 5) |
| :--- | :--- | :--- |
| **Backend Service** | FastAPI application factory, system health (`GET /health`), version metadata (`GET /api/version`), DB readiness (`GET /health/db`), uniform error contract (`{"error": {"code", "message"}}`). | User-scoped queries, versioned snapshot export endpoints. |
| **Agent Orchestration** | Controlled LangGraph state machine (`app/agent/`), typed `TripState`, step-count guard (`MAX_STEPS = 25`), multi-tool routing by intent (`MAX_TOOL_CALLS = 5`), rule-based intent classification (`RuleBasedGateway`), clarification loop for missing parameters. | Optional live LLM provider adapters behind the `ModelGateway` protocol. |
| **Typed Tools** | Three registered tools: `geocode_destination` (Open-Meteo Geocoding), `get_weather` (Open-Meteo Forecast), and `get_route_context` (OpenRouteService with deterministic offline Haversine fallback). | Additional travel domain tools (places search, flight/hotel discovery). |
| **Reliability & Retries** | Bounded retry with exponential backoff and jitter (max 2 retries, 0.5s base, 4.0s max, 8.0s budget). Unified `ProviderError` classification; 401/403/invalid requests abort immediately without retry. | Provider health check circuit breakers and rate-limit quotas. |
| **Itinerary Schema v2** | `ItineraryV2` schema with fine-grained activity IDs, duration estimates (`DurationBasis`), explicit provenance (`RETRIEVED` vs `GENERATED_SUGGESTION`), cost status classification, and non-destructive in-memory v1 upgrader (`upgrade_itinerary_v1_to_v2`). | Versioned itinerary snapshots and history diffing. |
| **Validation & Repair** | 10 deterministic validation rules (date ranges, duplicates, pacing, source metadata, budget floors, non-booking checks). Bounded repair loops (max 2 attempts) with no-progress detection and safe partial fallback (`build_partial_result`). | Interactive user repair prompts and activity re-generation. |
| **Structured Logging** | Single-line structured JSON event logging under `app.events` (`node_start/end`, `tool_call_start/end`, `retry_scheduled`, `repair_start/end`, `validation_result`). Automated credential and URL query redaction; diagnostic runbook (`docs/runbooks/debugging-failures.md`). | OpenTelemetry trace export and cloud log forwarding. |
| **Frontend UI** | Next.js 16 (App Router) + React 19 + Tailwind CSS. Real-time `BackendStatus` indicator, Saved Trips page (`/trips`), Trip Details page (`/trips/[id]`), interactive Assistant page (`/assistant`), and expandable `ToolActivityPanel`. | Markdown/JSON itinerary export views (PDF stretch). |
| **Database & Migrations** | Local PostgreSQL 16 container via Docker Compose, SQLAlchemy 2.0 base and session factory, Alembic baseline revision (`0001_baseline.py`). Optional at runtime (app starts offline without DB). | User profiles, preferences, trip message threads, tool-run metadata models. |
| **Authentication & Users** | Single-user local development mode (no login required). | Multi-user authentication, JWT/OAuth sessions, user-scoped data isolation. |
| **Booking & Commerce** | **Permanently Out of Scope**: Never claims or performs bookings, ticketing, payments, or reservations. | Permanently out of scope. |
| **Testing & Quality** | 516 backend Pytest tests, 29-scenario Phase 4 regression test suite, 14 adversarial QA tests, 85 frontend Vitest component tests, smoke test script, GitHub Actions CI. | End-to-end browser integration tests. |

---

## 3. Architecture

AI Travel Concierge is designed as a **modular monolith** with clean architectural seams between the user-facing web tier, the core API service, and backing data stores:

```text
+---------------------------------------------------------------------------------+
|                                   Web Browser                                   |
+---------------------------------------------------------------------------------+
                                         |
                                HTTP / JSON (Port 3000)
                                         v
+---------------------------------------------------------------------------------+
|                        Frontend (Next.js 16 / React 19)                         |
|  - App Router:                                                                  |
|      * /            -> Home & BackendStatus Health Indicator                    |
|      * /assistant   -> Conversational Travel Planner & ToolActivityPanel        |
|      * /trips       -> Saved Trips List & Trip Details Views                    |
|  - Typed Client Wrappers (src/lib/api/) & Vitest Test Harness                   |
+---------------------------------------------------------------------------------+
                                         |
                             REST API / CORS (Port 8000)
                                         v
+---------------------------------------------------------------------------------+
|                          Backend (FastAPI / Pydantic)                           |
|  - API Route Handlers (app/api/routes/)                                         |
|  - LangGraph State Machine (app/agent/graph.py):                                |
|      [parse_request] -> [check_required_fields] -> [ask_clarification]          |
|      [plan_tool_calls] -> [execute_tools] -> [draft_itinerary]                  |
|      [validate_itinerary] <-> [repair_itinerary] -> [build_partial_result]      |
|      -> [respond]                                                               |
|  - Typed Research Tools (app/agent/tools/):                                     |
|      * geocode_destination (Open-Meteo Geocoding)                               |
|      * get_weather (Open-Meteo Daily Meteorological Forecast)                   |
|      * get_route_context (OpenRouteService with Haversine fallback)              |
|  - Reliability Layer: Bounded Retries, Backoff & Error Classification           |
|  - Deterministic Validation Engine (10 Rules) & Schema v2 Models                |
|  - Structured JSON Event Logging & Redaction (app/core/logging.py)              |
+---------------------------------------------------------------------------------+
                                         |
                       SQLAlchemy / psycopg (Port 5432 / 5433)
                                         v
+---------------------------------------------------------------------------------+
|                       Database (PostgreSQL 16 via Docker)                       |
|  - Container: ai_travel_concierge_db (ai_travel_concierge)                      |
|  - Schema Migrations via Alembic (alembic/)                                     |
+---------------------------------------------------------------------------------+
```

### Repository Layout

```text
ai-travel-concierge/
├── .editorconfig               # Workspace code formatting rules
├── .env.example                # Root environment template (Docker compose database)
├── .gitattributes              # Line-ending normalization rules
├── .gitignore                  # Git tracked file exclusion rules
├── AGENTS.md                   # Agent guidelines, boundaries, and conventions
├── CONTRIBUTING.md             # Solo-developer workflow guidelines
├── README.md                   # Project overview, setup, and documentation
├── docker-compose.yml          # Local PostgreSQL 16 container service
├── .github/
│   └── workflows/
│       └── ci.yml              # GitHub Actions CI pipeline (lint, format, test, regression, build)
├── backend/
│   ├── .dockerignore           # Container build exclusion rules
│   ├── .env.example            # Backend environment template
│   ├── Dockerfile              # Python 3.11-slim container definition
│   ├── pyproject.toml          # Python tool configuration (Ruff, Pytest)
│   ├── requirements.txt        # Production dependencies (FastAPI, LangGraph, etc.)
│   ├── requirements-dev.txt    # Testing dependencies (Pytest, Ruff)
│   ├── alembic/                # Database migrations (0001_baseline.py)
│   ├── app/
│   │   ├── main.py             # FastAPI application factory
│   │   ├── agent/              # LangGraph state machine & typed tools
│   │   │   ├── graph.py        # Graph assembly & run_workflow entrypoint
│   │   │   ├── nodes.py        # Workflow execution nodes, routing, bounded repair
│   │   │   ├── state.py        # Typed TripState schema & secret key validation
│   │   │   ├── gateway.py      # RuleBasedGateway & ModelGateway protocol
│   │   │   ├── validation.py   # Deterministic 10-rule validation engine
│   │   │   ├── partial.py      # Safe partial result fallback synthesizer
│   │   │   └── tools/          # Geocoding, weather, and routing tools
│   │   ├── core/               # Settings, error contracts, retry/backoff, logging
│   │   ├── db/                 # SQLAlchemy session and engine factory
│   │   ├── models/             # Database ORM models
│   │   ├── providers/          # Provider adapters and unified error taxonomy
│   │   ├── schemas/            # Pydantic schemas (TripRequest, ItineraryV2, SourceInfo)
│   │   └── services/           # Itinerary generation and weather services
│   └── tests/                  # Pytest unit, workflow, logging, QA, and regression test suites
│       └── regression/         # 29-case offline deterministic regression test suite
├── frontend/
│   ├── package.json            # Node.js dependencies (Next.js 16, React 19)
│   ├── src/
│   │   ├── app/
│   │   │   ├── page.tsx        # Home page with BackendStatus
│   │   │   ├── assistant/      # Assistant conversational planning page
│   │   │   └── trips/          # Trips list and details views
│   │   ├── components/         # Reusable React components (Navbar, ToolActivityPanel)
│   │   └── lib/                # API client wrappers and TypeScript contracts
│   └── tests/                  # Vitest component and unit test suites
├── docs/                       # Project documentation & architectural records
│   ├── phase2-3/               # Phase 2-3 data contracts and branch plan
│   ├── phase3/                 # Phase 3 architecture & agent workflow specs
│   ├── phase4-5/               # Phase 4 acceptance report, contracts, and branch plan
│   ├── qa/                     # Independent QA verification reports (Phase 1, 3, 4)
│   └── runbooks/               # Diagnostic runbook for failures and structured logs
└── scripts/
    └── smoke_test.py           # Cross-platform service health probe script
```

---

## 4. Quick Start (Windows 11 & Bash)

### Prerequisites
- **Python**: Version `3.11.x`
- **Node.js**: Version `20.x` LTS (with `npm 10.x+`)
- **Git**: Version `2.40+`
- **Docker Desktop** *(Optional)*: Required only if running local PostgreSQL.

---

### Step 1: Clone and Set Up Environment

#### PowerShell (Windows 11):
```powershell
# Clone the repository
git clone https://github.com/dradhikac/ai-travel-concierge.git
Set-Location ai-travel-concierge

# Set up backend virtual environment
Set-Location backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
Set-Location ..

# Set up frontend dependencies
Set-Location frontend
npm ci
Copy-Item .env.example .env.local
Set-Location ..
```

#### Bash Equivalent:
```bash
git clone https://github.com/dradhikac/ai-travel-concierge.git
cd ai-travel-concierge

# Backend setup
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements-dev.txt
cp .env.example .env
cd ..

# Frontend setup
cd frontend
npm ci
cp .env.example .env.local
cd ..
```

---

### Step 2: Start Development Services

#### Backend Service (Runs on http://localhost:8000)
```powershell
# In PowerShell:
Set-Location backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

```bash
# In Bash:
cd backend && ./.venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

#### Frontend Service (Runs on http://localhost:3000)
```powershell
# In a separate terminal:
npm --prefix frontend run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

---

## 5. Walkthrough Demos

### Demo 1: Phase 2 Deterministic Generator
```powershell
# In PowerShell:
Set-Location backend
.\.venv\Scripts\python.exe -c @"
from datetime import date, timedelta
from app.agent.nodes import TripRequest
from app.services.itinerary import generate_itinerary

start = date.today() + timedelta(days=14)
end = start + timedelta(days=3)
request = TripRequest(
    origin='London',
    destination='Tokyo',
    start_date=start,
    end_date=end,
    party_size=2,
    pace='balanced',
    interests=['culture', 'food']
)
itinerary = generate_itinerary(request=request, destination='Tokyo')
print('=== Generated Itinerary ===')
print('Summary:', itinerary.summary)
print('Days:', len(itinerary.days))
for day in itinerary.days:
    print(f'Day {day.day_number} ({day.date}): {len(day.activities)} activities')
    for act in day.activities:
        print(f'  - [{act.time_of_day.upper() if act.time_of_day else "FLEX"}] {act.title} (Provenance: {act.provenance.value})')
"@
Set-Location ..
```

### Demo 2: Phase 3 Conversational Assistant Workflow
```powershell
# In PowerShell:
Set-Location backend
.\.venv\Scripts\python.exe -c @"
from datetime import date, timedelta
from app.agent.graph import run_workflow

start = (date.today() + timedelta(days=14)).isoformat()
end = (date.today() + timedelta(days=17)).isoformat()

# 1. Ambiguous intake -> triggers clarification
s1 = run_workflow('Plan a trip to Rome')
print('[Turn 1] Status:', s1.status.value)
print('[Turn 1] Question:', s1.clarification_question)
print('[Turn 1] Missing:', s1.missing_fields)

# 2. Complete intake -> executes geocoding & weather, drafts itinerary
s2 = run_workflow(f'Plan a 3-day trip from London to Rome from {start} to {end} for 2 people')
print('\n[Turn 2] Status:', s2.status.value)
print('[Turn 2] Tools Run:', len(s2.tool_results))
for a in s2.tool_activity:
    print(f'  * Tool: {a.tool_label} | Status: {a.status} | Source: {a.source}')
if s2.final_response:
    print('[Turn 2] Summary:', s2.final_response.itinerary.summary)

# 3. Non-booking invariant enforcement
s3 = run_workflow('Book a flight from London to Paris and confirm payment')
print('\n[Turn 3] Status:', s3.status.value)
print('[Turn 3] Warning:', s3.warnings[0])
"@
Set-Location ..
```

### Demo 3: Phase 4 Multi-Tool Routing & Schema v2 Upgrader
```powershell
# In PowerShell:
Set-Location backend
.\.venv\Scripts\python.exe -c @"
from app.agent.graph import run_workflow
from app.agent.state import Intent, create_fresh_trip_state

# Run route planning intent (executes destination & endpoint geocoding + route context)
state = create_fresh_trip_state(
    user_message='How do I get from Colosseum to Vatican in Rome?',
    intent=Intent.ROUTE_PLANNING,
    initial_known_fields={'destination': 'Rome', 'route_from': 'Colosseum', 'route_to': 'Vatican'}
)
out = run_workflow(state)
print('[Route Planning] Intent:', out.intent.value)
print('[Route Planning] Status:', out.status.value)
print('[Route Planning] Tools Run:', len(out.tool_results))
for a in out.tool_activity:
    print(f'  * Tool: {a.tool_label} | Status: {a.status}')
"@
Set-Location ..
```

---

## 6. Running Tests & Quality Verification

Execute the test suites locally to verify compliance:

```powershell
# 1. Backend Linting & Formatting
.\backend\.venv\Scripts\python.exe -m ruff check backend
.\backend\.venv\Scripts\python.exe -m ruff format --check backend

# 2. Full Backend Test Suite (516 passing tests)
Set-Location backend; .\.venv\Scripts\python.exe -m pytest -q; Set-Location ..

# 3. Phase 4 Regression Test Suite (29 passing tests across 10 categories)
Set-Location backend; .\.venv\Scripts\python.exe -m pytest tests/regression -q; Set-Location ..

# 4. Independent Adversarial QA Test Suite (14 passing tests)
Set-Location backend; .\.venv\Scripts\python.exe -m pytest tests/test_qa_phase4_reliability.py -v; Set-Location ..

# 5. Backend Dependency Health
.\backend\.venv\Scripts\python.exe -m pip check

# 6. Frontend Lint, Typecheck, and Vitest Tests (85 passing tests)
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend test -- --run

# 7. Frontend Production Compilation
npm --prefix frontend run build

# 8. Service Smoke Test Script
.\backend\.venv\Scripts\python.exe scripts\smoke_test.py --backend-url http://localhost:8000 --frontend-url http://localhost:3000
```

---

## 7. External Providers & Environment Variables

AI Travel Concierge integrates with trusted external data providers behind typed adapters with clear attributions:

| Provider | Purpose | Environment Variable Names | Attribution String | Operating Mode |
| :--- | :--- | :--- | :--- | :--- |
| **Open-Meteo Geocoding** | Place name resolution to coordinates | `OPEN_METEO_GEOCODING_URL`, `OPEN_METEO_CONNECT_TIMEOUT_SECONDS`, `OPEN_METEO_READ_TIMEOUT_SECONDS` | *"Geocoding data by Open-Meteo.com"* | Free / No API key required. |
| **Open-Meteo Forecast** | Daily meteorological summaries | `OPEN_METEO_FORECAST_URL`, `OPEN_METEO_MAX_RETRIES` | *"Weather data by Open-Meteo.com"* | Free / No API key required. |
| **OpenRouteService** | Route distances and transit context | `OPENROUTESERVICE_API_KEY`, `OPENROUTESERVICE_BASE_URL`, `OPENROUTESERVICE_TIMEOUT_SECONDS`, `ROUTING_PROVIDER_MODE` | *"Routing data © OpenStreetMap contributors"* | Defaults to `ROUTING_PROVIDER_MODE="mock"` with deterministic Haversine calculations. |
| **Optional LLM Gateway** | Optional repair assistance | `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL` | Provider-specific attribution | Defaults to `LLM_PROVIDER="none"` (RuleBasedGateway active; zero inference costs). |

---

## 8. Honest Limitations & Operational Boundaries

1. **Discovery & Planning Only (NOT a Booking Engine)**: The system strictly organizes travel plans and does not book flights, reserve hotel rooms, purchase transit passes, or process payments.
2. **Forecast Horizon (16 Days)**: Open-Meteo provides deterministic numerical forecasts up to 16 days in advance. Requests for dates further than 16 days out gracefully degrade to `PARTIAL` status with an explanatory notice.
3. **Curated POI Suggestions**: Points of interest are selected from deterministic rule-based heuristics matched to traveler pace and interests rather than live ticket inventory.
4. **Single-User Local Mode**: The application runs without user authentication or multi-tenant database partitioning.
5. **Deterministic Rule Gateway**: LangGraph state routing utilizes the built-in `RuleBasedGateway`, eliminating unpredictable model hallucinations and external API key costs.
6. **Docker Offline Mode**: Local PostgreSQL containerization is optional; when Docker is offline or `DATABASE_URL` is unset, database integration tests skip cleanly and the app operates in offline mode.
7. **Next.js Version Advisory**: Frontend build notes an advisory recommendation for Next.js security upgrade (`next upgrade --agent=security`).

---

## 9. Roadmap

- [x] **Phase 1: Project Foundation**
  - Scaffolding, engineering conventions, modular monolith seams.
  - FastAPI health, version, and database readiness endpoints.
  - Next.js application shell with real-time health indicator.
  - PostgreSQL containerization and Alembic baseline migrations.
- [x] **Phase 2: Deterministic Engine & Live Provider**
  - Validated trip intake schema (`TripRequest`).
  - Open-Meteo geocoding and weather provider adapter with offline fixtures.
  - Deterministic day-by-day itinerary generator with strict provenance tracking.
  - Results and saved trips user interfaces (`/trips`, `/trips/[id]`).
- [x] **Phase 3: Controlled LangGraph Workflow & Assistant UI**
  - Typed `TripState` state machine with pure nodes and step guards (`MAX_STEPS = 25`).
  - Typed tools (`geocode_destination`, `get_weather`).
  - Safe clarification loop and default preference policies.
  - Interactive Assistant UI (`/assistant`) with real-time `ToolActivityPanel`.
  - Comprehensive adversarial robustness test suite.
- [x] **Phase 4: Multi-Tool Reliability & Validation**
  - Third tool: route context (`get_route_context` with OpenRouteService and Haversine fallback).
  - Unified `ProviderError` classification and bounded retry with backoff and jitter.
  - Structured Itinerary Schema v2 and non-destructive upgrader.
  - Deterministic 10-rule validation catalog and bounded repair loops.
  - Safe partial result degradation (`build_partial_result`).
  - Structured JSON event logging under `app.events` and failure debugging runbook.
  - 29-case offline regression test suite running locally and in CI.
- [ ] **Phase 5: Travel Domain Integrations & Durable Data** *(Planned)*
  - Adapter interfaces for all travel providers (source name, timeout, fetched_at, typed error contract).
  - Four or more tools (optional flight/hotel discovery where access permits, not blocking).
  - PostgreSQL models for users, preferences, trips, messages, itinerary versions, and tool runs.
  - User-scoped queries and versioned itinerary snapshots.
  - Markdown/JSON export capabilities.

---

## 10. Contributing & Licensing

- **Contributing**: Please review [CONTRIBUTING.md](CONTRIBUTING.md) for branch management rules, conventional commit formatting, and quality checklists.
- **Licensing**: No open source or commercial license has been selected for this project yet. All rights are reserved. Do not add license headers to repository files.
