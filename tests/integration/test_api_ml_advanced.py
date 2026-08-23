"""Integration tests for calibrate / drift-full / pareto / explain endpoints."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from formulation_workbench.infrastructure.config import AppSettings, reset_settings_cache
from formulation_workbench.infrastructure.db.connection import Database
from formulation_workbench.infrastructure.db.models import Base
from formulation_workbench.infrastructure.ml.features import FEATURE_NAMES
from formulation_workbench.presentation.api.app import create_app

pytestmark = [pytest.mark.integration, pytest.mark.api]


def _recipe(binder_pct: float) -> dict:
    water = round(100.0 - binder_pct - 10.0, 2)
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
    db = tmp_path / "adv.db"
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


async def _seed_models(api: AsyncClient, n: int = 15) -> list[str]:
    """Create n recipes + experiments, train the models, return recipe ids."""
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
                    {"property_code": "gloss_60", "value": 15.0 + 1.6 * binder + (i % 5) - 2},
                    {"property_code": "voc_content", "value": 5.0 + 0.4 * binder},
                ],
            },
        )
    await api.post("/ml/train", json={"recipe_ids": ids})
    return ids


# ---------------------------------------------------------------------------
# Explainability
# ---------------------------------------------------------------------------
async def test_predict_returns_top_features_when_requested(api: AsyncClient) -> None:
    ids = await _seed_models(api)
    r = await api.get(
        f"/recipes/{ids[5]}/predict",
        params={"explain_top_k": 3},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["predictions"], "must have at least one prediction"
    for p in body["predictions"]:
        assert 1 <= len(p["top_features"]) <= 3
        for fi in p["top_features"]:
            for key in ("feature_name", "contribution", "baseline_value", "global_importance"):
                assert key in fi


async def test_predict_omits_top_features_when_not_requested(api: AsyncClient) -> None:
    ids = await _seed_models(api)
    r = await api.get(f"/recipes/{ids[3]}/predict")
    assert r.status_code == 200
    assert all(p["top_features"] == [] for p in r.json()["predictions"])


# ---------------------------------------------------------------------------
# Drift-full
# ---------------------------------------------------------------------------
async def test_drift_full_returns_per_feature_reports(api: AsyncClient) -> None:
    await _seed_models(api)
    # Fabricate 5 "fresh" vectors of the correct width.
    current = [[float(i)] + [0.0] * (len(FEATURE_NAMES) - 1) for i in range(5)]
    r = await api.post(
        "/ml/models/gloss_60/drift-full",
        json={"current_vectors": current},
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["reports"]) == len(FEATURE_NAMES)
    assert body["worst_level"] in {"no_drift", "moderate_drift", "severe_drift"}


async def test_drift_full_422_on_wrong_width(api: AsyncClient) -> None:
    await _seed_models(api)
    r = await api.post(
        "/ml/models/gloss_60/drift-full",
        json={"current_vectors": [[0.0, 1.0], [1.0, 2.0]]},  # too narrow
    )
    assert r.status_code == 422


async def test_drift_full_404_for_missing_model(api: AsyncClient) -> None:
    current = [[0.0] * len(FEATURE_NAMES) for _ in range(3)]
    r = await api.post(
        "/ml/models/no_such_property/drift-full",
        json={"current_vectors": current},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------
async def test_calibrate_endpoint_returns_bundle(api: AsyncClient) -> None:
    await _seed_models(api)
    # Build a calibration set — 10 predictions + measured values.
    samples = [
        {
            "raw_prediction": 60.0 + i,
            "actual": 61.0 + i * 1.05,
            "lower": 55.0 + i,
            "upper": 65.0 + i,
        }
        for i in range(10)
    ]
    r = await api.post(
        "/ml/models/gloss_60/calibrate",
        json={"samples": samples, "target_coverage": 0.9},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["property_code"] == "gloss_60"
    assert body["has_isotonic"] is True
    assert body["has_interval"] is True
    assert body["n_samples"] == 10


async def test_calibrate_404_for_missing_model(api: AsyncClient) -> None:
    r = await api.post(
        "/ml/models/no_such_property/calibrate",
        json={
            "samples": [
                {"raw_prediction": 1.0, "actual": 1.0},
                {"raw_prediction": 2.0, "actual": 2.0},
            ]
        },
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Pareto
# ---------------------------------------------------------------------------
async def test_pareto_returns_front(api: AsyncClient) -> None:
    ids = await _seed_models(api)
    r = await api.post(
        f"/recipes/{ids[0]}/pareto",
        json={
            "targets": [
                {"property_code": "gloss_60", "target_value": 200.0, "direction": "maximise"},
                {"property_code": "voc_content", "target_value": 0.0, "direction": "minimise"},
            ],
            "population_size": 12,
            "generations": 5,
            "mutation_std": 1.0,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["base_recipe_id"] == ids[0]
    assert body["generations"] == 5
    assert len(body["front"]) >= 1
    for p in body["front"]:
        assert set(p["objectives"].keys()) == {"gloss_60", "voc_content"}
        assert p["rank"] == 0


async def test_pareto_404_missing_recipe(api: AsyncClient) -> None:
    r = await api.post(
        "/recipes/nope/pareto",
        json={"targets": [{"property_code": "gloss_60", "target_value": 100.0}]},
    )
    assert r.status_code == 404


async def test_openapi_declares_new_endpoints(api: AsyncClient) -> None:
    paths = (await api.get("/openapi.json")).json()["paths"]
    for expected in (
        "/ml/models/{property_code}/drift-full",
        "/ml/models/{property_code}/calibrate",
        "/recipes/{recipe_id}/pareto",
    ):
        assert expected in paths, expected
