# AI Travel Concierge

AI Travel Concierge is an AI-powered travel research and planning web application that assists travelers in discovering destinations, researching points of interest, and organizing itineraries. The application is strictly a travel discovery and planning assistant, **NOT a booking engine**. It never claims to make reservations, execute transactions, process payments, or book flights and accommodations.

**Current Status**: **Phase 1 Foundation Complete**. Phase 1 establishes the production-grade application scaffolding, backend FastAPI service, frontend Next.js application shell, optional containerized PostgreSQL with Alembic migrations, test suites, and GitHub Actions CI. Phase 2 (LLM orchestration and travel integrations) is planned.

---

## 1. Problem Statement

Travel planning today is tedious, inefficient, and fragmented:
- **Fragmented Workflows**: Travelers juggle dozens of browser tabs across review sites, forums, blogs, map services, and booking engines to piece together an itinerary.
- **Unsupported & Hallucinated Chatbot Answers**: Generic LLM chatbots often invent outdated business hours, fabricate non-existent transport connections, or lack verified citations.
- **High-Pressure Booking Funnels**: Most commercial travel apps prioritize aggressive reservation commissions, ads, and urgency nudges over honest, personalized research and exploratory planning.

AI Travel Concierge aims to resolve these issues by providing a structured, verifiable planning workspace powered by specialized agents that surface actionable, context-aware travel recommendations without sales gimmicks.

---

## 2. Implemented in Phase 1 vs. Planned

| Area | Implemented in Phase 1 (Foundation) | Planned (Future Phases) |
| :--- | :--- | :--- |
| **Backend Service** | FastAPI application factory, system health (`GET /health`), version metadata (`GET /api/version`), DB readiness (`GET /health/db`), uniform error contract (`{"error": {"code", "message"}}`). | LangGraph / LangChain agent orchestration, dynamic tool calling, LLM inference endpoints. |
| **Frontend UI** | Next.js 16 (App Router) + React 19 shell, Tailwind CSS styling, real-time `BackendStatus` indicator with offline recovery and accessible states. | Interactive map exploration, itinerary drag-and-drop builder, chat interface, multi-turn travel research assistant. |
| **Database & Migrations** | Local PostgreSQL 16 container via Docker Compose, SQLAlchemy 2.0 base and session factory, Alembic 1.14 baseline revision (`0001_baseline`). Optional at runtime (app starts without DB). | Domain models (trips, destinations, points of interest, user profiles), saved itinerary persistence. |
| **External Travel APIs** | None (tests use deterministic mocks; zero network egress). | Amadeus, Google Places, TripAdvisor, Skyscanner, or weather APIs. |
| **Booking & Commerce** | **Explicitly Out of Scope**: Never claims or performs bookings, ticketing, payments, or reservations. | Out of scope permanently. |
| **Quality & Automation** | Pytest unit and CORS integration tests, Vitest component test harness, standalone smoke test script, GitHub Actions CI workflow. | End-to-end Playwright tests, automated staging deployments, performance benchmarking. |

---

## 3. Architecture

AI Travel Concierge is designed as a **modular monolith** with clean architectural seams between the user-facing web tier, the core API service, and backing data stores:

```text
+-----------------------------------------------------------+
|                       Web Browser                         |
+-----------------------------------------------------------+
                             |
                   HTTP / JSON (Port 3000)
                             v
+-----------------------------------------------------------+
|              Frontend (Next.js 16 / React 19)             |
|  - App Router (src/app/)                                  |
|  - Typed API Client Wrapper (src/lib/api/client.ts)       |
|  - BackendStatus Component (src/components/BackendStatus) |
+-----------------------------------------------------------+
                             |
             REST API / CORS (Port 8000)
                             v
+-----------------------------------------------------------+
|               Backend (FastAPI / Pydantic)                |
|  - Application Factory & Routes (app/api/routes/)         |
|  - Typed Settings & Error Contract (app/core/)            |
|  - Lazy SQLAlchemy Engine & Session (app/db/)             |
+-----------------------------------------------------------+
                             |
         SQLAlchemy / psycopg (Port 5432 / 5433)
                             v
+-----------------------------------------------------------+
|           Database (PostgreSQL 16 via Docker)             |
|  - Container: ai_travel_concierge_db                      |
|  - Schema Migrations via Alembic                          |
+-----------------------------------------------------------+
```

### Repository Layout

The actual tracked repository structure (derived from `git ls-files`):

```text
ai-travel-concierge/
├── .editorconfig               # Workspace code formatting rules
├── .env.example                # Root environment template (Docker compose database)
├── .gitattributes              # Line-ending and Git attributes normalization
├── .gitignore                  # Git tracked file exclusion rules
├── AGENTS.md                   # Agent guidelines, boundaries, and rules
├── CONTRIBUTING.md             # Solo-developer workflow guidelines
├── README.md                   # Project overview, setup, and documentation
├── docker-compose.yml          # Local PostgreSQL 16 container service
├── .github/
│   └── workflows/
│       └── ci.yml              # GitHub Actions CI pipeline (backend, frontend, hygiene)
├── backend/
│   ├── .env.example            # Backend environment template
│   ├── README.md               # Backend-specific architecture and setup guide
│   ├── alembic.ini             # Alembic configuration (no credentials)
│   ├── pyproject.toml          # Python tool configuration (Ruff, Pytest)
│   ├── requirements.txt        # Production Python dependencies
│   ├── requirements-dev.txt    # Development and testing Python dependencies
│   ├── alembic/
│   │   ├── env.py              # Dynamic migration runner reading application settings
│   │   ├── script.py.mako      # Alembic migration script template
│   │   └── versions/
│   │       └── 0001_baseline.py# Initial empty baseline revision
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py             # FastAPI application factory and lifespan handler
│   │   ├── version.py          # Application semantic version constant
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   └── routes/
│   │   │       ├── __init__.py
│   │   │       ├── health.py   # Health and database readiness endpoints
│   │   │       └── version.py  # Version metadata endpoint
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── config.py       # Pydantic Settings configuration loader
│   │   │   ├── errors.py       # Global exception handlers and error contracts
│   │   │   └── logging.py      # Structured application logging configuration
│   │   ├── db/
│   │   │   ├── __init__.py
│   │   │   ├── base.py         # DeclarativeBase SQLAlchemy model base
│   │   │   └── session.py      # Lazy engine and get_session FastAPI dependency
│   │   └── schemas/
│   │       ├── __init__.py
│   │       ├── errors.py       # Pydantic error response contract schemas
│   │       ├── health.py       # Pydantic health check schemas
│   │       └── version.py      # Pydantic version response schemas
│   └── tests/
│       ├── conftest.py         # Test fixtures and shared client factories
│       ├── test_config.py      # Settings and environment validation tests
│       ├── test_db_health.py   # Database readiness and connection probe tests
│       ├── test_error_contract.py# JSON error shape contract verification tests
│       ├── test_errors.py      # Specific error handler unit tests
│       ├── test_health.py      # Health route unit tests
│       ├── test_integration_cors.py # CORS header reflection and rejection tests
│       └── test_version.py     # Version route unit tests
├── docs/
│   ├── README.md               # Documentation directory index
│   ├── architecture.md         # Architecture overview and design seams
│   ├── environment.md          # Exhaustive environment variable specification
│   ├── local-development.md    # Comprehensive local developer manual
│   ├── testing.md              # Testing guide, smoke testing, and QA checklists
│   └── decisions/
│       └── 0001-phase1-stack.md# Architecture Decision Record: Phase 1 tech stack
├── frontend/
│   ├── .env.example            # Frontend environment template
│   ├── AGENTS.md               # Frontend-specific engineering conventions
│   ├── README.md               # Frontend setup and architecture guide
│   ├── eslint.config.mjs       # ESLint 9 configuration
│   ├── next.config.ts          # Next.js 16 configuration
│   ├── package.json            # Node.js dependencies and script definitions
│   ├── package-lock.json       # Deterministic npm dependency lockfile
│   ├── tsconfig.json           # TypeScript strict configuration
│   ├── vitest.config.ts        # Vitest test runner configuration
│   ├── src/
│   │   ├── app/
│   │   │   ├── favicon.ico
│   │   │   ├── globals.css     # Global styles and Tailwind CSS directives
│   │   │   ├── layout.tsx      # Root HTML layout and metadata
│   │   │   └── page.tsx        # Landing page rendering BackendStatus card
│   │   ├── components/
│   │   │   └── BackendStatus.tsx# Real-time backend status component
│   │   └── lib/
│   │       ├── config.ts       # Typed frontend configuration module
│   │       └── api/
│   │           ├── client.ts   # Robust fetch wrapper with timeout and error classification
│   │           └── health.ts   # Typed API health/version query functions
│   └── tests/
│       ├── setup.ts            # Vitest DOM matchers and mock lifecycle setup
│       ├── components/
│       │   └── BackendStatus.test.tsx # UI component states and retry tests
│       └── lib/
│           ├── client.test.ts  # HTTP client error handling and timeout tests
│           ├── config.test.ts  # Client environment configuration tests
│           └── health.test.ts  # API response runtime schema validation tests
└── scripts/
    └── smoke_test.py           # Dependency-free live HTTP endpoint probing script
```

---

## 4. Technology Stack & Selected Versions

The repository pins current stable, compatible-release versions across all layers:

- **Backend**:
  - Python `3.11` (specifically `3.11.9`)
  - FastAPI `~=0.146.0`
  - Uvicorn `~=0.54.0` (standard extra)
  - Pydantic Settings `~=2.16.0`
  - SQLAlchemy `~=2.0.55`
  - Psycopg `~=3.2.13` (binary extra)
  - Alembic `~=1.14.1`
  - Pytest `~=9.1.1`
  - HTTPX `~=0.28.1`
  - Ruff `~=0.17.1`
- **Frontend**:
  - Node.js `20` (`v20.18.0` LTS)
  - npm `10.8.2`
  - Next.js `16.4.2` (App Router)
  - React `19.3.0` & React DOM `19.3.0`
  - TypeScript `^5` (`5.9.3`)
  - Vitest `~=3.2.7`
  - Testing Library React `~=16.3.3`
  - Tailwind CSS `^4`
- **Database & Containerization**:
  - PostgreSQL `16-alpine`
  - Docker Compose v2

---

## 5. Prerequisites

Before setting up the project locally, ensure you have the following installed:
- **Operating System**: Windows 11 (PowerShell 5.1/7 primary) or macOS / Linux (Bash)
- **Python**: `3.11` (verified with `3.11.9`; accessible via `py -3.11` or `python3.11`)
- **Node.js**: `20` LTS (verified with `v20.18.0`; includes `npm`)
- **Git**: Modern Git client
- **Docker & Docker Compose**: (Optional for basic development; required only when running the local PostgreSQL container)

---

## 6. Quick Start

Follow these steps to run the complete AI Travel Concierge application locally.

### Windows 11 (PowerShell)

```powershell
# 1. Clone the repository
git clone https://github.com/dradhikac/ai-travel-concierge.git
Set-Location ai-travel-concierge

# 2. Set up Backend
Set-Location backend
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
# Start the backend server (runs at http://localhost:8000)
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

In a second PowerShell window:
```powershell
Set-Location ai-travel-concierge

# 3. Set up Frontend
Set-Location frontend
npm ci
Copy-Item .env.example .env.local
# Start the Next.js development server (runs at http://localhost:3000)
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your web browser. You will see the **Connected to Backend Service** status card displaying service health and API version metadata.

#### Optional: Start Local PostgreSQL & Run Database Migrations
```powershell
# From the repository root:
Copy-Item .env.example .env
docker compose up -d db

# Update backend/.env with DATABASE_URL (adjust port if 5432 is occupied):
# DATABASE_URL=postgresql+psycopg://postgres:change-me-local-only@127.0.0.1:5433/ai_travel_concierge

# Run Alembic migrations:
Set-Location backend
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
```

---

### macOS / Linux (Bash)

```bash
# 1. Clone the repository
git clone https://github.com/dradhikac/ai-travel-concierge.git
cd ai-travel-concierge

# 2. Set up Backend
cd backend
python3.11 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements-dev.txt
cp .env.example .env
# Start the backend server (runs at http://localhost:8000)
./.venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

In a second terminal window:
```bash
cd ai-travel-concierge

# 3. Set up Frontend
cd frontend
npm ci
cp .env.example .env.local
# Start the Next.js development server (runs at http://localhost:3000)
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

#### Optional: Start Local PostgreSQL & Run Database Migrations
```bash
# From repository root:
cp .env.example .env
docker compose up -d db

# In backend/.env:
# DATABASE_URL=postgresql+psycopg://postgres:change-me-local-only@127.0.0.1:5432/ai_travel_concierge

cd backend
./.venv/bin/python -m alembic upgrade head
./.venv/bin/python -m alembic current
```

---

## 7. Environment Variables

Environment variables are isolated across service boundaries. Never commit actual `.env` files.

| File Path | Variable Name | Required | Default Value | Description |
| :--- | :--- | :---: | :--- | :--- |
| `/.env` | `POSTGRES_USER` | Yes (for Docker) | `postgres` | Superuser username for local database container. |
| `/.env` | `POSTGRES_PASSWORD` | Yes (for Docker) | `change-me-local-only` | Superuser password for local database container. |
| `/.env` | `POSTGRES_DB` | Yes (for Docker) | `ai_travel_concierge` | Default database name. |
| `/.env` | `POSTGRES_PORT` | No | `5432` (or `5433` if occupied)| Host port mapped to PostgreSQL container port 5432. |
| `backend/.env` | `APP_ENV` | No | `development` | Runtime environment (`development`, `test`, `production`). |
| `backend/.env` | `CORS_ORIGINS` | No | `["http://localhost:3000", ...]` | Allowed CORS origins (JSON array or comma-separated string). |
| `backend/.env` | `DATABASE_URL` | No | `None` | SQLAlchemy connection string (`postgresql+psycopg://...`). Unset by default. |
| `frontend/.env.local`| `NEXT_PUBLIC_API_BASE_URL` | No | `http://localhost:8000` | Backend base URL for browser and server fetches. |

For exhaustive documentation and formatting rules, refer to [docs/environment.md](docs/environment.md).

---

## 8. Running Tests and Verification Checks

### Backend Checks (Ruff & Pytest)

```powershell
# PowerShell
Set-Location backend
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pytest -q
Set-Location ..
```

```bash
# Bash
cd backend
./.venv/bin/python -m ruff check .
./.venv/bin/python -m ruff format --check .
./.venv/bin/python -m pytest -q
cd ..
```

*Note*: Default `pytest` runs entirely offline and requires no live database (database sessions are mocked; integration tests marked `@pytest.mark.integration` automatically skip when `DATABASE_URL` is unset).

### Frontend Checks (ESLint, TypeScript, Vitest, Build)

```powershell
# PowerShell
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend run test
npm --prefix frontend run build
```

```bash
# Bash
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend run test
npm --prefix frontend run build
```

### End-to-End Smoke Test Script

When services are running locally, execute the standalone Python standard-library probe script:
```powershell
# Probe local backend only (http://localhost:8000)
.\backend\.venv\Scripts\python.exe scripts\smoke_test.py --backend-url http://localhost:8000

# Probe both backend and frontend
.\backend\.venv\Scripts\python.exe scripts\smoke_test.py --backend-url http://localhost:8000 --frontend-url http://localhost:3000
```

Detailed test workflows and manual QA checklists are documented in [docs/testing.md](docs/testing.md).

---

## 9. Continuous Integration (CI)

Automated continuous integration is defined in [.github/workflows/ci.yml](.github/workflows/ci.yml).
- **Triggers**: Automated runs on `push` to `main` and `develop`, `pull_request` targeting `main` and `develop`, and manual trigger via `workflow_dispatch`.
- **Permissions**: Minimum privileges (`permissions: contents: read`). No secrets or write tokens are configured.
- **Concurrency**: Per-ref cancellation (`cancel-in-progress: true`).
- **Jobs**:
  1. `backend`: Sets up Python 3.11 with pip caching, installs `requirements-dev.txt`, runs `ruff check .`, `ruff format --check .`, and executes `pytest -q`.
  2. `frontend`: Sets up Node.js 20 with npm caching, installs dependencies via `npm ci`, runs `npm run lint`, `npm run typecheck`, `npm run test`, and validates production compilation via `npm run build`.
  3. `repo-hygiene`: Enforces that no `.env` files outside `.env.example` are committed and scans for accidental private keys or secret token patterns.

*Note on Status Badges*: No CI status badge is included in this README because the workflow has been verified locally and a remote GitHub Actions execution has not yet run.

---

## 10. Troubleshooting

### 1. PowerShell Script Execution Policy Blocks venv Activation
- **Symptom**: `.\.venv\Scripts\Activate.ps1 cannot be loaded because running scripts is disabled on this system.`
- **Resolution**: Open PowerShell and run:
  ```powershell
  Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
  ```
  Alternatively, invoke the virtual environment's Python binary directly without activation (e.g. `.\.venv\Scripts\python.exe -m uvicorn ...`).

### 2. Port Conflicts (3000, 8000, or 5432 in Use)
- **Port 8000 (Backend)**: If another application occupies port 8000, run Uvicorn on an alternate port:
  ```powershell
  python -m uvicorn app.main:app --reload --port 8001
  ```
  Remember to set `NEXT_PUBLIC_API_BASE_URL=http://localhost:8001` in `frontend/.env.local`.
- **Port 3000 (Frontend)**: Next.js will automatically offer to run on port 3001 if 3000 is occupied, or specify `npm run dev -- -p 3001`.
- **Port 5432 (PostgreSQL)**: If a host PostgreSQL instance occupies port 5432, update `POSTGRES_PORT` in your root `.env` to `5433`:
  ```env
  POSTGRES_PORT=5433
  ```
  Then run `docker compose up -d db` and set `DATABASE_URL=postgresql+psycopg://postgres:change-me-local-only@127.0.0.1:5433/ai_travel_concierge` in `backend/.env`.

### 3. Cross-Origin Resource Sharing (CORS) Errors
- **Symptom**: Browser console indicates `CORS policy: No 'Access-Control-Allow-Origin' header is present`.
- **Resolution**: Ensure `CORS_ORIGINS` in `backend/.env` contains your exact frontend origin:
  ```env
  CORS_ORIGINS=["http://localhost:3000"]
  ```

### 4. Wrong Python or Node.js Versions
- **Symptom**: Incompatible syntax errors or module loading failures.
- **Resolution**: Verify versions with `python --version` (requires Python `3.11.x`) and `node --version` (requires Node.js `20.x`). On Windows with multiple Python versions installed, invoke the `py` launcher: `py -3.11 -m venv .venv`.

### 5. `npm ci` Fails Due to Lockfile Desynchronization
- **Symptom**: `npm error code EUSAGE` or `npm ci can only install with an existing package-lock.json`.
- **Resolution**: Do not modify `package-lock.json` manually. Ensure you run `npm ci` from within the `frontend/` directory (or use `npm --prefix frontend ci`).

### 6. Docker Desktop Not Running
- **Symptom**: `failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine`.
- **Resolution**: Launch Docker Desktop and wait until the engine status shows "Engine running" before executing `docker compose up -d db`.

### 7. Database Data Loss from `docker compose down -v`
- **Caution**: **NEVER run `docker compose down -v`**.
- The `-v` flag permanently removes named Docker volumes (`postgres_data`), deleting all local database tables and migration records. Always run `docker compose down` (without `-v`) to preserve data between development sessions.

---

## 11. Roadmap

- [x] **Phase 1: Project Foundation**
  - Scaffolding, engineering conventions, modular monolith seams.
  - FastAPI health, version, and database readiness endpoints with standard error handling.
  - Next.js application shell with real-time health indicator and offline recovery.
  - PostgreSQL containerization and Alembic baseline migrations.
  - Comprehensive unit, integration, and CI validation pipelines.
- [ ] **Phase 2: Agent Orchestration & Core Workflows** *(Planned)*
  - LangGraph workflow definition and state management.
  - Destination research and point-of-interest discovery tool definitions.
  - Structured output validation and citation tracking.
- [ ] **Phase 3: Live Travel Integrations & Curation** *(Planned)*
  - Live external API integrations (places, activities, transit overviews).
  - Rate limiting, fallback handling, and deterministic caching.
- [ ] **Phase 4: Trip Organizer & User Persistence** *(Planned)*
  - User-driven itinerary organization and notes.
  - Database persistence for trips and curated spots.

---

## 12. Contributing & Licensing

- **Contributing**: Please review [CONTRIBUTING.md](CONTRIBUTING.md) for branch management rules, conventional commit formatting, and quality checklists.
- **Licensing**: No open source or commercial license has been selected for this project yet. All rights are reserved. Do not add license files or license headers to repository files.
