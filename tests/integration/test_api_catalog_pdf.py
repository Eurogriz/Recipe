"""Integration test for GET /catalog/export.pdf."""

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


def _recipe(subcat: str) -> dict:
    return {
        "category": "Краски",
        "subcategory": subcat,
        "binder_type": "Acrylic",
        "product_class": "Standard",
        "intended_use": f"Testing {subcat}",
        "stages": [
            {
                "stage_number": 1,
                "name": "Mix",
                "description": "",
                "components": [
                    {
                        "name": "Water",
                        "cas_number": "7732-18-5",
                        "function": "vehicle",
                        "mass_percent": 50.0,
                    },
                    {
                        "name": "Binder",
                        "cas_number": "mixture",
                        "function": "binder",
                        "mass_percent": 30.0,
                    },
                    {
                        "name": "TiO2",
                        "cas_number": "13463-67-7",
                        "function": "pigment",
                        "mass_percent": 20.0,
                    },
                ],
                "process": {"equipment": "Disperser"},
            }
        ],
        "primary_source": {
            "authors": "Flick",
            "title": "WBPF",
            "year": 1995,
            "publisher": "Noyes Publications",
            "isbn": "9780815513773",
        },
        "cross_references": [],
    }


@pytest_asyncio.fixture
async def api(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    reset_settings_cache()
    db = tmp_path / "cat.db"
    dbc = Database.from_url(url=f"sqlite+aiosqlite:///{db}")
    await dbc.init()
    async with dbc.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await dbc.close()
    settings = AppSettings(
        environment="development",
        database_url=f"sqlite+aiosqlite:///{db}",
        api_token="",
        rate_limit_enabled=False,
        model_dir=tmp_path / "models",
    )
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


async def test_catalog_pdf_streams_all_recipes(api: AsyncClient) -> None:
    for name in ("first", "second", "third"):
        await api.post("/recipes", json=_recipe(name))

    r = await api.get("/catalog/export.pdf?limit=10")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert "attachment" in r.headers["content-disposition"]
    # Valid PDF header + non-trivial size (TOC + 3 recipe pages).
    assert r.content[:4] == b"%PDF"
    assert len(r.content) > 2500


async def test_catalog_pdf_404_when_empty(api: AsyncClient) -> None:
    r = await api.get("/catalog/export.pdf")
    assert r.status_code == 404


async def test_catalog_pdf_respects_category_filter(api: AsyncClient) -> None:
    # Two categories: only the paints filter should hit.
    await api.post("/recipes", json=_recipe("kra1"))
    await api.post("/recipes", json=_recipe("kra2"))

    r = await api.get("/catalog/export.pdf?category=Клеи")
    assert r.status_code == 404  # no glue recipes in this dataset

    r = await api.get("/catalog/export.pdf?category=%D0%9A%D1%80%D0%B0%D1%81%D0%BA%D0%B8")
    assert r.status_code == 200
    disposition = r.headers["content-disposition"]
    # ASCII filename fallback + RFC-5987 filename* for the localised name.
    assert 'filename="catalog_' in disposition
    assert "filename*=UTF-8''" in disposition
