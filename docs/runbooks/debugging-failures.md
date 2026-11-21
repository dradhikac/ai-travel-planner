# AI Travel Concierge - Failure Debugging & Structured Logs Runbook

This runbook establishes diagnostic procedures, log search workflows, and failure classification rules for debugging incidents in the AI Travel Concierge application.

---

## 1. Structured Logging Overview

All workflow components—graph nodes, research tools, bounded retries, and repair passes—emit standardized single-line JSON log events to `stdout` under the `app.events` logger.

Every event adheres to a strict schema featuring distributed tracing (`request_id`), canonical node and tool attribution, performance latencies (`latency_ms`), error taxonomy (`error_code`), and ISO 8601 UTC timestamps.

### Strict Redaction & Privacy Guarantee
To preserve data privacy and security, all log lines pass through a centralized redaction filter (`app.core.logging.sanitize_for_logging`):
- **API Keys & Credentials**: Anthropic, OpenAI, AWS, GitHub, and OpenRouteService tokens are redacted to `[REDACTED]`.
- **Query Strings & URLs**: All URLs have query parameters stripped (e.g. `https://api.openrouteservice.org/v2/directions` with zero query params).
- **User Messages**: Raw user prompt text is never logged; only message length is captured (`[USER_MESSAGE len=N]`).
- **Prompts & Completions**: LLM input prompts and raw model completions are never emitted.
- **Itinerary Text**: Validation repair events record deterministic issue code strings only (e.g. `["pacing_mismatch"]`), never draft itinerary text.

---

## 2. Searching Logs by Request ID

Every API request and workflow run generates or receives a unique `request_id` propagated across all asynchronous tasks and threads via Python `contextvars`.

### Windows 11 / PowerShell 5.1 & 7

#### Find all events for a specific Request ID:
```powershell
Get-Content backend.log | Select-String -Pattern '"request_id":"<REQUEST_ID>"'
```

#### Parse events into a readable table:
```powershell
Get-Content backend.log | Select-String -Pattern '"request_id":"<REQUEST_ID>"' | ForEach-Object {
    $_.Line | ConvertFrom-Json
} | Format-Table timestamp, event_name, node, tool, status, latency_ms, error_code
```

#### Find only failure or retry events:
```powershell
Get-Content backend.log | Select-String -Pattern '"request_id":"<REQUEST_ID>"' | ForEach-Object {
    $_.Line | ConvertFrom-Json
} | Where-Object { $_.status -in @("failed", "timeout", "rate_limited", "error") -or $_.event_name -eq "retry_scheduled" } | Format-Table timestamp, event_name, tool, status, error_code, retry_delay_ms
```

---

### Bash / macOS / Linux

#### Find all events for a specific Request ID:
```bash
grep '"request_id":"<REQUEST_ID>"' backend.log
```

#### Pretty-print JSON events using `jq`:
```bash
grep '"request_id":"<REQUEST_ID>"' backend.log | jq '{timestamp, event_name, node, tool, status, latency_ms, error_code}'
```

#### Filter failures and retry attempts:
```bash
grep '"request_id":"<REQUEST_ID>"' backend.log | jq 'select(.status == "failed" or .status == "timeout" or .status == "rate_limited" or .status == "error" or .event_name == "retry_scheduled")'
```

---

## 3. Structured Field Glossary

Every emitted JSON event contains the following fields:

| Field Name | Type | Description | Example Values |
| :--- | :--- | :--- | :--- |
| `event_name` | `string` | Canonical event identifier. | `"node_started"`, `"node_finished"`, `"tool_call_finished"`, `"retry_scheduled"`, `"repair_attempt"`, `"workflow_finished"` |
| `request_id` | `string` | Tracing UUID for the workflow execution. Defaults to `"unknown"` if unset. | `"550e8400-e29b-41d4-a716-446655440000"` |
| `node` | `string \| null` | Graph execution node in LangGraph state machine. | `"parse_request"`, `"execute_tools"`, `"validate_itinerary"`, `"repair_itinerary"` |
| `tool` | `string \| null` | Research tool identifier. | `"geocode_destination"`, `"get_weather"`, `"get_route_context"` |
| `attempt` | `int \| null` | Sequence attempt number for retries or repair iterations. | `1`, `2`, `3` |
| `latency_ms` | `float \| null` | Non-negative elapsed duration in milliseconds. | `142.5`, `12.0` |
| `status` | `string \| null` | Operation or node termination status. | `"ok"`, `"failed"`, `"timeout"`, `"rate_limited"`, `"skipped"`, `"empty"`, `"completed"`, `"partial"` |
| `error_code` | `string \| null` | Standardized error category or exception name. | `"timeout"`, `"rate_limited"`, `"authentication_failed"`, `"malformed_response"`, `"not_found"` |
| `retry_delay_ms` | `float \| null` | Backoff delay scheduled before next retry. | `500.0`, `1000.0` |
| `timestamp` | `string` | ISO 8601 UTC timestamp of event creation. | `"2026-11-21T22:30:00.000000+00:00"` |
| `data_origin` | `string \| null` | Source provenance indicator. | `"live"`, `"mock"`, `"fixture"`, `"none"` |
| `issue_codes` | `list[str] \| null` | Validation rule codes present during a repair iteration (issue codes only, no text). | `["pacing_mismatch", "unrealistic_duration"]` |
| `tool_counts` | `dict \| null` | Summary tally of tool results emitted at workflow completion. | `{"total": 4, "ok": 3, "failed": 1, "skipped": 0, "empty": 0}` |

---

## 4. Canonical Event Reference

### `node_started`
- **Emission Seam**: Immediately before graph node execution begins.
- **Key Fields**: `event_name`, `request_id`, `node`, `timestamp`.

### `node_finished`
- **Emission Seam**: Immediately after graph node execution terminates.
- **Key Fields**: `event_name`, `request_id`, `node`, `latency_ms`, `status` (`"ok"`, `"failed"`), `error_code`, `timestamp`.

### `tool_call_finished`
- **Emission Seam**: When a planned tool finishes execution or is marked skipped.
- **Key Fields**: `event_name`, `request_id`, `node`, `tool`, `status` (`"ok"`, `"empty"`, `"timeout"`, `"rate_limited"`, `"error"`, `"skipped"`), `error_code`, `latency_ms`, `attempts`, `data_origin`, `timestamp`.

### `retry_scheduled`
- **Emission Seam**: Triggered by bounded retry utility before sleeping and retrying a transient failure.
- **Key Fields**: `event_name`, `request_id`, `node`, `tool`, `attempt`, `error_code`, `retry_delay_ms`, `timestamp`.

### `repair_attempt`
- **Emission Seam**: Invoked during the `repair_itinerary` node when critical validation issues exist.
- **Key Fields**: `event_name`, `request_id`, `node="repair_itinerary"`, `attempt`, `issue_codes` (string codes only), `timestamp`.

### `workflow_finished`
- **Emission Seam**: When LangGraph execution completes in `run_workflow`.
- **Key Fields**: `event_name`, `request_id`, `status` (`"completed"`, `"partial"`, `"failed"`, `"needs_clarification"`), `repair_attempts`, `tool_counts`, `latency_ms`, `timestamp`.

---

## 5. Diagnostic Decision Matrix: Symptom -> Events -> Likely Cause

| Symptom | Events to Look For | Likely Cause | Recommended Action |
| :--- | :--- | :--- | :--- |
| **Provider Timeout** | `retry_scheduled` with `error_code="timeout"` (attempts 1..N), followed by `tool_call_finished` with `status="timeout"` and `workflow_finished` with `status="partial"`. | Upstream provider (e.g. OpenRouteService directions or Open-Meteo) failed to reply within client timeout window. | Check network connectivity to upstream provider; check provider status dashboard. If persistent, consider raising timeout or using mock mode. |
| **Provider Rate Limiting** | `retry_scheduled` with `error_code="rate_limited"` and `retry_delay_ms`, followed by `tool_call_finished` with `status="rate_limited"`. | Upstream provider returned HTTP 429 Too Many Requests, exceeding rate quotas. | Check request volume. Verify that `Retry-After` header is honored. For OpenRouteService, check API key quota usage. |
| **Authentication Failure** | Single `tool_call_finished` with `error_code="authentication_failed"` (attempt 1, zero `retry_scheduled` events). | Non-retryable HTTP 401 or 403 returned by upstream provider. Invalid or expired API key. | Inspect `OPENROUTESERVICE_API_KEY` configuration. Note: The workflow immediately fails attempt 1 without retries per non-retryable error contract. |
| **Invalid / Malformed Response** | `tool_call_finished` with `error_code="malformed_response"` and `status="error"`. | Upstream provider returned HTTP 200 with an unparseable schema or missing coordinates. | Check upstream API version compatibility or inspect changes in provider response format. |
| **Validation Failures (Critical)** | `node_finished` for `validate_itinerary` noting critical issues, followed by `repair_attempt` with `issue_codes`. | Synthesized itinerary violated deterministic domain rules (e.g. pacing mismatch, unrealistic day duration). | Inspect the `issue_codes` array in the `repair_attempt` event to identify which validation rules were triggered. |
| **Exhausted Repairs** | Multiple `repair_attempt` events up to `MAX_REPAIR_ATTEMPTS` (default 2), followed by `node_finished` for `build_partial_result` and `workflow_finished` with `status="partial"`. | Repair gateway was unable to resolve critical validation flaws within bounded loop budget. | Workflow degrades safely to `RunStatus.PARTIAL` with safe partial result. Review generator or gateway repair prompts. |
| **Recursion / Step Limit Exceeded** | `workflow_finished` with `status="failed"` and warning `"Workflow execution exceeded recursion limit"`. | LangGraph super-step guard or runaway execution ceiling triggered (`AGENT_RECURSION_LIMIT`). | Check state transitions for cyclic loops between `repair_itinerary` and `validate_itinerary`. |
| **Unavailable Capability** | `tool_call_finished` with `status="skipped"`, `attempts=0`, and `latency_ms=0.0`. | Tool capability disabled or missing API key in live mode (`ROUTING_PROVIDER_MODE="live"` without key). | Normal graceful degradation. To enable, configure `OPENROUTESERVICE_API_KEY` or switch to `ROUTING_PROVIDER_MODE="mock"`. |
