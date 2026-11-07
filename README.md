# AI Travel Concierge

AI Travel Concierge is an AI-powered travel research and planning web application that assists travelers in discovering destinations, researching points of interest, and organizing itineraries. The application is strictly a travel discovery and planning assistant, **NOT a booking engine**. It never claims to make reservations, execute transactions, process payments, or book flights and accommodations.

**Current Status**: **Phase 1, Phase 2, and Phase 3 Complete (Release Candidate v0.3.0-rc1)**. The repository includes a production-grade FastAPI backend, a Next.js 16 (React 19) frontend shell, a deterministic itinerary generation engine with Open-Meteo meteorological integration, a controlled LangGraph agent workflow with typed state and clarification loops, an interactive Assistant UI with tool activity audits, PostgreSQL containerization, and comprehensive automated test suites.

---

## 1. Problem Statement

Travel planning today is tedious, inefficient, and fragmented:
- **Fragmented Workflows**: Travelers juggle dozens of browser tabs across review sites, forums, blogs, map services, and booking engines to piece together an itinerary.
- **Unsupported & Hallucinated Chatbot Answers**: Generic LLM chatbots often invent outdated business hours, fabricate non-existent transport connections, or lack verified citations.
- **High-Pressure Booking Funnels**: Most commercial travel apps prioritize aggressive reservation commissions, ads, and urgency nudges over honest, personalized research and exploratory planning.

AI Travel Concierge resolves these issues by providing a structured, verifiable planning workspace powered by specialized workflows that surface actionable, context-aware travel recommendations with provenance tracking and transparent failure handling.

---

## 2. Implemented vs. Planned

| Area | Implemented (Phases 1–3) | Planned (Future Phases) |
| :--- | :--- | :--- |
| **Backend Service** | FastAPI application factory, system health (`GET /health`), version metadata (`GET /api/version`), DB readiness (`GET /health/db`), uniform error contract (`{"error": {"code", "message"}}`). | Multi-destination routing endpoints, user-specific trip sharing. |
| **Agent Orchestration** | Controlled LangGraph state machine (`app/agent/`), typed `TripState`, step-count guard (`MAX_STEPS = 25`), sequential execution limits (`MAX_TOOL_CALLS = 5`), rule-based intent classification (`RuleBasedGateway`), clarification loop for missing parameters. | Optional live LLM provider adapters (Anthropic Claude, OpenAI, Gemini) behind the `ModelGateway` protocol. |
| **Typed Tools** | `geocode_destination` (resolves coordinates, timezone, admin region) and `get_weather` (daily meteorological summaries). Resilient offline fixtures, sanitized URLs, and timeout/rate-limit policies. | Live points-of-interest search, transit scheduling, route elevation profiles. |
| **Itinerary Generator** | Deterministic rule-based day-by-day generator (`app/services/itinerary.py`), pacing matching (relaxed, balanced, packed), interests matching, daily weather integration, and strict provenance tagging (`RETRIEVED` vs `SYNTHESIZED`). | Drag-and-drop manual itinerary reordering, user notes persistence. |
| **Frontend UI** | Next.js 16 (App Router) + React 19 + Tailwind CSS. Real-time `BackendStatus` indicator, Saved Trips page (`/trips`), Trip Details page (`/trips/[id]`), interactive Assistant page (`/assistant`), and expandable `ToolActivityPanel`. | Interactive Leaflet/Mapbox destination maps, dark/light theme toggle. |
| **Database & Migrations** | Local PostgreSQL 16 container via Docker Compose, SQLAlchemy 2.0 base and session factory, Alembic baseline revision (`0001_baseline.py`). Optional at runtime (app starts offline without DB). | Production managed PostgreSQL deployment, automated backup schedules. |
| **Authentication & Users** | Single-user local development mode (no login required). | Multi-user authentication, JWT/OAuth sessions, user profiles. |
| **Booking & Commerce** | **Permanently Out of Scope**: Never claims or performs bookings, ticketing, payments, or reservations. | Permanently out of scope. |
| **Testing & Quality** | 257 backend Pytest tests (including 24 adversarial robustness tests), 83 frontend Vitest component tests, standalone smoke test script, GitHub Actions CI. | End-to-end Playwright tests against live browser instances. |

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
|      [plan_tool_calls] -> [execute_tools] -> [draft_itinerary] -> [respond]     |
|  - Typed Research Tools (app/agent/tools/):                                     |
|      * geocode_destination (Open-Meteo Geocoding)                               |
|      * get_weather (Open-Meteo Daily Meteorological Forecast)                   |
|  - Deterministic Itinerary Engine (app/services/itinerary.py)                   |
|  - Error Contract & Logging Redaction (app/core/)                               |
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
│       └── ci.yml              # GitHub Actions CI pipeline
├── backend/
│   ├── .dockerignore           # Container build exclusion rules
│   ├── .env.example            # Backend environment template
│   ├── Dockerfile              # Python 3.11-slim container definition
│   ├── pyproject.toml          # Python tool configuration (Ruff, Pytest)
│   ├── requirements.txt        # Production dependencies (FastAPI, LangGraph, etc.)
│   ├── requirements-dev.txt    # Testing dependencies (Pytest, Ruff)
│   ├── alembic/                # Database migrations
│   ├── app/
│   │   ├── main.py             # FastAPI application factory
│   │   ├── agent/              # LangGraph state machine & typed tools
│   │   │   ├── graph.py        # Graph assembly & run_workflow entrypoint
│   │   │   ├── nodes.py        # Pure workflow execution nodes & step guards
│   │   │   ├── state.py        # Typed TripState schema & secret key validation
│   │   │   ├── gateway.py      # RuleBasedGateway & ModelGateway protocol
│   │   │   └── tools/          # Typed geocoding and weather tools
│   │   ├── core/               # Typed settings, error contracts, logging
│   │   ├── db/                 # SQLAlchemy session and engine factory
│   │   ├── schemas/            # Pydantic schemas (TripRequest, Itinerary, SourceInfo)
│   │   └── services/           # Deterministic itinerary generator & weather adapter
│   └── tests/                  # Pytest unit, workflow, and adversarial test suites
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
│   ├── qa/                     # Independent QA verification reports
│   └── release/                # Release candidate reports
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

Demonstrates programmatic itinerary generation using the deterministic rule-based engine:

```powershell
# In PowerShell from repository root:
.\backend\.venv\Scripts\python.exe -c @"
from datetime import date
from app.schemas.trip import TripRequest
from app.services.itinerary import generate_itinerary

request = TripRequest(
    origin='London',
    destination='Tokyo',
    start_date=date(2026, 11, 10),
    end_date=date(2026, 11, 13),
    party_size=2,
    pace='balanced',
    interests=['culture', 'food']
)
itinerary = generate_itinerary(request=request, destination='Tokyo')
print('=== Generated Itinerary ===')
print('Summary:', itinerary.summary)
print('Days:', len(itinerary.days))
for day in itinerary.days:
    print(f'Day {day.day_number} ({day.date}): {len(day.items)} activities')
    for item in day.items:
        print(f'  - [{item.time_of_day.upper()}] {item.title} (Provenance: {item.provenance.value})')
"@
```

### Demo 2: Phase 3 Conversational Assistant Workflow

Demonstrates the LangGraph agent state machine handling clarification, tool execution, and partial degradation:

```powershell
# In PowerShell from repository root:
.\backend\.venv\Scripts\python.exe -c @"
from app.agent.graph import run_workflow

# 1. Ambiguous intake -> triggers clarification
s1 = run_workflow('Plan a trip to Rome')
print('[Turn 1] Status:', s1.status.value)
print('[Turn 1] Question:', s1.clarification_question)
print('[Turn 1] Missing:', s1.missing_fields)

# 2. Complete intake -> executes geocoding & weather, drafts itinerary
s2 = run_workflow('Plan a 3-day trip from London to Rome from 2026-11-10 to 2026-11-13 for 2 people')
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
```

---

## 6. Running Tests & Quality Verification

Execute the test suites locally to verify compliance:

```powershell
# 1. Backend Linting & Formatting
.\backend\.venv\Scripts\python.exe -m ruff check backend
.\backend\.venv\Scripts\python.exe -m ruff format --check backend

# 2. Backend Unit & Adversarial Tests (257 passing tests)
.\backend\.venv\Scripts\python.exe -m pytest -o pythonpath=backend -q backend\tests

# 3. Backend Dependency Health
.\backend\.venv\Scripts\python.exe -m pip check

# 4. Frontend Lint, Typecheck, and Vitest Tests (83 passing tests)
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend run test

# 5. Frontend Production Compilation
npm --prefix frontend run build

# 6. Service Smoke Test Script
.\backend\.venv\Scripts\python.exe scripts\smoke_test.py --backend-url http://localhost:8000 --frontend-url http://localhost:3000
```

---

## 7. External Provider Attribution

AI Travel Concierge integrates with Open-Meteo for meteorological data:
- **Provider**: [Open-Meteo](https://open-meteo.com/)
- **License**: Weather and geocoding data by Open-Meteo.com under [Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/).
- **Attribution Policy**: All meteorological summaries and geocoded locations display explicit attribution badges (`Open-Meteo`) and sanitized source links in the UI.

---

## 8. Honest Limitations & Operational Boundaries

1. **Discovery & Planning Only (NOT a Booking Engine)**: The system strictly organizes travel plans and does not book flights, reserve hotel rooms, purchase transit passes, or process payments.
2. **Forecast Horizon (16 Days)**: Open-Meteo provides deterministic numerical forecasts up to 16 days in advance. Requests for dates further than 16 days out gracefully degrade to `PARTIAL` status with an explanatory notice.
3. **Curated POI Suggestions**: Points of interest are selected from deterministic rule-based heuristics matched to traveler pace and interests rather than live ticket inventory.
4. **Single-User Local Mode**: The application runs without user authentication or multi-tenant database partitioning.
5. **Deterministic Rule Gateway**: LangGraph state routing utilizes the built-in `RuleBasedGateway`, eliminating unpredictable model hallucinations and external API key costs.

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
  - Narrow typed tools (`geocode_destination`, `get_weather`) with sequential caps (`MAX_TOOL_CALLS = 5`).
  - Safe clarification loop and default preference policies.
  - Interactive Assistant UI (`/assistant`) with real-time `ToolActivityPanel`.
  - Comprehensive adversarial robustness test suite.
- [ ] **Phase 4: Multi-Turn Memory & User Accounts** *(Planned)*
  - User session authentication and persistent user trip profiles.
  - Optional multi-provider travel recommendations (transit, walking routes).
  - Multi-destination trip graph connections.

---

## 10. Contributing & Licensing

- **Contributing**: Please review [CONTRIBUTING.md](CONTRIBUTING.md) for branch management rules, conventional commit formatting, and quality checklists.
- **Licensing**: No open source or commercial license has been selected for this project yet. All rights are reserved. Do not add license headers to repository files.
