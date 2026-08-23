"""Small helpers to wire business metrics into async use cases."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from functools import wraps
from typing import Any, TypeVar

from .metrics import get_recipe_operation_seconds, get_recipe_operations_total

_T = TypeVar("_T")


@asynccontextmanager
async def observe_operation(operation: str) -> AsyncIterator[None]:
    """Record latency + success/failure counter for ``operation``."""
    started = time.perf_counter()
    outcome = "success"
    try:
        yield
    except Exception:
        outcome = "failure"
        raise
    finally:
        elapsed = time.perf_counter() - started
        get_recipe_operation_seconds().labels(operation=operation).observe(elapsed)
        get_recipe_operations_total().labels(operation=operation, outcome=outcome).inc()


def observed(
    operation: str,
) -> Callable[[Callable[..., Awaitable[_T]]], Callable[..., Awaitable[_T]]]:
    """Decorator wrapping an async method with :func:`observe_operation`."""

    def decorator(func: Callable[..., Awaitable[_T]]) -> Callable[..., Awaitable[_T]]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> _T:
            async with observe_operation(operation):
                return await func(*args, **kwargs)

        return wrapper

    return decorator


__all__ = ["observe_operation", "observed"]
