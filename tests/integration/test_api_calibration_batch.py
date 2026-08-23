"""Integration tests for batch calibration + coverage matrix endpoints."""

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
    db = tmp_path / "cal_batch.db"
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


async def _seed_models(api: AsyncClient, n: int = 12) -> list[str]:
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


def _samples(base: float) -> list[dict]:
    return [
        {
            "raw_prediction": base + i,
            "actual": base + 1.0 + i * 1.02,
            "lower": base - 5.0 + i,
            "upper": base + 5.0 + i,
        }
        for i in range(10)
    ]


async def test_batch_calibrate_updates_multiple_models(api: AsyncClient) -> None:
    await _seed_models(api)
    payload = {
        "entries": [
            {"property_code": "gloss_60", "samples": _samples(60.0)},
            {"property_code": "voc_content", "samples": _samples(15.0)},
            {"property_code": "no_such_property", "samples": _samples(1.0)},
        ],
        "target_coverage": 0.9,
    }
    r = await api.post("/ml/calibrate", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    ok_codes = {row["property_code"] for row in body["calibrated"]}
    assert {"gloss_60", "voc_content"}.issubset(ok_codes)
    assert "no_such_property" in body["skipped"]
    for row in body["calibrated"]:
        assert row["has_isotonic"] is True
        assert row["has_interval"] is True
        assert row["n_samples"] == 10


async def test_calibration_matrix_reports_coverage(api: AsyncClient) -> None:
    await _seed_models(api)
    # Empty matrix — no calibrations yet.
    r = await api.get("/ml/calibration-matrix")
    assert r.status_code == 200
    empty = r.json()
    assert empty["n_models"] >= 2
    assert empty["n_calibrated"] == 0
    assert all(row["has_calibration"] is False for row in empty["rows"])

    # Calibrate two models.
    await api.post(
        "/ml/calibrate",
        json={
            "entries": [
                {"property_code": "gloss_60", "samples": _samples(60.0)},
                {"property_code": "voc_content", "samples": _samples(15.0)},
            ],
            "target_coverage": 0.9,
        },
    )
    r = await api.get("/ml/calibration-matrix")
    body = r.json()
    calibrated_rows = [row for row in body["rows"] if row["has_calibration"]]
    assert len(calibrated_rows) == 2
    for row in calibrated_rows:
        assert row["has_isotonic"] is True
        assert row["has_interval"] is True
        assert row["target_coverage"] == 0.9
        assert row["coverage_gap"] is not None
    assert body["n_calibrated"] == 2


async def test_openapi_declares_batch_and_matrix(api: AsyncClient) -> None:
    paths = (await api.get("/openapi.json")).json()["paths"]
    assert "/ml/calibrate" in paths
    assert "/ml/calibration-matrix" in paths
