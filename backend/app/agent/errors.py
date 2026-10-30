"""Exception classes and error codes for Phase 3 agent orchestration."""

from enum import StrEnum


class ToolErrorCode(StrEnum):
    """Stable, safe error codes for agent tool execution failures.

    These codes are surfaced in ToolResult envelopes and client API errors without
    leaking internal provider URLs, credentials, or raw stack traces.
    """

    PROVIDER_UNAVAILABLE = "provider_unavailable"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    INVALID_ARGUMENTS = "invalid_arguments"
    MALFORMED_RESPONSE = "malformed_response"
    NOT_FOUND = "not_found"
    OUT_OF_FORECAST_RANGE = "out_of_forecast_range"
    EXECUTION_FAILED = "execution_failed"
    SKIPPED = "skipped"


class AgentError(Exception):
    """Base exception for agent state machine and tool execution errors."""

    def __init__(self, message: str, code: str = "agent_error") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class ToolContractError(AgentError):
    """Raised when a tool argument or tool result violates its domain contract."""

    def __init__(
        self, message: str, code: str = ToolErrorCode.INVALID_ARGUMENTS
    ) -> None:
        super().__init__(message, code=str(code))


class SecurityViolationError(AgentError):
    """Raised when state fields contain forbidden secret-like identifiers or tokens."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="security_violation")
