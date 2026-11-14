"""Deterministic bounded retry with exponential backoff and jitter."""

import asyncio
import inspect
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final, TypeVar

from app.providers.errors import ErrorCode, ProviderError

# Default contract constants matching Phase 4 reliability specifications
DEFAULT_MAX_RETRIES: Final[int] = 2
DEFAULT_BASE_DELAY_SECONDS: Final[float] = 0.5
DEFAULT_BACKOFF_FACTOR: Final[float] = 2.0
DEFAULT_MAX_DELAY_SECONDS: Final[float] = 4.0
DEFAULT_TOTAL_BUDGET_SECONDS: Final[float] = 8.0

T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    """Configurable policy for bounded retries with backoff and jitter.

    Attributes:
        max_retries: Maximum number of retry attempts after the initial failure.
            0 disables retries completely.
        base_delay_seconds: Initial backoff step before exponentiation.
        backoff_factor: Multiplier applied per subsequent retry attempt.
        max_delay_seconds: Maximum delay ceiling for any individual retry sleep.
        total_budget_seconds: Hard cumulative wall-clock budget across all attempts.
        jitter: If True, applies full jitter (uniform random in [0, delay]).
    """

    max_retries: int = DEFAULT_MAX_RETRIES
    base_delay_seconds: float = DEFAULT_BASE_DELAY_SECONDS
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR
    max_delay_seconds: float = DEFAULT_MAX_DELAY_SECONDS
    total_budget_seconds: float = DEFAULT_TOTAL_BUDGET_SECONDS
    jitter: bool = True

    def __post_init__(self) -> None:
        """Validate retry policy constraints."""
        if self.max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        if self.base_delay_seconds < 0.0:
            raise ValueError("base_delay_seconds cannot be negative")
        if self.backoff_factor < 1.0:
            raise ValueError("backoff_factor must be >= 1.0")
        if self.max_delay_seconds < 0.0:
            raise ValueError("max_delay_seconds cannot be negative")
        if self.total_budget_seconds <= 0.0:
            raise ValueError("total_budget_seconds must be positive")


async def call_with_retry(
    operation: Callable[[], Awaitable[T] | T],
    policy: RetryPolicy | None = None,
    *,
    sleep: Callable[[float], Awaitable[None]] | None = None,
    clock: Callable[[], float] | None = None,
    random_source: Callable[[float, float], float] | None = None,
    on_event: Callable[[int, str, float], None] | None = None,
) -> T:
    """Execute an asynchronous or synchronous operation with bounded retry.

    Retries strictly when ProviderError.retryable is True (transient timeouts,
    connection failures, 5xx outages, and rate limits with small Retry-After).
    Non-retryable errors (auth failures, invalid requests, malformed responses)
    and non-ProviderError exceptions fail immediately.

    Args:
        operation: Callable returning a result or awaitable result.
        policy: Configured RetryPolicy (defaults to contract defaults).
        sleep: Async sleep double (defaults to asyncio.sleep).
        clock: Monotonic clock double (defaults to time.monotonic).
        random_source: Random float generator double (defaults to random.uniform).
        on_event: Callback invoked before each retry:
            on_event(attempt, error_code, delay_ms).

    Returns:
        The successful result of operation.

    Raises:
        ProviderError: When retries are exhausted, budget is exceeded, or error
            is non-retryable. err.attempts and err.details['attempts'] record the
            total attempts executed.
    """
    eff_policy = policy if policy is not None else RetryPolicy()
    sleep_fn = sleep if sleep is not None else asyncio.sleep
    clock_fn = clock if clock is not None else time.monotonic
    random_fn = random_source if random_source is not None else random.uniform

    start_time = clock_fn()
    attempt = 0

    while True:
        attempt += 1
        try:
            res = operation()
            if inspect.isawaitable(res):
                res = await res
            return res

        except ProviderError as err:
            err.attempts = attempt
            if not isinstance(err.details, dict):
                err.details = {}
            err.details["attempts"] = attempt

            # Non-retryable provider errors fail immediately
            if not err.retryable:
                raise err

            # Max retries exhausted
            if attempt > eff_policy.max_retries:
                raise err

            # Determine delay
            if (
                err.code == ErrorCode.RATE_LIMITED
                and err.retry_after_seconds is not None
            ):
                if err.retry_after_seconds > eff_policy.max_delay_seconds:
                    err.retryable = False
                    raise err
                delay = err.retry_after_seconds
            else:
                backoff_exponent = attempt - 1
                uncapped_delay = eff_policy.base_delay_seconds * (
                    eff_policy.backoff_factor**backoff_exponent
                )
                capped_delay = min(eff_policy.max_delay_seconds, uncapped_delay)
                if eff_policy.jitter:
                    delay = random_fn(0.0, capped_delay)
                else:
                    delay = capped_delay

            # Verify total budget before sleeping
            elapsed = clock_fn() - start_time
            if (elapsed + delay) > eff_policy.total_budget_seconds:
                err.details["budget_exhausted"] = True
                raise err

            # Notify diagnostic event callback
            delay_ms = delay * 1000.0
            code_str = (
                err.code.value
                if hasattr(err.code, "value")
                else str(getattr(err, "error_code", err.code))
            )
            if on_event is not None:
                on_event(attempt, code_str, delay_ms)

            # Sleep
            await sleep_fn(delay)
