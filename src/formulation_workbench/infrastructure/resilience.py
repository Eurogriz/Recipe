"""Retry + circuit breaker primitives for external adapters.

Kept dependency-free so we can use them wherever the runtime crosses a
trust or reliability boundary (1С CommerceML import, ML model warm-up,
future HTTP integrations).  Public API:

- :func:`with_retry` — synchronous retry with exponential backoff + jitter.
- :func:`with_retry_async` — the same, ``await``-friendly.
- :class:`CircuitBreaker` — closed → open → half-open state machine.
- :class:`CircuitBreakerOpen` — raised when calls are short-circuited.
"""

from __future__ import annotations

import asyncio
import logging
import random
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


# ---------------------------------------------------------------------------
# Retry helpers
# ---------------------------------------------------------------------------
def _sleep(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


async def _asleep(seconds: float) -> None:
    if seconds > 0:
        await asyncio.sleep(seconds)


def _delay(attempt: int, base: float, cap: float) -> float:
    """Exponential backoff with equal-jitter (see AWS Architecture Blog).

    Uses ``random.uniform`` — cryptographic randomness is not needed here.
    """
    exp = min(cap, base * (2 ** (attempt - 1)))
    jitter: float = random.uniform(0, exp / 2)
    return float(exp / 2 + jitter)


def with_retry(
    func: Callable[..., _T],
    *args: Any,
    attempts: int = 3,
    base_delay: float = 0.2,
    max_delay: float = 5.0,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    **kwargs: Any,
) -> _T:
    """Call ``func`` up to ``attempts`` times, backing off between failures."""
    last_error: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return func(*args, **kwargs)
        except retry_on as exc:
            last_error = exc
            if attempt == attempts:
                break
            wait = _delay(attempt, base_delay, max_delay)
            logger.warning(
                "retry_attempt_failed",
                extra={
                    "attempt": attempt,
                    "attempts": attempts,
                    "wait_seconds": round(wait, 3),
                    "error": repr(exc),
                },
            )
            _sleep(wait)
    assert last_error is not None
    raise last_error


async def with_retry_async(
    func: Callable[..., Awaitable[_T]],
    *args: Any,
    attempts: int = 3,
    base_delay: float = 0.2,
    max_delay: float = 5.0,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    **kwargs: Any,
) -> _T:
    """Async counterpart of :func:`with_retry`."""
    last_error: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await func(*args, **kwargs)
        except retry_on as exc:
            last_error = exc
            if attempt == attempts:
                break
            wait = _delay(attempt, base_delay, max_delay)
            logger.warning(
                "retry_attempt_failed",
                extra={
                    "attempt": attempt,
                    "attempts": attempts,
                    "wait_seconds": round(wait, 3),
                    "error": repr(exc),
                },
            )
            await _asleep(wait)
    assert last_error is not None
    raise last_error


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------
class CircuitBreakerOpen(RuntimeError):  # noqa: N818 — historical/public API name
    """Raised when a circuit breaker is open and rejects a call."""


@dataclass
class CircuitBreaker:
    """Simple 3-state circuit breaker.

    Rules:

    - **closed**: every call goes through; each failure increments the
      counter, ``failure_threshold`` consecutive failures move the state
      to *open*.
    - **open**: calls are rejected with :class:`CircuitBreakerOpen` until
      ``recovery_seconds`` pass; then the state moves to *half-open*.
    - **half-open**: the next call is allowed; success closes the circuit,
      failure re-opens it.
    """

    name: str
    failure_threshold: int = 5
    recovery_seconds: float = 30.0
    _failures: int = field(default=0, init=False, repr=False)
    _opened_at: float = field(default=0.0, init=False, repr=False)
    _state: str = field(default="closed", init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    @property
    def state(self) -> str:
        return self._state

    def _allow(self) -> bool:
        with self._lock:
            if self._state == "closed":
                return True
            if self._state == "open":
                if time.monotonic() - self._opened_at >= self.recovery_seconds:
                    self._state = "half-open"
                    logger.info("circuit_breaker_half_open", extra={"breaker": self.name})
                    return True
                return False
            # half-open: allow a single probe
            return True

    def _on_success(self) -> None:
        with self._lock:
            self._failures = 0
            if self._state != "closed":
                logger.info("circuit_breaker_closed", extra={"breaker": self.name})
            self._state = "closed"

    def _on_failure(self, exc: BaseException) -> None:
        with self._lock:
            self._failures += 1
            if self._state == "half-open" or self._failures >= self.failure_threshold:
                self._state = "open"
                self._opened_at = time.monotonic()
                logger.warning(
                    "circuit_breaker_opened",
                    extra={
                        "breaker": self.name,
                        "failures": self._failures,
                        "error": repr(exc),
                    },
                )

    def call(self, func: Callable[..., _T], *args: Any, **kwargs: Any) -> _T:
        if not self._allow():
            raise CircuitBreakerOpen(f"circuit '{self.name}' is open")
        try:
            result = func(*args, **kwargs)
        except Exception as exc:
            self._on_failure(exc)
            raise
        self._on_success()
        return result

    async def call_async(self, func: Callable[..., Awaitable[_T]], *args: Any, **kwargs: Any) -> _T:
        if not self._allow():
            raise CircuitBreakerOpen(f"circuit '{self.name}' is open")
        try:
            result = await func(*args, **kwargs)
        except Exception as exc:
            self._on_failure(exc)
            raise
        self._on_success()
        return result


__all__ = [
    "CircuitBreaker",
    "CircuitBreakerOpen",
    "with_retry",
    "with_retry_async",
]
