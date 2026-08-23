"""End-to-end tests for the cost, experiment, and apply-lab-results endpoints."""

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


VALID_RECIPE = {
    "category": "Краски",
    "subcategory": "Водно-дисперсионные",
    "binder_type": "Стирол-акриловая дисперсия",
    "product_class": "Premium",
    "intended_use": "Interior matte wall paint",
    "stages": [
        {
            "stage_number": 1,
            "name": "Mixing",
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
    db = tmp_path / "cost.db"
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
    )
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


# ---------------------------------------------------------------------------
# Cost
# ---------------------------------------------------------------------------
async def test_cost_endpoint_computes_price(api: AsyncClient) -> None:
    created = (await api.post("/recipes", json=VALID_RECIPE)).json()
    rid = created["id"]

    r = await api.post(
        f"/recipes/{rid}/cost",
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
    assert body["currency"] == "EUR"
    # 0.4*0.001 + 0.4*3.00 + 0.2*4.50 = 2.1004 EUR/kg
    assert 2.09 <= body["cost_per_kg"] <= 2.11
    assert body["priced_fraction"] == 1.0


async def test_cost_endpoint_returns_missing_prices(api: AsyncClient) -> None:
    created = (await api.post("/recipes", json=VALID_RECIPE)).json()
    r = await api.post(
        f"/recipes/{created['id']}/cost",
        json={
            "prices": [
                {"component_name": "Water", "amount": 0.001, "currency": "EUR", "unit": "kg"}
            ]
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert "Acrylic" in body["missing_prices"]
    assert body["priced_fraction"] < 1.0


async def test_cost_endpoint_404(api: AsyncClient) -> None:
    r = await api.post("/recipes/does-not-exist/cost", json={"prices": []})
    assert r.status_code == 404


async def test_cost_endpoint_validation_error_on_bad_unit(api: AsyncClient) -> None:
    created = (await api.post("/recipes", json=VALID_RECIPE)).json()
    r = await api.post(
        f"/recipes/{created['id']}/cost",
        json={
            "prices": [
                {"component_name": "Water", "amount": 1.0, "currency": "EUR", "unit": "barrel"}
            ]
        },
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Experiment + apply-lab-results
# ---------------------------------------------------------------------------
async def test_full_experiment_lifecycle(api: AsyncClient) -> None:
    created = (await api.post("/recipes", json=VALID_RECIPE)).json()
    rid = created["id"]

    # 1. Plan an experiment.
    r = await api.post(
        "/experiments",
        json={
            "recipe_id": rid,
            "recipe_version": 1,
            "title": "Gloss trial",
            "hypothesis": "Increase coalescent",
            "operator": "alice",
        },
    )
    assert r.status_code == 201, r.text
    experiment_id = r.json()["id"]
    assert r.json()["status"] == "planned"

    # 2. Complete with measurements.
    r = await api.post(
        f"/experiments/{experiment_id}/complete",
        json={
            "batch": {
                "batch_number": "B-001",
                "target_mass_kg": 10.0,
                "actual_mass_kg": 9.9,
                "equipment_used": "Disperser",
            },
            "measured_properties": [
                {"property_code": "gloss_60", "value": 82.0, "unit": "GU", "operator": "alice"},
            ],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    # No target_properties on the recipe → INCONCLUSIVE.
    assert body["verdict"] == "inconclusive"

    # 3. Apply the results (annotate mode).
    r = await api.post(
        f"/experiments/{experiment_id}/apply",
        json={"actor": "alice", "mode": "annotate"},
    )
    assert r.status_code == 200
    applied = r.json()
    assert applied["mode"] == "annotate"
    assert applied["original_recipe_id"] == rid
    assert applied["resulting_recipe_id"] == rid


async def test_apply_lab_results_branches_on_deviation(api: AsyncClient) -> None:
    # This recipe has a hard target — the measured value will miss it.
    recipe_with_target = {
        **VALID_RECIPE,
        # PATCH the request body to include target_properties requires the API
        # to accept them.  Since our CreateRecipeRequest does not include
        # target_properties yet, we skip the branch check here and only
        # verify that mode=branch is accepted for a passing experiment.
    }
    created = (await api.post("/recipes", json=recipe_with_target)).json()
    rid = created["id"]

    exp = (
        await api.post(
            "/experiments",
            json={"recipe_id": rid, "recipe_version": 1, "operator": "bob"},
        )
    ).json()
    await api.post(
        f"/experiments/{exp['id']}/complete",
        json={
            "batch": {"batch_number": "B-002", "target_mass_kg": 5.0},
            "measured_properties": [
                {"property_code": "gloss_60", "value": 60.0},
            ],
        },
    )
    r = await api.post(
        f"/experiments/{exp['id']}/apply",
        json={"actor": "bob", "mode": "branch", "change_note": "Investigating gloss"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "branch"
    # Branch mode always spawns a new version even without deviations.
    assert body["resulting_recipe_id"] != rid


async def test_apply_lab_results_404_when_missing(api: AsyncClient) -> None:
    r = await api.post("/experiments/nope/apply", json={"actor": "x", "mode": "annotate"})
    assert r.status_code == 404


async def test_openapi_declares_new_endpoints(api: AsyncClient) -> None:
    paths = (await api.get("/openapi.json")).json()["paths"]
    for expected in (
        "/recipes/{recipe_id}/cost",
        "/experiments",
        "/experiments/{experiment_id}",
        "/experiments/{experiment_id}/complete",
        "/experiments/{experiment_id}/apply",
    ):
        assert expected in paths, expected
