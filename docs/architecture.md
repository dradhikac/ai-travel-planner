# System Architecture

## Overview

AI Travel Concierge is structured as a **modular monolith**. It provides travel discovery and trip planning capabilities through an interactive web interface backed by a centralized API service.

The modular monolith pattern was chosen to minimize operational complexity for a solo developer while establishing strict architectural boundaries that facilitate future extension (such as adding AI orchestration tools and external travel data integrations in Phase 2).

---

## Current Components vs. Planned Modules

### Current State (Phase 1 Foundation)
At the current stage, the repository contains foundation configurations and documentation scaffolds:
- Workspace configurations: `.gitignore`, `.gitattributes`, `.editorconfig`.
- Project documentation: `AGENTS.md`, `CONTRIBUTING.md`, `README.md`, and architectural records.
- Service placeholders: `frontend/README.md`, `backend/README.md`.

### Planned Module Seams (Future Implementation)
The following directory boundaries represent the planned structure of the modular monolith. **These directories must NOT be created until their respective tasks are assigned**:

1. **`backend/app/api/` (API Transport Layer)**:
   - FastAPI routers handling HTTP requests, query parsing, and response serialization.
   - Validates input using Pydantic models.
   - Contains no business or database logic.
2. **`backend/app/services/` (Domain Business Logic)**:
   - Core domain operations (travel research synthesis, itinerary generation logic).
   - Independent of HTTP transport and database drivers.
3. **`backend/app/integrations/` (External Service Clients - Phase 2+)**:
   - Encapsulated wrappers for external travel APIs (e.g., flight data, hotel metadata, weather).
   - Strict mock interfaces for local testing.
4. **`backend/app/agents/` (AI & Orchestration - Phase 2+)**:
   - LangGraph / LangChain tool definitions and agent workflows.
   - Strictly isolated from core API routing.
5. **`backend/app/persistence/` or `backend/app/db/` (Data Access Layer)**:
   - SQLAlchemy / SQLModel models and database connection pools.
   - Encapsulates queries against PostgreSQL.
6. **`frontend/src/features/` (Frontend Feature Modules)**:
   - Feature-sliced frontend components (e.g., destination search, itinerary view).
   - Consumes backend via typed API clients.

---

## Phase 1 Health Check Data Flow

The initial end-to-end integration verifies the communication pipeline without introducing complex business logic:

```text
[ Browser / Frontend Client ]
              │
              │ HTTP GET /api/health
              ▼
[ FastAPI Route Handler (backend/app/api/health.py) ]
              │
              │ Invocations
              ▼
[ Health Check Service (backend/app/services/health.py) ]
              │
              │ Optional ping (Phase 1 DB setup)
              ▼
    [ PostgreSQL Database ]
              │
              │ Status: Healthy
              ▼
[ JSON Response: { "status": "ok", ... } ]
```

---

## Separation of Responsibilities

- **Transport vs. Logic**: Route handlers parse requests and return HTTP status codes; they delegate processing to domain services.
- **Discovery vs. Booking**: AI Travel Concierge is strictly an informational discovery and planning assistant. No booking, payment, reservation, or ticketing mechanisms are permitted anywhere in the system.
- **Frontend vs. Backend**: The frontend handles rendering, state management, and user interaction; all computational planning logic resides in the backend.
