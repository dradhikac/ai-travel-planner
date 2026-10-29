# Phase 3 Dependency Decision: LangGraph & LangChain-Core

- **Date**: 2026-10-29
- **Author**: AI Travel Concierge Planning & Documentation Team
- **Status**: **Approved / Accepted for Phase 3**
- **Target Repository**: `ai-travel-concierge`
- **Scope**: Phase 3 Agent Architecture & Controlled Workflow Engine

---

## 1. Executive Summary & Decision

For **Phase 3 (Controlled Agent Orchestration)**, the project adopts **`langgraph`** and **`langchain-core`** as minimal, focused dependencies to build a deterministic, bounded state machine.

### Chosen Packages and Version Constraints

| Package | Version Constraint | Verified PyPI Version | Primary Purpose |
| :--- | :--- | :--- | :--- |
| **`langgraph`** | `>=0.2.0,<1.3.0` | `1.2.18` | StateGraph builder, `START`/`END` markers, conditional edge routing, cycle guardrails (`recursion_limit`). |
| **`langchain-core`** | `>=0.3.0,<1.8.0` | `1.7.1` | Narrow `@tool` decorator, structured tool schema definitions (`args_schema`), and standard error contracts. |

> [!IMPORTANT]
> **No changes were made to repository configuration files in this task.**
> `backend/requirements.txt`, `backend/requirements-dev.txt`, and `backend/pyproject.toml` remain unmodified. These packages are verified via an isolated external virtual environment and scheduled for integration during implementation Task 14 (`feature/langgraph-state-schema`).

---

## 2. Research & Documentation Evidence

Official documentation and release specifications were reviewed on **2026-10-29**:

- **LangGraph Releases & Requirements**:
  - URL: [https://github.com/langchain-ai/langgraph/releases](https://github.com/langchain-ai/langgraph/releases)
  - URL: [https://langchain-5e9cc07a.mintlify.app/migration-guides/langgraph-v1](https://langchain-5e9cc07a.mintlify.app/migration-guides/langgraph-v1)
  - Python requirement: `Python >= 3.10` (Python 3.9 dropped).
  - Pydantic requirement: `pydantic >= 2.7.4`.
- **LangGraph StateGraph & Guardrail Architecture**:
  - Official Reference: `langgraph.graph.StateGraph`, `START`, `END`, `add_conditional_edges`.
  - Recursion safety: `recursion_limit` passed as top-level key in `config={"recursion_limit": N}`, raising `langgraph.errors.GraphRecursionError` if execution exceeds threshold.
- **LangChain Core Structured Tools**:
  - Official Reference: `langchain_core.tools.tool` with `args_schema: type[BaseModel]`.
  - Enables strict input validation matching existing Pydantic v2 domain schemas (`TripRequest`, `GeocodeResult`).

---

## 3. Compatibility Audit with Existing Project Stack

The candidate packages were tested against the project's exact pinned dependencies:

| Existing Project Dependency | Pinned Version in Repo | Installed / Resolved | Compatibility Status | Notes |
| :--- | :--- | :--- | :---: | :--- |
| **Python** | Runtime | `3.11.9` (CI: `3.11`) | **PASS** | Meets `Python >=3.10` requirement. |
| **FastAPI** | `~=0.146.0` | `0.146.0` | **PASS** | Starlette `1.10.0` compatible. |
| **Pydantic** | Transitive | `2.14.1` | **PASS** | Fully satisfies `pydantic>=2.7.4,<3.0.0`. |
| **Pydantic Settings**| `~=2.16.0` | `2.16.2` | **PASS** | Clean co-existence with Pydantic core. |
| **SQLAlchemy** | `~=2.0.55` | `2.0.55` | **PASS** | Zero conflict with LangGraph internal types. |
| **HTTPX** | `~=0.28.1` | `0.28.1` | **PASS** | Satisfies `httpx>=0.23.0` required by `langchain-core`. |
| **Alembic** | `~=1.14.1` | `1.14.1` | **PASS** | Database migration tooling unaffected. |
| **psycopg[binary]** | `~=3.2.13` | `3.2.13` | **PASS** | PostgreSQL client drivers unaffected. |

---

## 4. Empirical Compatibility Verification (Outside Repository)

To ensure zero risk to existing project assets, verification was performed inside a temporary virtual environment outside the workspace at `$env:TEMP\atc-phase3-test-venv`:

### Execution Steps
1. Created fresh Python 3.11 virtual environment.
2. Installed existing `backend/requirements.txt` dependencies.
3. Installed candidate packages `langgraph>=0.2.0,<1.3.0` and `langchain-core>=0.3.0,<1.8.0`.
4. Executed `pip check` to verify dependency tree integrity:
   ```text
   No broken requirements found.
   ```
5. Executed throwaway graph script testing:
   - StateGraph construction with `TypedDict` state schema (`TripAgentState`).
   - `START` entry point, standard nodes (`parse_input`, `ask_clarification`, `draft_itinerary`), and conditional edge routing (`route_next`).
   - Top-level `recursion_limit` invocation parameter (`config={"recursion_limit": 10}`).
   - Structured tool registration with Pydantic `BaseModel` (`GeocodeArgs`) via `@tool(args_schema=GeocodeArgs)`.
6. Observed output:
   ```text
   === COMPATIBILITY CHECK ===
   Python: 3.11.9
   langgraph: 1.2.18
   langchain_core: 1.7.1
   pydantic: 2.14.1
   fastapi: 0.146.0
   httpx: 0.28.1
   Graph Success Execution: {'destination': 'Tokyo', 'clarification_needed': False, 'iterations': 1, 'itinerary_draft': 'Draft itinerary for Tokyo'}
   Graph Clarification Execution: {'destination': 'Unknown', 'clarification_needed': True, 'iterations': 1, 'itinerary_draft': 'Clarification requested: Please provide dates.'}
   Tool Execution Result: Resolved: Paris -> 48.8534, 2.3488
   ALL COMPATIBILITY VERIFICATIONS PASSED!
   ```
7. Cleaned up and deleted the temporary virtual environment completely.

---

## 5. Architectural Non-Goals: What Was Explicitly NOT Added

To preserve the modular monolith architecture and adhere to solo-developer operational reality, several common AI infrastructure components were evaluated and **deliberately rejected**:

### 1. No Umbrella `langchain` Package
- **Reason**: The full `langchain` package pulls hundreds of megabytes of transitive dependencies, experimental scrapers, community integrations, and complex abstractions.
- **Decision**: Only `langgraph` (graph engine) and `langchain-core` (typed tool & message primitives) are adopted.

### 2. No Vector Databases (Pinecone, Chroma, Qdrant, Weaviate, pgvector)
- **Reason**: Travel research in AI Travel Concierge relies on **authoritative external live facts** (geocoding, meteorological forecasts) and **deterministic domain rules** (pacing, day schedules, budget allocation). It does not require semantic similarity search over unstructured document embeddings.
- **Decision**: Vector databases add stateful network maintenance, synchronization bugs, and memory bloat with zero benefit to Phase 3 core planning.

### 3. No Distributed Queues or Cache Stores (Redis, Celery, RabbitMQ)
- **Reason**: The application is a modular monolith. Graph workflows execute in-process within async FastAPI request lifecycles.
- **Decision**: Adding Redis introduces an external daemon dependency, connection pooling overhead, and complex serialization barriers. Persistence is handled exclusively by PostgreSQL via SQLAlchemy.

### 4. No Unbounded Multi-Agent Swarms (CrewAI, AutoGen, ChatDev, Swarm)
- **Reason**: Multi-agent chat swarms (agents debating each other) are non-deterministic, difficult to test, prone to runaway token consumption, and violate our non-booking truthfulness boundaries.
- **Decision**: LangGraph enables a **single, tightly controlled, single-agent state machine** with explicit conditional edges, finite repair budgets, and deterministic validation.

---

## 6. Unresolved Risks & Mitigations

| Risk | Impact | Mitigation Strategy |
| :--- | :--- | :--- |
| **Rapid upstream release cadence** | Minor interface drift in `langgraph` minor versions | Enforce bounded semantic version constraint `<1.3.0` and pin minor versions in CI lockfiles. |
| **Starlette / TestClient deprecation notice** | Informational deprecation warning during test runs | No runtime impact; TestClient remains fully functional with Starlette `1.10.0`. |
| **Graph execution recursion loops** | Unbounded runtime execution on cyclic edge definitions | Mandatory `recursion_limit=25` on all graph invocations, backed by explicit `MAX_REPAIR_ATTEMPTS = 2` guards in state. |
