# Phase 2 & Phase 3 Branch Plan

This document defines the Git branching model, integration baseline, retention policy for existing Phase 1 branches, planned branches for Phase 2 and Phase 3, merge order, and independent QA verification protocol for AI Travel Concierge.

---

## 1. Integration Baseline

- **Primary Integration Base**: `develop`
- **Current Integration Commit**: `f91e7bd1e658a2d1e0394334f59040776bdf2d30` (`Merge pull request #14 from dradhikac/docs/phase1-release-notes`)
- **Baseline Verification**: The base contains the complete, verified Phase 1 foundation:
  - Repository structure, engineering conventions, and EditorConfig
  - Backend FastAPI scaffolding with `/health`, `/api/version`, `/health/db`, and centralized error handlers
  - Frontend Next.js 16 + React 19 shell with typed API client and accessible `BackendStatus` component
  - Containerization (`docker-compose.yml` for PostgreSQL 16, production `Dockerfile`s for backend and frontend)
  - SQLAlchemy 2.0 base and Alembic baseline revision (`0001_baseline.py`)
  - Automated CI workflow in [.github/workflows/ci.yml](../../.github/workflows/ci.yml)
  - Comprehensive unit test suites (24 backend tests, 33 frontend tests)
  - Phase 1 release documentation ([CHANGELOG.md](../../CHANGELOG.md), [docs/releases/phase1.md](../releases/phase1.md), and [docs/qa/phase1-qa-report.md](../qa/phase1-qa-report.md))
- **Production Baseline (`main`)**: Commit `23caa30` (`chore: initialize repository`). Main is updated strictly by the human developer via milestone merges from `develop`.

---

## 2. Retention Policy for Existing Phase 1 Branches

All existing Phase 1 branches must be **RETAINED** in their current form. They must **never** be deleted, renamed, or force-pushed:

| Branch Name | Tip Commit Hash | Description / Milestone Role |
| :--- | :--- | :--- |
| `main` | `23caa30` | Production baseline (unmodified initial commit) |
| `develop` | `f91e7bd` | Primary integration base containing all merged Phase 1 work |
| `feature/repo-foundation` | `471cc61` | Initial repository layout, conventions, and linters |
| `docs/engineering-conventions` | `dc776bf` | Engineering guidelines, ADR 0001, and architecture |
| `feature/backend-scaffold` | `ea4cc9b` | FastAPI service factory, health, and version endpoints |
| `feature/frontend-scaffold` | `8e933c9` | Next.js 16 application scaffolding and TypeScript setup |
| `feature/env-config` | `505406c` | Typed Pydantic settings and environment templates |
| `feature/health-integration` | `705f388` | Frontend BackendStatus component and API client wrapper |
| `feature/frontend-tests` | `c817de7` | Vitest test harness and frontend client unit tests |
| `test/phase1-integration` | `98fe316` | Standalone Python smoke test and CORS integration tests |
| `feature/postgres-dev-setup` | `92412e1` | Docker Compose PostgreSQL 16 service container |
| `feature/db-baseline` | `7a950c2` | SQLAlchemy base, session factory, and Alembic baseline |
| `feature/ci-workflow` | `455258c` | Multi-job GitHub Actions CI workflow |
| `docs/phase1-setup` | `b6671cc` | Comprehensive README setup guide and architecture notes |
| `feature/deployment-shell` | `ef7433c` | Production Dockerfiles for backend and frontend |
| `test/phase1-final-verification` | `2687fd8` | Independent Phase 1 QA verification matrix |
| `docs/phase1-release-notes` | `e2de7bf` | Phase 1 release notes (v0.1.0) and root CHANGELOG.md |

---

## 3. Branch Reuse Policy

- **No Stale Reuse**: Never reuse an already merged or completed Phase 1 branch for Phase 2 or Phase 3 tasks.
- **Conditional Reuse**: An existing branch may be reused only when **all** of the following criteria are satisfied:
  1. The branch was explicitly created for the exact task being performed.
  2. The branch is unmerged into `develop`.
  3. The branch contains no unrelated commits or unreviewed diffs.
  4. The working tree is clean.
- When no suitable unmerged branch exists, a new topic branch must be created from `develop`.

---

## 4. Planned Branches for Phase 2 (Foundation & Deterministic Engine)

All Phase 2 branches start from `develop` (updated sequentially as prior branches merge):

| Planned Branch Name | Role | Base Branch | Purpose / Scope |
| :--- | :---: | :---: | :--- |
| `docs/phase2-3-plan` | `docs` | `develop` | Branch plan and data contracts specification (this task). |
| `feature/phase2-models-schemas` [PLANNED] | `feature` | `develop` | Pydantic intake schemas (`TripRequest`), normalized provider schemas, provenance enum, and SQLAlchemy trip domain models with Alembic migration `0002_trip_persistence`. |
| `feature/open-meteo-client` [PLANNED] | `feature` | `develop` | Promote `httpx` to `backend/requirements.txt`, implement resilient Open-Meteo geocoding and weather client with unit tests and deterministic offline fixtures. |
| `feature/itinerary-generator` [PLANNED] | `feature` | `develop` | Deterministic rule-based day-by-day itinerary generation engine matching pace, interests, and weather summary, assigning strict provenance. |
| `feature/trip-persistence-api` [PLANNED] | `feature` | `develop` | FastAPI route endpoints (`POST /api/trips`, `GET /api/trips/{id}`, `GET /api/trips`) with error mapping and partial result handling. |
| `feature/phase2-results-ui` [PLANNED] | `feature` | `develop` | Frontend Next.js trip intake form, itinerary display cards, weather forecast summary, provenance indicators, and reload-by-URL support. |
| `test/phase2-integration-qa` [PLANNED] | `test` | `develop` | Independent QA verification in a fresh clone, live smoke testing, and QA verification matrix in `docs/qa/phase2-qa-report.md`. |
| `docs/phase2-release-notes` [PLANNED] | `docs` | `develop` | Phase 2 release notes (`docs/releases/phase2.md`) and updated `CHANGELOG.md`. |

---

## 5. Planned Branches for Phase 3 (Controlled LangGraph Orchestration)

Phase 3 introduces controlled LangGraph workflows without autonomous multi-agent swarms:

| Planned Branch Name | Role | Base Branch | Purpose / Scope |
| :--- | :---: | :---: | :--- |
| `feature/langgraph-state-schema` [PLANNED] | `feature` | `develop` | Typed `TripState`, graph state schemas, and bounded execution parameters. |
| `feature/langgraph-typed-tools` [PLANNED] | `feature` | `develop` | Narrow, typed research tool wrappers with input validation and bounded retry loops. |
| `feature/langgraph-workflow` [PLANNED] | `feature` | `develop` | Controlled LangGraph graph definition with clarification seams, deterministic validation, and repair handlers. |
| `feature/clarification-ui` [PLANNED] | `feature` | `develop` | Frontend interactive clarification prompts and incremental research progress display. |
| `test/phase3-integration-qa` [PLANNED] | `test` | `develop` | Independent QA verification of LangGraph graph execution and honest fallback handling. |
| `docs/phase3-release-notes` [PLANNED] | `docs` | `develop` | Phase 3 release notes (`docs/releases/phase3.md`) and updated `CHANGELOG.md`. |

---

## 6. Manual Merge Order for Human Developer

All merges to `develop` and `main` are executed manually by the solo developer following this strict order:

```text
[Step 1] Merge docs/phase2-3-plan -------------> into develop
[Step 2] Merge feature/phase2-models-schemas ---> into develop
[Step 3] Merge feature/open-meteo-client -------> into develop
[Step 4] Merge feature/itinerary-generator -----> into develop
[Step 5] Merge feature/trip-persistence-api ----> into develop
[Step 6] Merge feature/phase2-results-ui -------> into develop
[Step 7] Merge test/phase2-integration-qa ------> into develop
[Step 8] Merge docs/phase2-release-notes -------> into develop
[Step 9] Merge develop -------------------------> into main (Tag: v0.2.0)
```

---

## 7. Independent QA Verification Protocol

To preserve separation between implementation and testing:
1. **Isolated Execution**: QA verification is performed inside a fresh clone outside the workspace directory (e.g. `$env:TEMP\atc-qa-clone`).
2. **Read-Only Implementation**: QA never modifies application source code under `backend/app/` or `frontend/src/` to make checks pass.
3. **Allowed QA Changes**: QA commits only test harness additions, smoke test updates, and reports under `docs/qa/`.
4. **Defect Protocol**: If an implementation defect is discovered during QA, the test engineer stops, documents the failure with reproduction steps, and recommends a dedicated `fix/<defect-name>` branch for the developer.
