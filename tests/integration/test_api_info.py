"""Tests for the new /info endpoint and business Prometheus metrics."""

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
async def api(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    reset_settings_cache()
    db_file = tmp_path / "info.db"
    db = Database.from_url(url=f"sqlite+aiosqlite:///{db_file}")
    await db.init()
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await db.close()

    settings = AppSettings(
        environment="development",
        database_url=f"sqlite+aiosqlite:///{db_file}",
        api_token="",
        rate_limit_enabled=False,
    )
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


async def test_info_endpoint(api: AsyncClient) -> None:
    r = await api.get("/info")
    assert r.status_code == 200
    body = r.json()
    for key in ("name", "version", "environment", "python", "platform"):
        assert body[key], f"missing/empty {key}"
    assert body["name"] == "formulation-workbench"


async def test_metrics_include_business_series(api: AsyncClient) -> None:
    # Trigger a use case so counters/histograms populate.
    await api.get("/recipes", params={"q": "acrylic"})
    await api.get("/catalog/stats")

    r = await api.get("/metrics")
    assert r.status_code == 200
    body = r.text
    assert "formulation_app_info" in body
    assert "formulation_recipe_operations_total" in body
    assert "formulation_recipe_operation_seconds" in body
    assert "formulation_catalog_size" in body
