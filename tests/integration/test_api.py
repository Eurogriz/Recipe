"""Integration tests for the FastAPI REST facade."""

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


@pytest_asyncio.fixture
async def api_client(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    """Build a fresh app + client backed by an isolated temp SQLite file."""
    reset_settings_cache()
    db_file = tmp_path / "api.db"

    # Pre-create schema so the API can boot with an empty catalog.
    db = Database.from_url(url=f"sqlite+aiosqlite:///{db_file}")
    await db.init()
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await db.close()

    settings = AppSettings(
        environment="development",
        database_url=f"sqlite+aiosqlite:///{db_file}",
        api_token="",
        metrics_enabled=True,
    )
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Trigger lifespan startup
        async with app.router.lifespan_context(app):
            yield client


async def test_health_returns_ok(api_client: AsyncClient) -> None:
    response = await api_client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["environment"] == "development"
    assert "version" in body


async def test_catalog_stats_empty(api_client: AsyncClient) -> None:
    response = await api_client.get("/catalog/stats")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert set(body["by_status"].keys()) == {"Draft", "PendingReview", "Verified", "Rejected"}


async def test_search_returns_empty_list(api_client: AsyncClient) -> None:
    response = await api_client.get("/recipes", params={"q": "acrylic"})
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["has_more"] is False


async def test_unknown_recipe_returns_404(api_client: AsyncClient) -> None:
    response = await api_client.get("/recipes/does-not-exist")
    assert response.status_code == 404


async def test_metrics_endpoint(api_client: AsyncClient) -> None:
    response = await api_client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert b"python_gc_objects_collected_total" in response.content


async def test_request_id_header(api_client: AsyncClient) -> None:
    response = await api_client.get("/health")
    assert "x-request-id" in response.headers
    assert "x-response-time-ms" in response.headers


async def test_auth_required_when_token_configured(tmp_path: Path) -> None:
    reset_settings_cache()
    db_file = tmp_path / "api-auth.db"
    db = Database.from_url(url=f"sqlite+aiosqlite:///{db_file}")
    await db.init()
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await db.close()

    settings = AppSettings(
        environment="staging",
        database_url=f"sqlite+aiosqlite:///{db_file}",
        api_token="s3cret-token",
    )
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            # No token → 401
            r = await client.get("/recipes")
            assert r.status_code == 401
            # Wrong token → 401
            r = await client.get("/recipes", headers={"Authorization": "Bearer nope"})
            assert r.status_code == 401
            # Correct token → 200
            r = await client.get("/recipes", headers={"Authorization": "Bearer s3cret-token"})
            assert r.status_code == 200
            # Health is public (no dependency on token)
            r = await client.get("/health")
            assert r.status_code == 200
