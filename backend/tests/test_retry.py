"""Deterministic unit tests for bounded retry utility with backoff and jitter."""

import asyncio
import time
from typing import Any

import pytest

from app.core.retry import (
    DEFAULT_BACKOFF_FACTOR,
    DEFAULT_BASE_DELAY_SECONDS,
    DEFAULT_MAX_DELAY_SECONDS,
    DEFAULT_MAX_RETRIES,
    DEFAULT_TOTAL_BUDGET_SECONDS,
    RetryPolicy,
    call_with_retry,
)
from app.providers.open_meteo.client import OpenMeteoClient
from app.providers.open_meteo.errors import (
    HttpError,
    MalformedResponseError,
    RateLimitExceededError,
    TimeoutError,
)

# ==============================================================================
# Test Doubles (Zero-Sleep Clocks and Sleepers)
# ==============================================================================


class FakeClock:
    """Deterministic monotonic clock that advances when fake_sleep is invoked."""

    def __init__(self, initial_time: float = 0.0) -> None:
        self.current_time = initial_time
        self.sleep_calls: list[float] = []

    def clock(self) -> float:
        return self.current_time

    async def sleep(self, duration: float) -> None:
        self.sleep_calls.append(duration)
        self.current_time += duration


# ==============================================================================
# 1. Success Scenarios & Attempt Counting
# ==============================================================================


def test_default_retry_constants() -> None:
    """Verify default retry policy constants match reliability specification."""
    assert DEFAULT_MAX_RETRIES == 2
    assert DEFAULT_BASE_DELAY_SECONDS == 0.5
    assert DEFAULT_BACKOFF_FACTOR == 2.0
    assert DEFAULT_MAX_DELAY_SECONDS == 4.0
    assert DEFAULT_TOTAL_BUDGET_SECONDS == 8.0


def test_success_on_first_try_no_sleep() -> None:
    """Operation succeeds immediately on attempt 1 without sleeping."""
    fake = FakeClock()
    call_count = 0

    async def _operation() -> str:
        nonlocal call_count
        call_count += 1
        return "success_result"

    result = asyncio.run(
        call_with_retry(
            _operation,
            policy=RetryPolicy(max_retries=2),
            sleep=fake.sleep,
            clock=fake.clock,
        )
    )

    assert result == "success_result"
    assert call_count == 1
    assert fake.sleep_calls == []
    assert fake.current_time == 0.0


def test_timeout_then_success() -> None:
    """Transient timeout on attempt 1 succeeds on attempt 2."""
    fake = FakeClock()
    call_count = 0

    async def _operation() -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise TimeoutError("Simulated provider timeout", provider="TestProvider")
        return {"data": 42}

    policy = RetryPolicy(
        max_retries=2,
        base_delay_seconds=0.5,
        backoff_factor=2.0,
        jitter=False,
    )

    result = asyncio.run(
        call_with_retry(
            _operation,
            policy=policy,
            sleep=fake.sleep,
            clock=fake.clock,
        )
    )

    assert result == {"data": 42}
    assert call_count == 2
    assert len(fake.sleep_calls) == 1
    assert fake.sleep_calls[0] == 0.5
    assert fake.current_time == 0.5


def test_5xx_server_error_twice_then_success() -> None:
    """Server 503 error retries with exponential backoff and succeeds on attempt 3."""
    fake = FakeClock()
    call_count = 0
    events: list[tuple[int, str, float]] = []

    async def _operation() -> str:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise HttpError(
                status_code=503,
                message="Service Unavailable",
                provider="TestProvider",
            )
        return "recovered"

    policy = RetryPolicy(
        max_retries=3,
        base_delay_seconds=0.5,
        backoff_factor=2.0,
        jitter=False,
    )

    def _on_event(attempt: int, code: str, delay_ms: float) -> None:
        events.append((attempt, code, delay_ms))

    result = asyncio.run(
        call_with_retry(
            _operation,
            policy=policy,
            sleep=fake.sleep,
            clock=fake.clock,
            on_event=_on_event,
        )
    )

    assert result == "recovered"
    assert call_count == 3
    # Attempt 1 failed -> backoff 0.5s; Attempt 2 failed -> backoff 1.0s
    assert fake.sleep_calls == [0.5, 1.0]
    assert len(events) == 2
    assert events[0] == (1, "unknown_failure", 500.0)
    assert events[1] == (2, "unknown_failure", 1000.0)


# ==============================================================================
# 2. Exhaustion of Retries & Time Budget
# ==============================================================================


def test_exhausts_configured_retry_attempts() -> None:
    """When failures persist past max_retries, raises with attempt metrics."""
    fake = FakeClock()
    call_count = 0

    async def _operation() -> None:
        nonlocal call_count
        call_count += 1
        raise TimeoutError("Persistent provider timeout", provider="TestProvider")

    policy = RetryPolicy(
        max_retries=2,
        base_delay_seconds=0.5,
        backoff_factor=2.0,
        jitter=False,
    )

    with pytest.raises(TimeoutError) as exc_info:
        asyncio.run(
            call_with_retry(
                _operation,
                policy=policy,
                sleep=fake.sleep,
                clock=fake.clock,
            )
        )

    err = exc_info.value
    # 1 initial attempt + 2 retries = 3 total attempts
    assert call_count == 3
    assert err.attempts == 3
    assert err.details.get("attempts") == 3
    assert fake.sleep_calls == [0.5, 1.0]


def test_exhausts_total_time_budget() -> None:
    """Aborts immediately when accumulated wait time exceeds total_budget_seconds."""
    fake = FakeClock()
    call_count = 0

    async def _operation() -> None:
        nonlocal call_count
        call_count += 1
        raise TimeoutError("Slow provider timeout", provider="TestProvider")

    # Budget is 1.0s. Delay 1 is 0.8s; Delay 2 is 1.6s -> 0.8 + 1.6 = 2.4s > 1.0s!
    policy = RetryPolicy(
        max_retries=5,
        base_delay_seconds=0.8,
        backoff_factor=2.0,
        total_budget_seconds=1.0,
        jitter=False,
    )

    with pytest.raises(TimeoutError) as exc_info:
        asyncio.run(
            call_with_retry(
                _operation,
                policy=policy,
                sleep=fake.sleep,
                clock=fake.clock,
            )
        )

    err = exc_info.value
    assert err.details.get("budget_exhausted") is True
    # Initial attempt (slept 0.8s) + second attempt triggered budget exhaustion
    assert call_count == 2
    assert fake.sleep_calls == [0.8]
    assert err.attempts == 2


# ==============================================================================
# 3. Non-Retryable Error Enforcement (Never Retried)
# ==============================================================================


def test_authentication_failure_never_retried() -> None:
    """HTTP 401/403 authentication failures fail immediately on attempt 1."""
    fake = FakeClock()
    call_count = 0

    async def _operation() -> None:
        nonlocal call_count
        call_count += 1
        raise HttpError(
            status_code=401,
            message="Unauthorized",
            provider="TestProvider",
        )

    with pytest.raises(HttpError) as exc_info:
        asyncio.run(
            call_with_retry(
                _operation,
                policy=RetryPolicy(max_retries=3),
                sleep=fake.sleep,
                clock=fake.clock,
            )
        )

    err = exc_info.value
    assert call_count == 1
    assert err.retryable is False
    assert err.attempts == 1
    assert fake.sleep_calls == []


def test_invalid_request_never_retried() -> None:
    """HTTP 400 client error fails immediately on attempt 1."""
    fake = FakeClock()
    call_count = 0

    async def _operation() -> None:
        nonlocal call_count
        call_count += 1
        raise HttpError(
            status_code=400,
            message="Bad Request: parameter invalid",
            provider="TestProvider",
        )

    with pytest.raises(HttpError) as exc_info:
        asyncio.run(
            call_with_retry(
                _operation,
                policy=RetryPolicy(max_retries=3),
                sleep=fake.sleep,
                clock=fake.clock,
            )
        )

    err = exc_info.value
    assert call_count == 1
    assert err.retryable is False
    assert err.attempts == 1
    assert fake.sleep_calls == []


def test_invalid_response_never_retried() -> None:
    """Malformed response schema violation fails immediately on attempt 1."""
    fake = FakeClock()
    call_count = 0

    async def _operation() -> None:
        nonlocal call_count
        call_count += 1
        raise MalformedResponseError(
            "Expected JSON dict but received array",
            provider="TestProvider",
        )

    with pytest.raises(MalformedResponseError) as exc_info:
        asyncio.run(
            call_with_retry(
                _operation,
                policy=RetryPolicy(max_retries=3),
                sleep=fake.sleep,
                clock=fake.clock,
            )
        )

    err = exc_info.value
    assert call_count == 1
    assert err.retryable is False
    assert err.attempts == 1
    assert fake.sleep_calls == []


# ==============================================================================
# 4. Rate-Limiting & Retry-After Behavior
# ==============================================================================


def test_rate_limited_with_small_retry_after_retried() -> None:
    """HTTP 429 with Retry-After <= max_delay_seconds is retried with header delay."""
    fake = FakeClock()
    call_count = 0

    async def _operation() -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RateLimitExceededError(
                retry_after=1.5,
                message="Rate limit exceeded",
                provider="TestProvider",
            )
        return "rate_limit_cleared"

    policy = RetryPolicy(
        max_retries=2,
        base_delay_seconds=0.5,
        max_delay_seconds=4.0,
        jitter=True,
    )

    result = asyncio.run(
        call_with_retry(
            _operation,
            policy=policy,
            sleep=fake.sleep,
            clock=fake.clock,
        )
    )

    assert result == "rate_limit_cleared"
    assert call_count == 2
    # Exactly 1.5s from header, without backoff formula or jitter
    assert fake.sleep_calls == [1.5]


def test_rate_limited_with_large_retry_after_not_retried() -> None:
    """HTTP 429 with Retry-After > max_delay_seconds is NOT retried."""
    fake = FakeClock()
    call_count = 0

    async def _operation() -> None:
        nonlocal call_count
        call_count += 1
        raise RateLimitExceededError(
            retry_after=10.0,
            message="Rate limit exceeded",
            provider="TestProvider",
        )

    policy = RetryPolicy(
        max_retries=3,
        max_delay_seconds=4.0,
    )

    with pytest.raises(RateLimitExceededError) as exc_info:
        asyncio.run(
            call_with_retry(
                _operation,
                policy=policy,
                sleep=fake.sleep,
                clock=fake.clock,
            )
        )

    err = exc_info.value
    assert call_count == 1
    assert err.retryable is False
    assert err.attempts == 1
    assert fake.sleep_calls == []


def test_rate_limited_without_retry_after_not_retried() -> None:
    """HTTP 429 with no Retry-After header is treated as non-retryable."""
    fake = FakeClock()
    call_count = 0

    async def _operation() -> None:
        nonlocal call_count
        call_count += 1
        raise RateLimitExceededError(
            retry_after=None,
            message="Rate limit exceeded",
            provider="TestProvider",
        )

    with pytest.raises(RateLimitExceededError):
        asyncio.run(
            call_with_retry(
                _operation,
                policy=RetryPolicy(max_retries=3),
                sleep=fake.sleep,
                clock=fake.clock,
            )
        )

    assert call_count == 1
    assert fake.sleep_calls == []


# ==============================================================================
# 5. Backoff Math, Jitter & Max Delay Clamping
# ==============================================================================


def test_delay_sequence_matches_exponential_policy() -> None:
    """Verifies delay progression: base * (factor ^ attempt) clamped to max_delay."""
    fake = FakeClock()
    call_count = 0

    async def _operation() -> None:
        nonlocal call_count
        call_count += 1
        raise TimeoutError("Timeout", provider="TestProvider")

    policy = RetryPolicy(
        max_retries=4,
        base_delay_seconds=0.5,
        backoff_factor=2.0,
        max_delay_seconds=3.0,
        jitter=False,
    )

    with pytest.raises(TimeoutError):
        asyncio.run(
            call_with_retry(
                _operation,
                policy=policy,
                sleep=fake.sleep,
                clock=fake.clock,
            )
        )

    # 4 retries:
    # Attempt 1: 0.5 * 2^0 = 0.5s
    # Attempt 2: 0.5 * 2^1 = 1.0s
    # Attempt 3: 0.5 * 2^2 = 2.0s
    # Attempt 4: 0.5 * 2^3 = 4.0s -> clamped to max_delay 3.0s
    assert fake.sleep_calls == [0.5, 1.0, 2.0, 3.0]


def test_full_jitter_uses_random_source() -> None:
    """Full jitter calls random_source(0.0, capped_delay) deterministically."""
    fake = FakeClock()
    call_count = 0
    random_calls: list[tuple[float, float]] = []

    def _mock_random(low: float, high: float) -> float:
        random_calls.append((low, high))
        return high * 0.5  # Return midpoint deterministically

    async def _operation() -> None:
        nonlocal call_count
        call_count += 1
        raise TimeoutError("Timeout", provider="TestProvider")

    policy = RetryPolicy(
        max_retries=2,
        base_delay_seconds=1.0,
        backoff_factor=2.0,
        max_delay_seconds=10.0,
        jitter=True,
    )

    with pytest.raises(TimeoutError):
        asyncio.run(
            call_with_retry(
                _operation,
                policy=policy,
                sleep=fake.sleep,
                clock=fake.clock,
                random_source=_mock_random,
            )
        )

    assert random_calls == [(0.0, 1.0), (0.0, 2.0)]
    assert fake.sleep_calls == [0.5, 1.0]


def test_max_retries_zero_disables_retry() -> None:
    """When max_retries is 0, failures immediately raise on attempt 1."""
    fake = FakeClock()
    call_count = 0

    async def _operation() -> None:
        nonlocal call_count
        call_count += 1
        raise TimeoutError("Timeout", provider="TestProvider")

    policy = RetryPolicy(max_retries=0)

    with pytest.raises(TimeoutError) as exc_info:
        asyncio.run(
            call_with_retry(
                _operation,
                policy=policy,
                sleep=fake.sleep,
                clock=fake.clock,
            )
        )

    assert call_count == 1
    assert exc_info.value.attempts == 1
    assert fake.sleep_calls == []


# ==============================================================================
# 6. Safety & Edge Cases
# ==============================================================================


def test_non_provider_error_propagates_immediately() -> None:
    """Standard Python exceptions are never caught or retried."""
    fake = FakeClock()
    call_count = 0

    async def _operation() -> None:
        nonlocal call_count
        call_count += 1
        raise ValueError("Invalid internal argument")

    with pytest.raises(ValueError, match="Invalid internal argument"):
        asyncio.run(
            call_with_retry(
                _operation,
                policy=RetryPolicy(max_retries=3),
                sleep=fake.sleep,
                clock=fake.clock,
            )
        )

    assert call_count == 1
    assert fake.sleep_calls == []


def test_sync_callable_supported() -> None:
    """Synchronous functions are supported seamlessly by call_with_retry."""
    fake = FakeClock()
    call_count = 0

    def _sync_operation() -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise TimeoutError("Sync timeout", provider="TestProvider")
        return "sync_success"

    result = asyncio.run(
        call_with_retry(
            _sync_operation,
            policy=RetryPolicy(max_retries=2, jitter=False),
            sleep=fake.sleep,
            clock=fake.clock,
        )
    )

    assert result == "sync_success"
    assert call_count == 2
    assert len(fake.sleep_calls) == 1


def test_zero_real_sleeping_and_speed() -> None:
    """Test suite must complete in less than 50 milliseconds using test doubles."""
    fake = FakeClock()

    async def _operation() -> None:
        raise TimeoutError("Simulated timeout", provider="TestProvider")

    policy = RetryPolicy(
        max_retries=5,
        base_delay_seconds=1.0,
        backoff_factor=2.0,
        max_delay_seconds=10.0,
        total_budget_seconds=100.0,
        jitter=False,
    )

    start_wall = time.monotonic()
    with pytest.raises(TimeoutError):
        asyncio.run(
            call_with_retry(
                _operation,
                policy=policy,
                sleep=fake.sleep,
                clock=fake.clock,
            )
        )
    elapsed_wall = time.monotonic() - start_wall

    # 5 retries of 1s, 2s, 4s, 8s, 10s = 25s of virtual time
    assert fake.current_time == 25.0
    # Wall clock execution time is virtually instant (< 50ms)
    assert elapsed_wall < 0.05


def test_policy_post_init_validation() -> None:
    """RetryPolicy validates invalid configuration arguments on instantiation."""
    with pytest.raises(ValueError, match="max_retries cannot be negative"):
        RetryPolicy(max_retries=-1)

    with pytest.raises(ValueError, match="base_delay_seconds cannot be negative"):
        RetryPolicy(base_delay_seconds=-0.5)

    with pytest.raises(ValueError, match="backoff_factor must be >= 1.0"):
        RetryPolicy(backoff_factor=0.5)

    with pytest.raises(ValueError, match="max_delay_seconds cannot be negative"):
        RetryPolicy(max_delay_seconds=-2.0)

    with pytest.raises(ValueError, match="total_budget_seconds must be positive"):
        RetryPolicy(total_budget_seconds=0.0)


# ==============================================================================
# 7. OpenMeteoClient Integration with call_with_retry
# ==============================================================================


def test_open_meteo_client_uses_injected_retry_doubles() -> None:
    """OpenMeteoClient accepts retry test doubles without real sleeping."""
    fake = FakeClock()
    events: list[tuple[int, str, float]] = []

    client = OpenMeteoClient(
        retry_sleep=fake.sleep,
        retry_clock=fake.clock,
        retry_on_event=lambda att, code, ms: events.append((att, code, ms)),
        retry_random=lambda low, high: high,
    )

    assert client._retry_sleep == fake.sleep
    assert client._retry_clock == fake.clock


def test_open_meteo_client_retries_5xx_with_injected_doubles() -> None:
    """OpenMeteoClient executes retry loop using injected doubles on HTTP 500."""
    import httpx

    fake = FakeClock()
    events: list[tuple[int, str, float]] = []
    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(500, text="Temporary Upstream Glitch")
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": 1,
                        "name": "Tokyo",
                        "latitude": 35.6895,
                        "longitude": 139.6917,
                        "country": "Japan",
                        "timezone": "Asia/Tokyo",
                    }
                ]
            },
        )

    transport = httpx.MockTransport(_handler)
    client = OpenMeteoClient(
        transport=transport,
        retry_sleep=fake.sleep,
        retry_clock=fake.clock,
        retry_on_event=lambda att, code, ms: events.append((att, code, ms)),
        retry_random=lambda low, high: high,
    )

    results = asyncio.run(client.search_destination("Tokyo"))

    assert len(results) == 1
    assert results[0].name == "Tokyo"
    assert call_count == 2
    assert len(fake.sleep_calls) == 1
    assert len(events) == 1
    assert events[0][0] == 1  # attempt 1
    assert events[0][1] == "unknown_failure"  # 500 mapped to unknown_failure
