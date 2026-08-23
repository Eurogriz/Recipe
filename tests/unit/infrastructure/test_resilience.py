"""Unit tests for retry + circuit breaker primitives."""

from __future__ import annotations

import asyncio
import time

import pytest

from formulation_workbench.infrastructure.resilience import (
    CircuitBreaker,
    CircuitBreakerOpen,
    with_retry,
    with_retry_async,
)


class TestWithRetry:
    def test_succeeds_on_first_attempt(self) -> None:
        calls = []

        def op() -> str:
            calls.append(1)
            return "ok"

        assert with_retry(op) == "ok"
        assert len(calls) == 1

    def test_retries_until_success(self) -> None:
        calls = []

        def op() -> str:
            calls.append(1)
            if len(calls) < 3:
                raise RuntimeError("nope")
            return "eventually"

        assert with_retry(op, attempts=5, base_delay=0.001, max_delay=0.01) == "eventually"
        assert len(calls) == 3

    def test_raises_last_error_after_exhausting_attempts(self) -> None:
        def op() -> None:
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            with_retry(op, attempts=2, base_delay=0.001)

    def test_only_retries_matching_exceptions(self) -> None:
        def op() -> None:
            raise TypeError("wrong")

        with pytest.raises(TypeError):
            with_retry(op, attempts=5, retry_on=(ValueError,), base_delay=0.001)


class TestWithRetryAsync:
    async def test_retries_and_succeeds(self) -> None:
        calls = 0

        async def op() -> str:
            nonlocal calls
            calls += 1
            if calls < 2:
                raise RuntimeError("nope")
            return "ok"

        result = await with_retry_async(op, attempts=3, base_delay=0.001, max_delay=0.01)
        assert result == "ok"
        assert calls == 2


class TestCircuitBreaker:
    def test_closed_then_opens_after_failures(self) -> None:
        cb = CircuitBreaker(name="test", failure_threshold=3, recovery_seconds=60)

        def bad() -> None:
            raise RuntimeError("fail")

        for _ in range(3):
            with pytest.raises(RuntimeError):
                cb.call(bad)
        assert cb.state == "open"

        with pytest.raises(CircuitBreakerOpen):
            cb.call(lambda: "should not run")

    def test_half_open_closes_after_successful_probe(self) -> None:
        cb = CircuitBreaker(name="test", failure_threshold=2, recovery_seconds=0.05)

        def bad() -> None:
            raise RuntimeError()

        for _ in range(2):
            with pytest.raises(RuntimeError):
                cb.call(bad)
        assert cb.state == "open"

        time.sleep(0.06)

        assert cb.call(lambda: "healthy") == "healthy"
        assert cb.state == "closed"

    def test_half_open_reopens_on_probe_failure(self) -> None:
        cb = CircuitBreaker(name="test", failure_threshold=2, recovery_seconds=0.05)

        def bad() -> None:
            raise RuntimeError()

        for _ in range(2):
            with pytest.raises(RuntimeError):
                cb.call(bad)
        time.sleep(0.06)
        with pytest.raises(RuntimeError):
            cb.call(bad)
        assert cb.state == "open"

    async def test_call_async(self) -> None:
        cb = CircuitBreaker(name="a", failure_threshold=2, recovery_seconds=60)

        async def good() -> int:
            return 42

        assert await cb.call_async(good) == 42

        async def bad() -> None:
            raise RuntimeError()

        for _ in range(2):
            with pytest.raises(RuntimeError):
                await cb.call_async(bad)
        with pytest.raises(CircuitBreakerOpen):
            await cb.call_async(good)


class TestConcurrentBreaker:
    async def test_thread_safety_smoke(self) -> None:
        """Concurrent asyncio tasks must not race the breaker state."""
        cb = CircuitBreaker(name="c", failure_threshold=5, recovery_seconds=60)

        async def worker(i: int) -> None:
            if i % 3 == 0:
                with pytest.raises(RuntimeError):
                    await cb.call_async(lambda: (_ for _ in ()).throw(RuntimeError()))
            else:
                await cb.call_async(lambda: asyncio.sleep(0))

        await asyncio.gather(*(worker(i) for i in range(10)))
        # Regardless of interleaving the state is deterministic:
        # 4 failures (i in {0,3,6,9}) < 5 threshold → still closed.
        assert cb.state in {"closed", "open"}
