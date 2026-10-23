# Changelog

All notable changes to the AI Travel Concierge project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) and [Conventional Commits](https://www.conventionalcommits.org/).

---

## [0.1.0] - 2026-10-23

### Phase 1 Foundation

Initial foundation release of the AI Travel Concierge web application. This release establishes the modular monolith scaffolding, backend core API, frontend web shell, development containerization, and automated quality harnesses.

#### Added
- **Repository Baseline**: Monorepo layout, EditorConfig formatting, Git attributes, agent instructions ([AGENTS.md](AGENTS.md)), and contribution guidelines ([CONTRIBUTING.md](CONTRIBUTING.md)).
- **Architecture Specifications**: Modular monolith design overview ([docs/architecture.md](docs/architecture.md)) and ADR 0001 covering core technology stack selection ([docs/decisions/0001-phase1-stack.md](docs/decisions/0001-phase1-stack.md)).
- **Backend Core**: FastAPI application factory with lifespan management, structured logging, and uniform error contract (`GET /health`, `GET /api/version`, `GET /health/db`).
- **Frontend Web Shell**: Next.js 16 (App Router) + React 19 + TypeScript application shell with Tailwind CSS styling and accessible `BackendStatus` real-time connection indicator.
- **Configuration**: Typed settings loaders for backend (Pydantic Settings) and frontend, isolated environment templates, and documentation in [docs/environment.md](docs/environment.md).
- **Test Suites**: Pytest backend suite (24 tests), Vitest frontend suite (33 tests), and dependency-free end-to-end integration probe ([scripts/smoke_test.py](scripts/smoke_test.py)).
- **Continuous Integration**: GitHub Actions workflow ([.github/workflows/ci.yml](.github/workflows/ci.yml)) validating backend lint/tests, frontend lint/typecheck/tests/build, and repository secrets hygiene.
- **Optional Database Container**: Local PostgreSQL 16 service via Docker Compose ([docker-compose.yml](docker-compose.yml)) and Alembic baseline migration revision.
- **Optional Deployment Containers**: Production `Dockerfile` and `.dockerignore` for backend (Python 3.11-slim) and frontend (Next.js standalone) with non-root user execution.
- **Release Documentation**: Comprehensive setup documentation in [README.md](README.md), final QA verification report in [docs/qa/phase1-qa-report.md](docs/qa/phase1-qa-report.md), and detailed release notes in [docs/releases/phase1.md](docs/releases/phase1.md).

#### Scope Boundaries
- **Strictly Non-Booking**: Travel discovery and planning assistant only; never performs, claims, or simulates booking transactions, reservations, ticketing, or payments.
- **No LLM Integrations**: Zero LangGraph/LangChain orchestrations, model inference, prompts, or embeddings in Phase 1.
- **No External Travel APIs**: Zero third-party travel data integrations in Phase 1.
- **No Trip Persistence**: Itinerary persistence and domain trip models deferred to subsequent phases.

For complete release details and commit traceability, see the [Phase 1 Release Notes](docs/releases/phase1.md).
