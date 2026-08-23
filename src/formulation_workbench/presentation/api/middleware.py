"""Custom middleware for the FastAPI facade.

Each middleware is deliberately small and does one thing so that they can
be stacked and unit-tested in isolation:

- :class:`RequestContextMiddleware` — assigns / propagates a request id,
  measures latency, and logs a structured summary of every response.
- :class:`SecurityHeadersMiddleware` — adds hardened response headers
  suitable for a JSON API.
- :class:`RateLimitMiddleware` — an in-process token bucket that protects
  the service from accidental floods (per-token, else per-IP).
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Request context / structured logging
# ---------------------------------------------------------------------------
class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a request id and emit one structured log per request."""

    _HEADER = "x-request-id"

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        rid = request.headers.get(self._HEADER) or uuid.uuid4().hex
        started = time.perf_counter()

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=rid,
            method=request.method,
            path=request.url.path,
        )
        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.exception(
                "request_failed",
                duration_ms=round(elapsed_ms, 2),
            )
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal server error", "code": "internal_error"},
                headers={self._HEADER: rid},
            )

        elapsed_ms = (time.perf_counter() - started) * 1000
        response.headers[self._HEADER] = rid
        response.headers["x-response-time-ms"] = f"{elapsed_ms:.1f}"
        logger.info(
            "request",
            status=response.status_code,
            duration_ms=round(elapsed_ms, 2),
        )
        structlog.contextvars.clear_contextvars()
        return response


# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------
_SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "accelerometer=(), camera=(), geolocation=(), microphone=()",
    # A JSON API has no need for scripts / frames / images.
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    # HSTS is meaningful only over HTTPS; keeping the header is harmless in HTTP
    # environments and forwards through TLS-terminating proxies.
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add a curated set of security headers to every response."""

    def __init__(self, app: ASGIApp, extra: dict[str, str] | None = None) -> None:
        super().__init__(app)
        self._headers = dict(_SECURITY_HEADERS)
        if extra:
            self._headers.update(extra)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        for name, value in self._headers.items():
            response.headers.setdefault(name, value)
        # Swagger UI / ReDoc need scripts + iframes; loosen CSP just for them.
        if request.url.path in {"/docs", "/redoc", "/docs/oauth2-redirect"}:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self' https://cdn.jsdelivr.net data: blob:; "
                "img-src 'self' https: data:; "
                "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
                "script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
                "worker-src 'self' blob:; "
                "connect-src 'self'"
            )
            response.headers["X-Frame-Options"] = "SAMEORIGIN"
        return response


# ---------------------------------------------------------------------------
# In-process rate limiter (token bucket per client key)
# ---------------------------------------------------------------------------
class RateLimitMiddleware(BaseHTTPMiddleware):
    """Cap client request rate using a sliding-window log per client key.

    Client key priority:

        1. ``Authorization: Bearer <token>`` — one bucket per token.
        2. ``X-Forwarded-For`` first hop (if the deployment sets a trusted proxy).
        3. Direct peer IP.

    ``requests_per_minute`` is a soft ceiling; healthchecks are exempt so
    orchestrators are never throttled.
    """

    _EXEMPT_PATHS = frozenset({"/health", "/metrics"})

    def __init__(
        self,
        app: ASGIApp,
        requests_per_minute: int = 120,
        window_seconds: int = 60,
    ) -> None:
        super().__init__(app)
        self._limit = max(1, requests_per_minute)
        self._window = max(1, window_seconds)
        self._buckets: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()

    def _client_key(self, request: Request) -> str:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            return "tok:" + auth.split(" ", 1)[1].strip()[:32]
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            return "ip:" + xff.split(",", 1)[0].strip()
        if request.client is not None:
            return "ip:" + request.client.host
        return "ip:unknown"

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.url.path in self._EXEMPT_PATHS:
            return await call_next(request)

        key = self._client_key(request)
        now = time.monotonic()
        cutoff = now - self._window

        async with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = deque()
                self._buckets[key] = bucket
            # Drop old timestamps.
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self._limit:
                retry_after = int(bucket[0] + self._window - now) + 1
                logger.warning(
                    "rate_limited",
                    client_key=key[:16],
                    limit=self._limit,
                    window=self._window,
                )
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": "Too many requests",
                        "code": "rate_limited",
                    },
                    headers={
                        "Retry-After": str(max(1, retry_after)),
                        "X-RateLimit-Limit": str(self._limit),
                        "X-RateLimit-Remaining": "0",
                    },
                )
            bucket.append(now)
            remaining = self._limit - len(bucket)

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self._limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response


# Backwards-compatible export.
with contextlib.suppress(NameError):
    __all__ = [
        "RateLimitMiddleware",
        "RequestContextMiddleware",
        "SecurityHeadersMiddleware",
    ]
