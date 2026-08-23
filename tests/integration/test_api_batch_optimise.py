"""API tests for /batch-report and /optimise endpoints."""

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


def _recipe_body() -> dict:
    return {
        "category": "Краски",
        "subcategory": "Водно-дисперсионные",
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
                        "mass_percent": 40.0,
                    },
                    {
                        "name": "Acrylic",
                        "cas_number": "mixture",
                        "function": "binder",
                        "mass_percent": 40.0,
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
    db = tmp_path / "batch.db"
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


class TestBatchReport:
    async def test_batch_report_returns_cost_and_regulatory(self, api: AsyncClient) -> None:
        recipe = (await api.post("/recipes", json=_recipe_body())).json()
        rid = recipe["id"]

        exp = (
            await api.post(
                "/experiments",
                json={"recipe_id": rid, "recipe_version": 1, "operator": "alice"},
            )
        ).json()
        eid = exp["id"]
        await api.post(
            f"/experiments/{eid}/complete",
            json={
                "batch": {
                    "batch_number": "B-100",
                    "target_mass_kg": 20.0,
                    "actual_mass_kg": 19.8,
                    "lot_numbers": {"Water": "LOT-W", "Acrylic": "LOT-A", "TiO2": "LOT-T"},
                },
                "measured_properties": [{"property_code": "gloss_60", "value": 60.0}],
            },
        )
        r = await api.post(
            f"/experiments/{eid}/batch-report",
            json={
                "prices": [
                    {"component_name": "Water", "amount": 0.001, "currency": "EUR", "unit": "kg"},
                    {"component_name": "Acrylic", "amount": 3.00, "currency": "EUR", "unit": "kg"},
                    {"component_name": "TiO2", "amount": 4.50, "currency": "EUR", "unit": "kg"},
                ]
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["cost"]["currency"] == "EUR"
        # per-kg 2.1004 × 19.8 = 41.588
        assert 41.0 <= body["cost"]["total_cost"] <= 42.0
        # Lot numbers propagate.
        water_line = next(ln for ln in body["cost"]["lines"] if ln["component_name"] == "Water")
        assert water_line["lot_number"] == "LOT-W"
        # Mass balance yield ≈ 99 % → within tolerance.
        assert body["mass_balance"]["is_within_tolerance"]

    async def test_batch_report_404_missing_experiment(self, api: AsyncClient) -> None:
        r = await api.post("/experiments/nope/batch-report", json={"prices": []})
        assert r.status_code == 404

    async def test_batch_report_409_without_batch(self, api: AsyncClient) -> None:
        recipe = (await api.post("/recipes", json=_recipe_body())).json()
        exp = (
            await api.post(
                "/experiments",
                json={"recipe_id": recipe["id"], "recipe_version": 1, "operator": "x"},
            )
        ).json()
        r = await api.post(f"/experiments/{exp['id']}/batch-report", json={"prices": []})
        assert r.status_code == 409


class TestOptimise:
    async def test_optimise_returns_predictions_when_model_absent(self, api: AsyncClient) -> None:
        # No training data → optimiser gets None from predict → final_loss is large.
        recipe = (await api.post("/recipes", json=_recipe_body())).json()
        r = await api.post(
            f"/recipes/{recipe['id']}/optimise",
            json={
                "targets": [{"property_code": "gloss_60", "target_value": 80.0}],
                "max_iterations": 5,
                "population_size": 4,
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["base_recipe_id"] == recipe["id"]
        # Missing predictions → predicted_values empty.
        assert body["predicted_values"] == {}

    async def test_optimise_404_when_recipe_missing(self, api: AsyncClient) -> None:
        r = await api.post(
            "/recipes/nope/optimise",
            json={"targets": [{"property_code": "gloss_60", "target_value": 80.0}]},
        )
        assert r.status_code == 404

    async def test_openapi_declares_new_endpoints(self, api: AsyncClient) -> None:
        paths = (await api.get("/openapi.json")).json()["paths"]
        for expected in (
            "/experiments/{experiment_id}/batch-report",
            "/recipes/{recipe_id}/optimise",
            "/ml/models/{property_code}/drift",
        ):
            assert expected in paths, expected
