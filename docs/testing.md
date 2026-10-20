# Testing & Quality Assurance Guide

This document defines testing workflows, execution procedures, and manual verification checklists for the AI Travel Concierge project during Phase 1.

---

## 1. Automated Test Suites Overview

| Scope | Tooling | Coverage Areas | Execution Type |
| :--- | :--- | :--- | :--- |
| **Backend Unit & API** | Pytest, FastAPI TestClient | Health route (`/health`), Version route (`/api/version`), Settings/Config validation | Automated |
| **Backend CORS Integration** | Pytest, TestClient | Explicit origin header reflection, preflight OPTIONS, unlisted origin rejection, wildcard prevention | Automated |
| **Backend Error Contract** | Pytest, TestClient | Uniform JSON shape (`{"error": {"code", "message"}}`) across 404, 405, 422, 500 without stack trace leaks | Automated |
| **Frontend Unit & Components** | Vitest, Testing Library, jsdom | Config validation, HTTP API client wrapper, Health runtime validation schemas, `BackendStatus` UI states | Automated |
| **Smoke Test Script** | Python 3 Standard Library | Live HTTP probing of `/health`, `/api/version`, and optional frontend landing page | Automated |
| **Browser Integration Scenario** | Chromium / Firefox / WebKit | Real browser verification of live connection, server outage handling, and retry recovery | Manual |

---

## 2. Backend Test Execution

Backend tests reside in `backend/tests/` and execute via `pytest`.

### PowerShell (Windows 11)
```powershell
Set-Location backend

# Ensure virtual environment dependencies are installed
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

# Run linter and formatting checks
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .

# Run pytest test suite
.\.venv\Scripts\python.exe -m pytest -q

Set-Location ..
```

### Bash
```bash
cd backend

# Ensure virtual environment dependencies are installed
./.venv/bin/python -m pip install -r requirements-dev.txt

# Run linter and formatting checks
./.venv/bin/python -m ruff check .
./.venv/bin/python -m ruff format --check .

# Run pytest test suite
./.venv/bin/python -m pytest -q

cd ..
```

---

## 3. Frontend Test Execution

Frontend tests reside in `frontend/tests/` and execute via `vitest`.

### PowerShell (Windows 11)
```powershell
# Clean dependency verification
npm --prefix frontend ci

# Static analysis and type checking
npm --prefix frontend run lint
npm --prefix frontend run typecheck

# Run unit tests once
npm --prefix frontend run test

# Run unit tests in interactive watch mode (development)
npm --prefix frontend run test:watch

# Verify production compilation
npm --prefix frontend run build
```

### Bash
```bash
# Clean dependency verification
npm --prefix frontend ci

# Static analysis and type checking
npm --prefix frontend run lint
npm --prefix frontend run typecheck

# Run unit tests once
npm --prefix frontend run test

# Run unit tests in interactive watch mode (development)
npm --prefix frontend run test:watch

# Verify production compilation
npm --prefix frontend run build
```

---

## 4. Smoke Test Script Execution

The script `scripts/smoke_test.py` tests running service endpoints without third-party dependencies.

### PowerShell (Windows 11)
```powershell
# Probe local backend only (default: http://localhost:8000)
.\backend\.venv\Scripts\python.exe scripts\smoke_test.py --backend-url http://localhost:8000

# Probe both backend and frontend
.\backend\.venv\Scripts\python.exe scripts\smoke_test.py --backend-url http://localhost:8000 --frontend-url http://localhost:3000
```

### Bash
```bash
# Probe local backend only
./backend/.venv/bin/python scripts/smoke_test.py --backend-url http://localhost:8000

# Probe both backend and frontend
./backend/.venv/bin/python scripts/smoke_test.py --backend-url http://localhost:8000 --frontend-url http://localhost:3000
```

---

## 5. Browser Scenario Checklist (Manual QA)

The following checklist verifies frontend-backend interaction in a live browser.

| Step # | Verification Item | Mode | Expected Outcome | Pass / Fail |
| :---: | :--- | :---: | :--- | :---: |
| **1** | Start Backend & Frontend | Manual | Backend listening on `:8000`, Frontend listening on `:3000` | [ ] |
| **2** | Initial Load (Backend Up) | Manual | Open `http://localhost:3000`. Status shows briefly `Checking backend connection status...` (`role="status"`), followed by green card `Connected to Backend Service` displaying service status (`ok`), version (`0.1.0`), and environment (`development`). | [ ] |
| **3** | Honest Messaging Verification | Manual | Verify page clearly states Phase 1 foundation; no fake AI planning features, booking buttons, or transaction mechanisms. | [ ] |
| **4** | Simulate Server Outage | Manual | Stop the backend process (`Ctrl+C` or kill process). | [ ] |
| **5** | Retry while Offline | Manual | In browser, click `Retry Connection`. Status transitions through checking, then renders rose-tinted card: `Backend Service Unreachable` with friendly message and no technical stack traces or traceback leaks. | [ ] |
| **6** | Keyboard & Focus Accessibility | Manual | Press `Tab` to navigate to `Retry Connection`. Verify prominent visible focus ring (`ring-2 ring-blue-600 ring-offset-2`). Text conveys state without relying exclusively on color. | [ ] |
| **7** | Recover Service | Manual | Restart backend server on `:8000`. Click `Retry Connection`. Status smoothly returns to `Connected to Backend Service` with active version info. | [ ] |

---

## 6. Secret & Privacy Pre-Commit Probes

Run these commands to ensure no sensitive files or environment secrets are committed:

### PowerShell
```powershell
# Check for untracked or tracked non-example .env files
git ls-files | Select-String -Pattern '(^|/)\.env($|\.)' | Where-Object { $_ -notmatch '\.env\.example$' }

# Check for common credential and private key patterns
git grep -nIE "(sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,}|BEGIN (RSA |EC )?PRIVATE KEY)"

# Check for leaked absolute local user paths
git grep -nIE "([A-Za-z]:\\Users\\|/home/[a-z]+/|/Users/[A-Za-z]+/)"
```

### Bash
```bash
git ls-files | grep -E '(^|/)\.env($|\.)' | grep -v '\.env\.example$' || true
git grep -nIE "(sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,}|BEGIN (RSA |EC )?PRIVATE KEY)" || true
git grep -nIE "([A-Za-z]:\\Users\\|/home/[a-z]+/|/Users/[A-Za-z]+/)" || true
```
