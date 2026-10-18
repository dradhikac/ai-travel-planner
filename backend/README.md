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

---

## Architectural Boundaries

- **Modular Monolith**: All application logic is organized in internal module seams.
- **Strict Boundary**: AI Travel Concierge is strictly a discovery and planning assistant, not a booking engine. No booking, payment, reservation, or ticketing mechanisms are implemented.
