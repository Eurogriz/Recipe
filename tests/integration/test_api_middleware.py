"""Tests for the custom API middleware stack.

Covers:

- security headers on every response;
- rate limiting per client key;
- exemption of ``/health`` from rate limiting;
- graceful 500 handling by :class:`RequestContextMiddleware`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from formulation_workbench.infrastructure.config import AppSettings, reset_settings_cache
from formulation_workbench.infrastructure.db.connection import Database
from formulation_workbench.infrastructure.db.models import Base
from formulation_workbench.presentation.api.app import create_app

pytestmark = [pytest.mark.integration, pytest.mark.api]


async def _prepare_db(path: Path) -> None:
    db = Database.from_url(url=f"sqlite+aiosqlite:///{path}")
    await db.init()
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await db.close()


@pytest_asyncio.fixture
async def app_client(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    reset_settings_cache()
    db_file = tmp_path / "mw.db"
    await _prepare_db(db_file)

    settings = AppSettings(
        environment="development",
        database_url=f"sqlite+aiosqlite:///{db_file}",
        api_token="",
        rate_limit_enabled=True,
        rate_limit_per_minute=5,  # very tight — easy to exercise
    )
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


async def test_security_headers_present(app_client: AsyncClient) -> None:
    response = await app_client.get("/health")
    assert response.status_code == 200
    for header in (
        "X-Content-Type-Options",
        "X-Frame-Options",
        "Referrer-Policy",
        "Content-Security-Policy",
        "Cross-Origin-Opener-Policy",
        "Cross-Origin-Resource-Policy",
        "Permissions-Policy",
        "Strict-Transport-Security",
    ):
        assert header in response.headers, f"missing {header}"


async def test_docs_endpoint_has_relaxed_csp(app_client: AsyncClient) -> None:
    response = await app_client.get("/docs")
    assert response.status_code == 200
    csp = response.headers["Content-Security-Policy"]
    assert "cdn.jsdelivr.net" in csp
    assert response.headers["X-Frame-Options"] == "SAMEORIGIN"


async def test_rate_limit_kicks_in(app_client: AsyncClient) -> None:
    # 5 responses allowed; 6th must be 429.
    limited = 0
    for _ in range(7):
        r = await app_client.get("/recipes")
        if r.status_code == 429:
            limited += 1
    assert limited >= 1
    # After the first hit, the rate limit response carries a Retry-After.
    r = await app_client.get("/recipes")
    if r.status_code == 429:
        assert "Retry-After" in r.headers
        assert r.headers["X-RateLimit-Remaining"] == "0"


async def test_health_is_exempt_from_rate_limit(app_client: AsyncClient) -> None:
    # Exhaust the budget with regular calls first.
    for _ in range(6):
        await app_client.get("/recipes")
    r = await app_client.get("/health")
    assert r.status_code == 200


async def test_ratelimit_headers_on_normal_response(app_client: AsyncClient) -> None:
    r = await app_client.get("/recipes")
    assert r.status_code == 200
    assert "X-RateLimit-Limit" in r.headers
    assert "X-RateLimit-Remaining" in r.headers
    assert int(r.headers["X-RateLimit-Limit"]) == 5


async def test_request_id_is_echoed(app_client: AsyncClient) -> None:
    rid = "test-request-id-123"
    r = await app_client.get("/health", headers={"x-request-id": rid})
    assert r.headers["x-request-id"] == rid


async def test_unhandled_exception_returns_500(tmp_path: Path) -> None:
    """RequestContextMiddleware must convert exceptions into a 500 JSON body."""
    reset_settings_cache()
    db_file = tmp_path / "err.db"
    await _prepare_db(db_file)

    settings = AppSettings(
        environment="development",
        database_url=f"sqlite+aiosqlite:///{db_file}",
        api_token="",
        rate_limit_enabled=False,
    )
    app = create_app(settings)

    @app.get("/boom")
    async def _boom() -> None:  # pragma: no cover — exercised only in tests
        raise RuntimeError("kaboom")

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            r = await client.get("/boom")
    assert r.status_code == 500
    body = r.json()
    assert body["code"] == "internal_error"
    assert "x-request-id" in r.headers
