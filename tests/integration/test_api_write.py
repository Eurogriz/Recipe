"""Tests for POST/PUT/DELETE and workflow endpoints on /recipes."""

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
    "finish": "matte",
    "color": "white",
    "tags": ["interior"],
    "stages": [
        {
            "stage_number": 1,
            "name": "Mixing",
            "description": "Mix all",
            "components": [
                {
                    "name": "Water",
                    "cas_number": "7732-18-5",
                    "function": "vehicle",
                    "mass_percent": 50.0,
                },
                {
                    "name": "Acrylic emulsion",
                    "cas_number": "mixture",
                    "function": "binder",
                    "mass_percent": 40.0,
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
        "authors": "Flick, E. W.",
        "title": "Water-Based Paint Formulations, Vol. 3",
        "year": 1995,
        "publisher": "Noyes Publications",
        "isbn": "9780815513773",
    },
    "cross_references": [],
}


@pytest_asyncio.fixture
async def api(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    reset_settings_cache()
    db_file = tmp_path / "write.db"
    db = Database.from_url(url=f"sqlite+aiosqlite:///{db_file}")
    await db.init()
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await db.close()

    # No auth — dev-mode "open" principal has all scopes.
    settings = AppSettings(
        environment="development",
        database_url=f"sqlite+aiosqlite:///{db_file}",
        api_token="",
        rate_limit_enabled=False,
    )
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


async def test_create_recipe_returns_201(api: AsyncClient) -> None:
    r = await api.post("/recipes", json=VALID_RECIPE)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["category"] == "Краски"
    assert body["status"] == "Draft"
    assert body["id"]


async def test_create_then_fetch(api: AsyncClient) -> None:
    created = (await api.post("/recipes", json=VALID_RECIPE)).json()
    r = await api.get(f"/recipes/{created['id']}")
    assert r.status_code == 200
    assert r.json()["id"] == created["id"]


async def test_create_invalid_returns_422(api: AsyncClient) -> None:
    bad = {**VALID_RECIPE}
    bad_stages = [{**bad["stages"][0]}]
    bad_stages[0] = {
        **bad_stages[0],
        "components": [
            {
                "name": "Water",
                "cas_number": "7732-18-5",
                "function": "vehicle",
                "mass_percent": 200.0,  # invalid: pydantic bounds
            }
        ],
    }
    bad["stages"] = bad_stages
    r = await api.post("/recipes", json=bad)
    assert r.status_code == 422


async def test_create_invalid_domain_returns_422(api: AsyncClient) -> None:
    bad = {**VALID_RECIPE}
    bad["stages"] = [
        {
            "stage_number": 1,
            "name": "Only",
            "description": "",
            "components": [
                {
                    "name": "Water",
                    "cas_number": "7732-18-5",
                    "function": "vehicle",
                    "mass_percent": 42.0,
                }
            ],
        }
    ]  # sum != 100
    r = await api.post("/recipes", json=bad)
    assert r.status_code == 422
    assert "sum" in r.json()["detail"].lower()


async def test_update_existing(api: AsyncClient) -> None:
    created = (await api.post("/recipes", json=VALID_RECIPE)).json()
    updated_body = {**VALID_RECIPE, "intended_use": "Kitchen ceiling paint"}
    r = await api.put(f"/recipes/{created['id']}", json=updated_body)
    assert r.status_code == 200
    assert r.json()["intended_use"] == "Kitchen ceiling paint"


async def test_update_missing_returns_404(api: AsyncClient) -> None:
    r = await api.put("/recipes/does-not-exist", json=VALID_RECIPE)
    assert r.status_code == 404


async def test_delete_soft(api: AsyncClient) -> None:
    created = (await api.post("/recipes", json=VALID_RECIPE)).json()
    r = await api.delete(f"/recipes/{created['id']}")
    assert r.status_code == 204


async def test_delete_missing_returns_404(api: AsyncClient) -> None:
    r = await api.delete("/recipes/nope")
    assert r.status_code == 404


async def test_submit_verify_reaches_verified(api: AsyncClient) -> None:
    created = (await api.post("/recipes", json=VALID_RECIPE)).json()
    rid = created["id"]

    r = await api.post(f"/recipes/{rid}/submit-review", json={"actor": "author"})
    assert r.status_code == 200
    assert r.json()["status"] == "PendingReview"

    for i in range(3):
        r = await api.post(
            f"/recipes/{rid}/verify",
            json={"verifier": f"user{i}", "source_citation_id": f"c{i}"},
        )
        assert r.status_code == 200, r.text
    assert r.json()["status"] == "Verified"
    assert r.json()["verification_count"] == 3


async def test_verify_missing_returns_404(api: AsyncClient) -> None:
    r = await api.post("/recipes/nope/verify", json={"verifier": "x"})
    assert r.status_code == 404


async def test_reject_draft(api: AsyncClient) -> None:
    created = (await api.post("/recipes", json=VALID_RECIPE)).json()
    r = await api.post(
        f"/recipes/{created['id']}/reject",
        json={"actor": "auditor", "reason": "wrong CPVC"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "Rejected"


async def test_verify_draft_returns_conflict(api: AsyncClient) -> None:
    created = (await api.post("/recipes", json=VALID_RECIPE)).json()
    r = await api.post(f"/recipes/{created['id']}/verify", json={"verifier": "x"})
    assert r.status_code == 409  # cannot verify a Draft


async def test_openapi_declares_write_endpoints(api: AsyncClient) -> None:
    spec = (await api.get("/openapi.json")).json()
    paths = spec["paths"]
    assert "post" in paths["/recipes"]
    assert "put" in paths["/recipes/{recipe_id}"]
    assert "delete" in paths["/recipes/{recipe_id}"]
    for suffix in ("submit-review", "verify", "reject"):
        assert f"/recipes/{{recipe_id}}/{suffix}" in paths
