"""Integration test for /recipes/{id}/similar."""

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


def _recipe(binder_pct: float, pigment_pct: float = 20.0, *, category: str = "Краски") -> dict:
    water = round(100.0 - binder_pct - pigment_pct, 2)
    return {
        "category": category,
        "subcategory": "test",
        "binder_type": "Acrylic",
        "product_class": "Standard",
        "intended_use": "Test",
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
                        "mass_percent": water,
                    },
                    {
                        "name": "Acrylic",
                        "cas_number": "mixture",
                        "function": "binder",
                        "mass_percent": binder_pct,
                    },
                    {
                        "name": "TiO2",
                        "cas_number": "13463-67-7",
                        "function": "pigment",
                        "mass_percent": pigment_pct,
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
    db = tmp_path / "sim.db"
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


async def test_similar_returns_neighbours_sorted(api: AsyncClient) -> None:
    ref = (await api.post("/recipes", json=_recipe(30.0, 20.0))).json()["id"]
    close = (await api.post("/recipes", json=_recipe(31.0, 19.0))).json()["id"]
    far = (await api.post("/recipes", json=_recipe(60.0, 1.0))).json()["id"]
    other = (await api.post("/recipes", json=_recipe(30.0, 20.0, category="Клеи"))).json()["id"]

    r = await api.get(f"/recipes/{ref}/similar?top_k=5")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reference_recipe_id"] == ref
    assert body["same_category_only"] is True
    ids = [m["recipe_id"] for m in body["matches"]]
    assert ref not in ids
    assert other not in ids
    assert close in ids
    assert far in ids
    # Ordered by similarity descending.
    sims = [m["similarity"] for m in body["matches"]]
    assert sims == sorted(sims, reverse=True)


async def test_similar_404_for_missing_recipe(api: AsyncClient) -> None:
    r = await api.get("/recipes/does-not-exist/similar")
    assert r.status_code == 404


async def test_similar_respects_min_similarity(api: AsyncClient) -> None:
    ref = (await api.post("/recipes", json=_recipe(30.0, 20.0))).json()["id"]
    for pct in (30.1, 29.9, 60.0, 5.0):
        await api.post("/recipes", json=_recipe(pct, 20.0))
    r = await api.get(f"/recipes/{ref}/similar?top_k=10&min_similarity=0.99")
    body = r.json()
    for m in body["matches"]:
        assert m["similarity"] >= 0.99


async def test_similar_cross_category_when_flag_off(api: AsyncClient) -> None:
    ref = (await api.post("/recipes", json=_recipe(30.0, 20.0))).json()["id"]
    other = (await api.post("/recipes", json=_recipe(30.0, 20.0, category="Клеи"))).json()["id"]
    r = await api.get(f"/recipes/{ref}/similar?same_category_only=false")
    body = r.json()
    assert other in [m["recipe_id"] for m in body["matches"]]
