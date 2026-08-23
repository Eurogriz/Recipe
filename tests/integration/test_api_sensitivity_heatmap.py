"""Integration tests for POST /recipes/{id}/sensitivity-heatmap."""

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


def _recipe(binder_pct: float, pigment_pct: float = 20.0) -> dict:
    water = round(100.0 - binder_pct - pigment_pct, 2)
    return {
        "category": "Краски",
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
    db = tmp_path / "heat.db"
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


async def _seed_with_models(api: AsyncClient, n: int = 12) -> str:
    ids: list[str] = []
    for i in range(n):
        binder = 20.0 + i * 3.0
        r = (await api.post("/recipes", json=_recipe(binder))).json()
        rid = r["id"]
        ids.append(rid)
        exp = (
            await api.post(
                "/experiments",
                json={"recipe_id": rid, "recipe_version": 1, "operator": "alice"},
            )
        ).json()
        await api.post(
            f"/experiments/{exp['id']}/complete",
            json={
                "batch": {"batch_number": f"B-{i:03d}", "target_mass_kg": 5.0},
                "measured_properties": [
                    {"property_code": "gloss_60", "value": 90.0 - binder + (i % 5)},
                ],
            },
        )
    await api.post("/ml/train", json={"recipe_ids": ids})
    return ids[0]


async def test_heatmap_returns_grid(api: AsyncClient) -> None:
    rid = await _seed_with_models(api)
    r = await api.post(
        f"/recipes/{rid}/sensitivity-heatmap",
        json={
            "component_a": "TiO2",
            "component_b": "Acrylic",
            "property_code": "gloss_60",
            "a_min": 10.0,
            "a_max": 25.0,
            "b_min": 20.0,
            "b_max": 40.0,
            "steps_a": 4,
            "steps_b": 5,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["component_a"] == "TiO2"
    assert body["component_b"] == "Acrylic"
    assert len(body["a_values"]) == 4
    assert len(body["b_values"]) == 5
    assert len(body["values"]) == 4
    for row in body["values"]:
        assert len(row) == 5
    assert body["z_min"] is not None
    assert body["z_max"] is not None
    assert body["z_min"] <= body["z_max"]


async def test_heatmap_422_for_same_component(api: AsyncClient) -> None:
    rid = await _seed_with_models(api)
    r = await api.post(
        f"/recipes/{rid}/sensitivity-heatmap",
        json={
            "component_a": "TiO2",
            "component_b": "TiO2",
            "property_code": "gloss_60",
            "a_min": 10.0,
            "a_max": 25.0,
            "b_min": 20.0,
            "b_max": 40.0,
            "steps_a": 4,
            "steps_b": 4,
        },
    )
    assert r.status_code == 422


async def test_heatmap_404_for_unknown_recipe(api: AsyncClient) -> None:
    r = await api.post(
        "/recipes/does-not-exist/sensitivity-heatmap",
        json={
            "component_a": "TiO2",
            "component_b": "Acrylic",
            "property_code": "gloss_60",
            "a_min": 10.0,
            "a_max": 25.0,
            "b_min": 20.0,
            "b_max": 40.0,
        },
    )
    assert r.status_code == 404


async def test_heatmap_422_when_cell_cap_exceeded(api: AsyncClient) -> None:
    rid = await _seed_with_models(api)
    r = await api.post(
        f"/recipes/{rid}/sensitivity-heatmap",
        json={
            "component_a": "TiO2",
            "component_b": "Acrylic",
            "property_code": "gloss_60",
            "a_min": 10.0,
            "a_max": 25.0,
            "b_min": 20.0,
            "b_max": 40.0,
            "steps_a": 25,
            "steps_b": 25,  # 625 > 400
        },
    )
    assert r.status_code == 422
