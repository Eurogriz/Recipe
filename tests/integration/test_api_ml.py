"""End-to-end tests for the ML endpoints (/ml/train, /ml/models, /predict)."""

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


def _valid_recipe(binder_pct: float) -> dict:
    water = round(100.0 - binder_pct - 10.0, 2)
    return {
        "category": "Краски",
        "subcategory": "Водно-дисперсионные",
        "binder_type": "Acrylic",
        "product_class": "Standard",
        "intended_use": "ML test",
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
                        "mass_percent": 10.0,
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
    db = tmp_path / "ml.db"
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


async def _seed_experiments(api: AsyncClient, n: int = 15) -> list[str]:
    """Create n recipes with linked completed experiments; return recipe ids."""
    recipe_ids: list[str] = []
    for i in range(n):
        binder = 20.0 + i * 3.0
        recipe = _valid_recipe(binder_pct=binder)
        created = (await api.post("/recipes", json=recipe)).json()
        rid = created["id"]
        recipe_ids.append(rid)

        exp = (
            await api.post(
                "/experiments",
                json={"recipe_id": rid, "recipe_version": 1, "operator": "alice"},
            )
        ).json()
        # Ground truth: gloss = 15 + 1.6 * binder + jitter (deterministic)
        gloss = 15.0 + 1.6 * binder + (i % 5) - 2
        viscosity = 100.0 + 25.0 * binder
        await api.post(
            f"/experiments/{exp['id']}/complete",
            json={
                "batch": {"batch_number": f"B-{i:03d}", "target_mass_kg": 5.0},
                "measured_properties": [
                    {"property_code": "gloss_60", "value": gloss},
                    {"property_code": "viscosity_mid_shear", "value": viscosity},
                ],
            },
        )
    return recipe_ids


async def test_train_and_predict_flow(api: AsyncClient) -> None:
    recipe_ids = await _seed_experiments(api, n=15)

    # 1. Train.
    r = await api.post(
        "/ml/train",
        json={"recipe_ids": recipe_ids},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    trained_codes = {m["property_code"] for m in body["trained"]}
    assert trained_codes == {"gloss_60", "viscosity_mid_shear"}
    for meta in body["trained"]:
        assert meta["n_samples"] == 15
        # v1.8.0 upgraded from plain RandomForest to a stacked
        # (RF + HistGradientBoosting → Ridge) ensemble.  Legacy models
        # persisted under the old algorithm name are still readable.
        assert "RandomForest" in meta["algorithm"] or "Stacking" in meta["algorithm"]
        assert meta["fingerprint"]

    # 2. List models.
    r = await api.get("/ml/models")
    assert r.status_code == 200
    listed = {m["property_code"] for m in r.json()}
    assert listed == {"gloss_60", "viscosity_mid_shear"}

    # 3. Predict on one of the recipes.
    r = await api.get(f"/recipes/{recipe_ids[7]}/predict")
    assert r.status_code == 200
    payload = r.json()
    codes = {p["property_code"] for p in payload["predictions"]}
    assert codes == {"gloss_60", "viscosity_mid_shear"}
    for p in payload["predictions"]:
        assert p["model_version"]
        assert p["predicted_value"] > 0


async def test_train_no_data_returns_empty(api: AsyncClient) -> None:
    # No recipes seeded → training runs but produces nothing.
    r = await api.post("/ml/train", json={"recipe_ids": []})
    assert r.status_code == 200
    body = r.json()
    assert body["trained"] == []
    assert body["skipped"] == {}


async def test_predict_without_models_returns_empty_list(api: AsyncClient) -> None:
    created = (await api.post("/recipes", json=_valid_recipe(binder_pct=40.0))).json()
    r = await api.get(f"/recipes/{created['id']}/predict")
    assert r.status_code == 200
    assert r.json()["predictions"] == []


async def test_predict_missing_recipe_returns_404(api: AsyncClient) -> None:
    r = await api.get("/recipes/nope/predict")
    assert r.status_code == 404


async def test_openapi_declares_ml_endpoints(api: AsyncClient) -> None:
    paths = (await api.get("/openapi.json")).json()["paths"]
    for expected in ("/ml/train", "/ml/models", "/recipes/{recipe_id}/predict"):
        assert expected in paths, expected
