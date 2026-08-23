"""Integration tests for production feature-vector ingestion + drift source."""

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
    water = round(100.0 - binder_pct - 20.0, 2)
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
    db = tmp_path / "pv.db"
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


async def _seed_with_models(api: AsyncClient, n: int = 12) -> list[str]:
    """Create n recipes with completed experiments and train models."""
    ids: list[str] = []
    for i in range(n):
        binder = 20.0 + i * 3.0
        rid = (await api.post("/recipes", json=_recipe(binder))).json()["id"]
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
    return ids


async def test_ingest_by_recipe_id_extracts_features_server_side(
    api: AsyncClient,
) -> None:
    rid = (await api.post("/recipes", json=_recipe(30.0))).json()["id"]
    r = await api.post(
        "/ml/production-vectors",
        json={"items": [{"recipe_id": rid, "source": "lab"}]},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["accepted"] == 1
    assert len(body["ids"]) == 1
    assert body["skipped"] == {}

    listed = (await api.get("/ml/production-vectors")).json()
    assert listed["total"] == 1
    sample = listed["samples"][0]
    assert sample["recipe_id"] == rid
    assert len(sample["features"]) == len(FEATURE_NAMES)


async def test_ingest_with_explicit_vector_uses_it_verbatim(api: AsyncClient) -> None:
    fake_vector = [float(i) for i in range(len(FEATURE_NAMES))]
    r = await api.post(
        "/ml/production-vectors",
        json={
            "items": [
                {
                    "recipe_id": "external-lot-42",
                    "features": fake_vector,
                    "source": "production",
                    "notes": "SAP integration",
                }
            ]
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["accepted"] == 1

    got = (await api.get("/ml/production-vectors")).json()["samples"][0]
    assert got["features"] == fake_vector
    assert got["source"] == "production"
    assert got["notes"] == "SAP integration"


async def test_ingest_rejects_wrong_width(api: AsyncClient) -> None:
    r = await api.post(
        "/ml/production-vectors",
        json={
            "items": [
                {"recipe_id": "x", "features": [1.0, 2.0]},  # wrong length
            ]
        },
    )
    assert r.status_code == 422


async def test_ingest_skips_unknown_recipe_but_keeps_valid_ones(api: AsyncClient) -> None:
    rid = (await api.post("/recipes", json=_recipe(30.0))).json()["id"]
    r = await api.post(
        "/ml/production-vectors",
        json={
            "items": [
                {"recipe_id": rid, "source": "lab"},
                {"recipe_id": "does-not-exist"},
            ]
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["accepted"] == 1
    assert "item#1" in body["skipped"]


async def test_list_filters_by_recipe_and_source(api: AsyncClient) -> None:
    rid = (await api.post("/recipes", json=_recipe(30.0))).json()["id"]
    fake_vector = [0.0] * len(FEATURE_NAMES)
    # Two rows with different sources.
    for src in ("lab", "production"):
        await api.post(
            "/ml/production-vectors",
            json={"items": [{"recipe_id": rid, "features": fake_vector, "source": src}]},
        )

    all_ = (await api.get(f"/ml/production-vectors?recipe_id={rid}")).json()
    assert len(all_["samples"]) == 2

    prod_only = (await api.get(f"/ml/production-vectors?recipe_id={rid}&source=production")).json()
    assert len(prod_only["samples"]) == 1
    assert prod_only["samples"][0]["source"] == "production"


async def test_drift_from_catalog_source_production(api: AsyncClient) -> None:
    ids = await _seed_with_models(api)
    # Ingest 20 fresh vectors reusing seeded recipe compositions.
    items = [{"recipe_id": rid} for rid in ids[:8]] * 3  # 24 items
    r = await api.post("/ml/production-vectors", json={"items": items})
    assert r.status_code == 201
    assert r.json()["accepted"] >= 8

    r = await api.get("/ml/models/gloss_60/drift-from-catalog?source=production&limit=100")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["property_code"] == "gloss_60"
    assert len(body["reports"]) == len(FEATURE_NAMES)
    assert body["worst_level"] in {"no_drift", "moderate_drift", "severe_drift"}


async def test_drift_from_catalog_source_production_empty(api: AsyncClient) -> None:
    await _seed_with_models(api)
    r = await api.get("/ml/models/gloss_60/drift-from-catalog?source=production")
    assert r.status_code == 404


async def test_drift_from_catalog_rejects_unknown_source(api: AsyncClient) -> None:
    await _seed_with_models(api)
    r = await api.get("/ml/models/gloss_60/drift-from-catalog?source=hallucination")
    assert r.status_code == 422
