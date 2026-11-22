# Regression Test Suite Documentation

## Overview

The regression test suite (`backend/tests/regression`) provides an automated, data-driven regression harness running **100% offline** with zero external network access and zero real clock sleeps.

Governed by Phase 4 reliability contracts, it protects against regressions across core multi-tool workflows, fallback branches, timeout handling, authentication degradation, rate-limiting degradation, prompt injection resilience, input boundaries, and validation repair loops.

---

## Architecture & Guarantees

1. **Declarative Test Cases**:
   - Each test scenario is authored as a JSON file located in `backend/tests/regression/cases/*.json`.
   - The test runner (`test_regression_cases.py`) dynamically discovers and parses all JSON files, parametrizing pytest execution by `case["id"]`.
   - On any failure, the exact case ID, category, and differential diagnostics are surfaced immediately.

2. **Offline & Network-Isolated**:
   - Inherits `prevent_real_network_sockets` from `conftest.py`, forcibly disabling real network socket creation. Any attempt to reach an external host raises `RuntimeError`.
   - Uses injected mock tool implementations for `geocode_destination`, `get_weather`, and `get_route_context` with deterministic delays and status transitions (mock latencies are recorded as numerical metadata with zero `time.sleep`).

3. **Deterministic Repair & Execution**:
   - Deterministic rule-based gateways simulate LLM drafting and iterative repair.
   - Reference dates are frozen via `TripRequest.set_test_today(...)` to ensure long-term reproducibility across seasons and years.

4. **Category Reporting Hook**:
   - Implemented via `pytest_terminal_summary` in `backend/tests/regression/conftest.py`.
   - Outputs a clean, formatted table summarizing pass/fail counts and percentages across all 10 scenario categories.

---

## Test Scenario Categories

The suite covers 10 mandatory categories across 29 test cases:

| Category | Description | Primary Invariants Verified |
| :--- | :--- | :--- |
| `normal` | Happy-path trip discovery and planning | Valid intake parameters produce completed status and expected tool calls. |
| `ambiguous` | Missing fields, vague inputs, contradictions | Generates targeted clarification questions or flags contradictions without crashing. |
| `impossible_budget` | Extreme low or negative budgets | Rejects negative/zero budgets; triggers advisory notes for constrained budgets. |
| `empty_result` | Provider returns no matching results | Safely degrades with clear user notices; does not raise unhandled exceptions. |
| `timeout` | Simulated upstream provider timeouts | Bounded retries abort on budget expiry; preserves partial results. |
| `auth_failure` | 401/403 authorization failures | Aborts retries immediately (non-retryable); surfaces sanitized notices. |
| `rate_limit` | 429 upstream rate-limiting | Non-retryable in Phase 4; degrades gracefully without infinite loops. |
| `invalid_itinerary` | Repair loops and bounded repair | Validates 2-attempt repair cap, no-progress early halting, and safe partial plan synthesis. |
| `injection` | Adversarial prompt injection attacks | System prompt overrides and booking commands are safely neutralized without state alteration. |
| `length_limit` | Extreme input payloads (>2000 chars) | Handled gracefully without stack overflows or buffer degradation. |

---

## JSON Case Schema Specification

Every case file in `backend/tests/regression/cases/` adheres to the following JSON structure:

```json
{
  "id": "REG-NORM-01",
  "category": "normal",
  "description": "Short human-readable summary of the test scenario",
  "input": {
    "user_message": "Plan a 3-day cultural trip to Munich from 2027-06-01 to 2027-06-03 for 2 travelers",
    "known_fields": {
      "origin": "Berlin",
      "destination": "Munich",
      "start_date": "2027-06-01",
      "end_date": "2027-06-03",
      "party_size": 2,
      "interests": ["culture"],
      "pace": "balanced"
    },
    "intent": "itinerary_planning"
  },
  "fake_tool_behaviours": {
    "geocode_destination": {
      "status": "ok",
      "latency_ms": 100.0
    },
    "get_weather": {
      "status": "ok",
      "latency_ms": 120.0
    }
  },
  "expected_status": "completed",
  "expected_warning_codes": [],
  "expected_tool_call_counts": {
    "geocode_destination": 1,
    "get_weather": 1
  }
}
```

### Key Schema Fields

- `id` (string, required): Unique identifier format `REG-<CATEGORY>-<SEQ>`.
- `category` (string, required): One of the 10 scenario categories.
- `description` (string, required): Purpose and validation criteria.
- `input` (object, required):
  - `user_message` (string): Raw user prompt.
  - `known_fields` (object): Pre-parsed entity dictionary.
  - `intent` (string): Intent classification (e.g. `itinerary_planning`, `weather_planning`, `route_planning`, `unsupported`).
- `initial_draft` (string, optional): `"critical_duplicate"` to pre-seed an invalid draft for repair testing.
- `gateway_override` (string, optional): `"repair_success"`, `"repair_exhausted"`, or `"no_progress"`.
- `fake_tool_behaviours` (object, optional): Simulated responses per tool (`status`: `ok`, `empty`, `timeout`, `auth_failure`, `rate_limited`, `recovery_on_retry`).
- `expected_status` (string, required): Terminal workflow status (`completed`, `partial`, `needs_clarification`, `failed`).
- `expected_warning_codes` (list of strings, optional): Substrings that must be present in warnings, contradictions, validation issues, or clarification prompts.
- `expected_repair_attempts` (integer, optional): Expected count of repair attempts performed.
- `expected_tool_call_counts` (object, optional): Expected exact number of invocations per tool.

---

## Adding a New Regression Case

To add a new scenario:
1. Create a new JSON file in `backend/tests/regression/cases/` following the naming convention `case_<number>_<category>_<detail>.json`.
2. Define the scenario inputs and expected outcomes following the schema above.
3. Run the regression suite to verify that the new case is automatically discovered, executed, and validated.

---

## Running the Regression Suite

The suite can be executed standalone or as part of the broader backend test suite.

### PowerShell (Windows 11)

```powershell
# Run only regression tests with category summary
Set-Location backend
.\.venv\Scripts\python.exe -m pytest tests/regression -v
Set-Location ..

# Run regression tests via marker
Set-Location backend
.\.venv\Scripts\python.exe -m pytest -m regression -v
Set-Location ..
```

### Bash (Linux / macOS / WSL)

```bash
# Run only regression tests with category summary
cd backend
python -m pytest tests/regression -v
cd ..

# Run regression tests via marker
cd backend
python -m pytest -m regression -v
cd ..
```

---

## Continuous Integration (CI)

The regression suite runs automatically on every pull request and push targeting `main` or `develop` via `.github/workflows/ci.yml`.

The workflow step is defined under the `backend` job:
```yaml
      - name: Run regression test suite
        run: |
          cd backend
          pytest -m regression -q
```
It runs with `permissions: contents: read` and does not require or consume any cloud credentials or secrets.
