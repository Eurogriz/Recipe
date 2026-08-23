"""Integration tests for GET /recipes/{id}/versions and /diff.

Both endpoints ride on the existing repository ``get_all_versions``
port, which returns every persisted version of the same recipe id.
Versioning is triggered by PUT /recipes/{id} — the API creates a new
version row rather than mutating the existing one.
"""

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


def _recipe(
    *, binder_pct: float = 30.0, pigment_pct: float = 20.0, binder_type: str = "Acrylic"
) -> dict:
    water = round(100.0 - binder_pct - pigment_pct, 2)
    return {
        "category": "Краски",
        "subcategory": "test",
        "binder_type": binder_type,
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
                        "name": "Binder",
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
    db = tmp_path / "ver.db"
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


async def _verify_thrice_and_fork(api: AsyncClient, rid: str) -> str:
    """Take a Draft recipe through the full workflow to unlock forking.

    Returns the new (Draft, version 2) recipe id.  The old id remains
    verified and immutable — that's the whole point of the workflow.
    """
    await api.post(f"/recipes/{rid}/submit-review", json={"actor": "author"})
    for i in range(3):
        r = await api.post(
            f"/recipes/{rid}/verify",
            json={
                "verifier": f"verifier-{i + 1}",
                "source_citation_id": "primary",
                "comment": "ok",
            },
        )
        assert r.status_code == 200, r.text
    nv = await api.post(
        f"/recipes/{rid}/new-version",
        json={"actor": "author", "change_summary": "tweak"},
    )
    assert nv.status_code == 201, nv.text
    return nv.json()["id"]


async def test_versions_returns_history_latest_first(api: AsyncClient) -> None:
    rid = (await api.post("/recipes", json=_recipe(binder_pct=30.0))).json()["id"]
    new_id = await _verify_thrice_and_fork(api, rid)

    # Amend the new draft version so metadata + composition differ.
    await api.put(
        f"/recipes/{new_id}", json=_recipe(binder_pct=35.0, binder_type="Styrene-acrylic")
    )

    r = await api.get(f"/recipes/{new_id}/versions")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["recipe_id"] == new_id
    versions = body["versions"]
    assert len(versions) == 2  # new draft (v2) + original verified (v1)
    numbers = [v["version"] for v in versions]
    assert numbers == sorted(numbers, reverse=True), "latest version must be first"
    assert versions[0]["version"] == 2
    assert versions[-1]["version"] == 1
    assert versions[-1]["status"] == "Verified"


async def test_versions_404_for_unknown_recipe(api: AsyncClient) -> None:
    r = await api.get("/recipes/does-not-exist/versions")
    assert r.status_code == 404


async def test_diff_identical_when_left_equals_right(api: AsyncClient) -> None:
    rid = (await api.post("/recipes", json=_recipe(binder_pct=30.0))).json()["id"]
    r = await api.get(f"/recipes/{rid}/diff?left=1&right=1")
    assert r.status_code == 200
    body = r.json()
    assert body["identical"] is True
    assert body["metadata_changes"] == []
    assert body["component_changes"] == []


async def test_diff_reports_mass_changed(api: AsyncClient) -> None:
    rid = (await api.post("/recipes", json=_recipe(binder_pct=30.0))).json()["id"]
    new_id = await _verify_thrice_and_fork(api, rid)
    await api.put(f"/recipes/{new_id}", json=_recipe(binder_pct=35.0))

    r = await api.get(f"/recipes/{new_id}/diff?left=1&right=2")
    assert r.status_code == 200
    body = r.json()
    assert body["identical"] is False
    kinds = {c["kind"] for c in body["component_changes"]}
    assert "mass_changed" in kinds
    binder_change = next(c for c in body["component_changes"] if c["component_name"] == "Binder")
    assert binder_change["from_value"] == 30.0
    assert binder_change["to_value"] == 35.0


async def test_diff_reports_metadata_changed(api: AsyncClient) -> None:
    rid = (await api.post("/recipes", json=_recipe(binder_type="Acrylic"))).json()["id"]
    new_id = await _verify_thrice_and_fork(api, rid)
    await api.put(f"/recipes/{new_id}", json=_recipe(binder_type="Styrene-acrylic"))

    r = await api.get(f"/recipes/{new_id}/diff?left=1&right=2")
    body = r.json()
    md_fields = {c["field"] for c in body["metadata_changes"]}
    assert "binder_type" in md_fields
    binder_change = next(c for c in body["metadata_changes"] if c["field"] == "binder_type")
    assert binder_change["from_value"] == "Acrylic"
    assert binder_change["to_value"] == "Styrene-acrylic"


async def test_diff_422_for_unknown_version(api: AsyncClient) -> None:
    rid = (await api.post("/recipes", json=_recipe())).json()["id"]
    r = await api.get(f"/recipes/{rid}/diff?left=1&right=999")
    assert r.status_code == 422


async def test_diff_404_for_unknown_recipe(api: AsyncClient) -> None:
    r = await api.get("/recipes/does-not-exist/diff?left=1&right=2")
    assert r.status_code == 404
