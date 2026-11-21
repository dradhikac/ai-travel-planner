"""Structured logging, event emission, context propagation, and secret redaction."""

import contextvars
import json
import logging
import re
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Final

logger = logging.getLogger("app.events")

# Context variables for distributed request tracing and node/tool attribution
_current_request_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="unknown"
)
_current_node: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_node", default=None
)
_current_tool: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_tool", default=None
)
_in_execute_tools: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "in_execute_tools", default=False
)

# In-memory event listeners for testing and diagnostic capture
_EVENT_LISTENERS: list[Callable[[dict[str, Any]], None]] = []

# Redaction patterns for URLs and secret credentials
URL_WITH_QUERY_REGEX: Final[re.Pattern[str]] = re.compile(
    r"(https?://[^\s?#]+)[?#][^\s\"'<>]*"
)

SECRET_PATTERNS: Final[list[tuple[re.Pattern[str], str]]] = [
    # Strip URL query strings from embedded text
    (URL_WITH_QUERY_REGEX, r"\1"),
    # OpenAI and Anthropic API keys (e.g. sk-..., sk-ant-...)
    (re.compile(r"sk-[A-Za-z0-9_-]{20,}", re.IGNORECASE), "[REDACTED]"),
    # AWS Access Key IDs
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED]"),
    # GitHub personal access tokens
    (re.compile(r"ghp_[A-Za-z0-9]{30,}"), "[REDACTED]"),
    # HTTP Authorization Bearer tokens
    (re.compile(r"(Bearer\s+)[A-Za-z0-9_\-\.]{10,}", re.IGNORECASE), r"\1[REDACTED]"),
    # OpenRouteService 32-character tokens
    (re.compile(r"5b3ce3597851110001cf6248[0-9a-fA-F]{32}"), "[REDACTED]"),
    # Generic query-style or assignment secrets
    (
        re.compile(
            r"(api_key|apikey|api-key|token|access_token|secret)=([^\s&#]+)",
            re.IGNORECASE,
        ),
        r"\1=[REDACTED]",
    ),
]

SENSITIVE_FIELD_NAMES: Final[set[str]] = {
    "authorization",
    "api_key",
    "apikey",
    "api-key",
    "x-api-key",
    "token",
    "secret",
    "password",
    "access_token",
    "refresh_token",
    "client_secret",
    "prompt",
    "completion",
    "raw_body",
    "response_body",
    "raw_provider_body",
    "itinerary_text",
    "user_message",
}


# ==============================================================================
# Context Variable Accessors
# ==============================================================================


def set_request_id(request_id: str | None) -> contextvars.Token[str]:
    """Set the current request ID context variable."""
    return _current_request_id.set(request_id if request_id else "unknown")


def get_request_id() -> str:
    """Retrieve the active request ID or 'unknown'."""
    val = _current_request_id.get()
    return val if val else "unknown"


def reset_request_id(token: contextvars.Token[str]) -> None:
    """Reset request ID context variable to previous state."""
    _current_request_id.reset(token)


def set_current_node(node_name: str | None) -> contextvars.Token[str | None]:
    """Set the active graph node name in context."""
    return _current_node.set(node_name)


def get_current_node() -> str | None:
    """Retrieve the active graph node name."""
    return _current_node.get()


def reset_current_node(token: contextvars.Token[str | None]) -> None:
    """Reset current node context variable."""
    _current_node.reset(token)


def set_current_tool(tool_name: str | None) -> contextvars.Token[str | None]:
    """Set the active tool name in context."""
    return _current_tool.set(tool_name)


def get_current_tool() -> str | None:
    """Retrieve the active tool name."""
    return _current_tool.get()


def reset_current_tool(token: contextvars.Token[str | None]) -> None:
    """Reset current tool context variable."""
    _current_tool.reset(token)


def set_in_execute_tools(val: bool) -> contextvars.Token[bool]:
    """Mark whether execution is currently inside the execute_tools graph node."""
    return _in_execute_tools.set(val)


def is_in_execute_tools() -> bool:
    """Check whether execution is currently inside execute_tools."""
    return _in_execute_tools.get()


def reset_in_execute_tools(token: contextvars.Token[bool]) -> None:
    """Reset in_execute_tools context variable."""
    _in_execute_tools.reset(token)


# ==============================================================================
# Redaction & Sanitization Helpers
# ==============================================================================


def redact_string(val: str) -> str:
    """Apply secret redaction patterns and query string stripping to a string."""
    for pattern, replacement in SECRET_PATTERNS:
        val = pattern.sub(replacement, val)
    return val


def sanitize_for_logging(data: Any, key_name: str | None = None) -> Any:
    """Recursively sanitize data structures, masking secrets and sensitive fields."""
    if key_name and key_name.lower() in SENSITIVE_FIELD_NAMES:
        if key_name.lower() == "user_message" and isinstance(data, str):
            return f"[USER_MESSAGE len={len(data)}]"
        return "[REDACTED]"

    if isinstance(data, dict):
        sanitized_dict: dict[str, Any] = {}
        for k, v in data.items():
            k_str = str(k)
            if k_str.lower() in SENSITIVE_FIELD_NAMES:
                if k_str.lower() == "user_message" and isinstance(v, str):
                    sanitized_dict[k_str] = f"[USER_MESSAGE len={len(v)}]"
                else:
                    sanitized_dict[k_str] = "[REDACTED]"
            else:
                sanitized_dict[k_str] = sanitize_for_logging(v, key_name=k_str)
        return sanitized_dict

    if isinstance(data, (list, tuple, set)):
        sanitized_items = [sanitize_for_logging(item) for item in data]
        if isinstance(data, tuple):
            return tuple(sanitized_items)
        if isinstance(data, set):
            return set(sanitized_items)
        return sanitized_items

    if isinstance(data, str):
        return redact_string(data)

    if isinstance(data, (int, float, bool)) or data is None:
        return data

    return redact_string(str(data))


# ==============================================================================
# Structured Event Emission
# ==============================================================================


def _record_event_to_listeners(event_dict: dict[str, Any]) -> None:
    """Deliver event dictionary copy to all registered listener callbacks."""
    for listener in list(_EVENT_LISTENERS):
        try:
            listener(dict(event_dict))
        except Exception:
            pass


def add_event_listener(listener: Callable[[dict[str, Any]], None]) -> None:
    """Register a callback invoked whenever a structured event is emitted."""
    if listener not in _EVENT_LISTENERS:
        _EVENT_LISTENERS.append(listener)


def remove_event_listener(listener: Callable[[dict[str, Any]], None]) -> None:
    """Remove a previously registered event listener callback."""
    if listener in _EVENT_LISTENERS:
        _EVENT_LISTENERS.remove(listener)


class EventCapture:
    """Context manager for capturing emitted events in memory during test blocks."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def __enter__(self) -> "EventCapture":
        self.events.clear()
        add_event_listener(self.events.append)
        return self

    def __exit__(self, *args: Any) -> None:
        remove_event_listener(self.events.append)


def emit_event(
    event_name: str,
    *,
    node: str | None = None,
    tool: str | None = None,
    attempt: int | None = None,
    latency_ms: float | None = None,
    status: str | None = None,
    error_code: str | None = None,
    retry_delay_ms: float | None = None,
    request_id: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Emit a canonical structured JSON event with context attribution and redaction."""
    active_req_id = request_id or get_request_id()
    if not active_req_id:
        active_req_id = "unknown"

    active_node = node if node is not None else get_current_node()
    active_tool = tool if tool is not None else get_current_tool()

    if latency_ms is not None:
        latency_val: float | None = max(0.0, round(float(latency_ms), 2))
    else:
        latency_val = None

    if retry_delay_ms is not None:
        delay_val: float | None = max(0.0, round(float(retry_delay_ms), 2))
    else:
        delay_val = None

    event_payload: dict[str, Any] = {
        "event_name": event_name,
        "request_id": active_req_id,
        "node": active_node,
        "tool": active_tool,
        "attempt": attempt,
        "latency_ms": latency_val,
        "status": status,
        "error_code": error_code,
        "retry_delay_ms": delay_val,
        "timestamp": datetime.now(UTC).isoformat(),
    }

    # Merge extra attributes
    for k, v in extra.items():
        if k not in event_payload:
            event_payload[k] = sanitize_for_logging(v, key_name=k)

    clean_payload = sanitize_for_logging(event_payload)
    _record_event_to_listeners(clean_payload)

    json_str = json.dumps(clean_payload, separators=(",", ":"))
    logger.info(json_str)

    return clean_payload


def emit_tool_call_finished(
    res: Any,
    node: str | None = None,
) -> dict[str, Any]:
    """Helper to emit canonical 'tool_call_finished' event from a ToolResult."""
    err_code = (
        res.error_code.value
        if hasattr(res.error_code, "value")
        else (str(res.error_code) if getattr(res, "error_code", None) else None)
    )
    status_str = res.status.value if hasattr(res.status, "value") else str(res.status)
    latency = res.latency_ms if getattr(res, "latency_ms", None) is not None else 0.0
    attempts = getattr(res, "attempts", 1) or 1
    data_origin = getattr(res, "data_origin", "none") or "none"

    return emit_event(
        "tool_call_finished",
        node=node,
        tool=res.tool_name,
        status=status_str,
        error_code=err_code,
        latency_ms=latency,
        attempts=attempts,
        data_origin=data_origin,
    )


# ==============================================================================
# Standard Logging Initialization
# ==============================================================================


def setup_logging(log_level: str = "INFO") -> None:
    """Configure standard library root logger."""
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )
