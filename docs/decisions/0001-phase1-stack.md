# ADR 0001: Phase 1 Core Stack and Modular Monolith Architecture

## Status
Accepted

## Context
AI Travel Concierge is an AI-powered travel research and planning application. The project is being initialized by a solo developer on Windows 11.

We require a technology stack that offers:
1. Fast iteration cycles and rapid local feedback.
2. Strong static typing across the frontend and backend.
3. Reliable relational data persistence for user plans and destination metadata.
4. Clean architectural separation without distributed systems overhead.
5. A clear upgrade path to AI agent orchestration in Phase 2.

## Decision
1. **Frontend**: Next.js (React, TypeScript) housed in `frontend/`.
   - Provides server-side rendering, modern component patterns, and robust TypeScript integration.
2. **Backend**: Python 3.11 with FastAPI and Pydantic housed in `backend/`.
   - Delivers high-performance async HTTP APIs, automatic OpenAPI documentation, and native compatibility with the Python AI ecosystem (LangChain/LangGraph) planned for Phase 2.
3. **Database**: PostgreSQL managed locally via Docker Compose.
   - Provides dependable relational persistence, ACID compliance, and standard tooling.
4. **Architecture**: Modular Monolith.
   - Keep frontend and backend in a unified repository with clear internal boundaries.
   - Avoid microservices, Kubernetes, Redis, or message queues during Phase 1.
5. **Phase Scope**: Defer all LangGraph, LangChain, LLM provider integrations, and external travel APIs to Phase 2.
   - Phase 1 focuses exclusively on environment foundations, linting, health check endpoints, containerized database connectivity, and CI automation.

## Consequences
- **Positive**:
  - Low operational complexity for a solo developer.
  - End-to-end type safety with TypeScript (frontend) and Pydantic (backend).
  - High performance and standard local development tooling (Docker, npm, pip/venv).
  - Clear progression: solid foundation established before integrating probabilistic AI workflows.
- **Trade-offs / Mitigations**:
  - Internal module discipline is required to avoid coupling between layers. Module seams are explicitly documented in [docs/architecture.md](../architecture.md).
