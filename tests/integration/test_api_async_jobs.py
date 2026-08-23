"""Integration tests for the async ML job registry endpoints."""

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
    db = tmp_path / "async_jobs.db"
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


async def _seed(api: AsyncClient, n: int = 12) -> list[str]:
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
    return ids


async def _wait_for_job(api: AsyncClient, job_id: str, *, attempts: int = 30) -> dict:
    import asyncio

    for _ in range(attempts):
        r = await api.get(f"/ml/jobs/{job_id}")
        assert r.status_code == 200, r.text
        body = r.json()
        if body["status"] in {"succeeded", "failed", "cancelled"}:
            return body
        await asyncio.sleep(0.1)
    raise AssertionError(f"job {job_id} never reached a terminal state")


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
async def test_async_training_flow_produces_succeeded_job(api: AsyncClient) -> None:
    ids = await _seed(api)
    r = await api.post("/ml/train/async", json={"recipe_ids": ids})
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["status"] in {"queued", "running", "succeeded"}
    assert job["kind"] == "ml.train"
    assert job["metadata"]["recipe_ids"] == ids

    final = await _wait_for_job(api, job["id"])
    assert final["status"] == "succeeded", final
    assert final["duration_seconds"] is not None
    assert final["duration_seconds"] >= 0
    result = final["result"]
    assert "trained" in result
    assert isinstance(result["trained"], list)
    assert result["trained"], "at least one model must be trained"
    codes = {m["property_code"] for m in result["trained"]}
    assert {"gloss_60", "voc_content"}.issubset(codes)


async def test_list_jobs_shows_recent_job(api: AsyncClient) -> None:
    ids = await _seed(api, n=8)
    r = await api.post("/ml/train/async", json={"recipe_ids": ids})
    job_id = r.json()["id"]
    await _wait_for_job(api, job_id)

    listing = (await api.get("/ml/jobs")).json()["jobs"]
    assert any(j["id"] == job_id for j in listing)

    filtered = (await api.get("/ml/jobs?kind=ml.train&status=succeeded")).json()["jobs"]
    assert any(j["id"] == job_id for j in filtered)


async def test_get_job_returns_404_for_unknown_id(api: AsyncClient) -> None:
    r = await api.get("/ml/jobs/does-not-exist")
    assert r.status_code == 404


async def test_cancel_returns_404_for_unknown_id(api: AsyncClient) -> None:
    r = await api.delete("/ml/jobs/does-not-exist")
    assert r.status_code == 404


async def test_cancel_terminal_job_returns_409(api: AsyncClient) -> None:
    ids = await _seed(api, n=8)
    job_id = (await api.post("/ml/train/async", json={"recipe_ids": ids})).json()["id"]
    await _wait_for_job(api, job_id)
    r = await api.delete(f"/ml/jobs/{job_id}")
    assert r.status_code == 409


async def test_openapi_declares_async_endpoints(api: AsyncClient) -> None:
    paths = (await api.get("/openapi.json")).json()["paths"]
    for expected in (
        "/ml/train/async",
        "/ml/jobs",
        "/ml/jobs/{job_id}",
    ):
        assert expected in paths, expected
