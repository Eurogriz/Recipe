"""End-to-end tests for /recipes/{id}/assessment."""

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
                    "mass_percent": 33.5,
                },
                {
                    "name": "Dispex",
                    "cas_number": "9003-04-7",
                    "function": "dispersant",
                    "mass_percent": 0.6,
                },
                {
                    "name": "Foamex",
                    "cas_number": "63148-62-9",
                    "function": "defoamer",
                    "mass_percent": 0.3,
                },
                {
                    "name": "Kathon",
                    "cas_number": "26172-55-4",
                    "function": "biocide",
                    "mass_percent": 0.15,
                },
                {
                    "name": "TiO2",
                    "cas_number": "13463-67-7",
                    "function": "pigment",
                    "mass_percent": 22.0,
                },
                {
                    "name": "CaCO3",
                    "cas_number": "1317-65-3",
                    "function": "extender",
                    "mass_percent": 8.0,
                },
                {
                    "name": "Talc",
                    "cas_number": "14807-96-6",
                    "function": "extender",
                    "mass_percent": 4.0,
                },
                {
                    "name": "Acrylic",
                    "cas_number": "mixture",
                    "function": "binder",
                    "mass_percent": 27.85,
                },
                {
                    "name": "Texanol",
                    "cas_number": "25265-77-4",
                    "function": "coalescent",
                    "mass_percent": 1.5,
                },
                {
                    "name": "Rheo",
                    "cas_number": "proprietary",
                    "function": "rheology_modifier",
                    "mass_percent": 0.8,
                },
                {
                    "name": "PG",
                    "cas_number": "57-55-6",
                    "function": "antifreeze",
                    "mass_percent": 1.3,
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
    db = tmp_path / "assess.db"
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


async def test_assessment_endpoint_returns_score(api: AsyncClient) -> None:
    created = (await api.post("/recipes", json=VALID_RECIPE)).json()
    rid = created["id"]

    r = await api.get(f"/recipes/{rid}/assessment")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["recipe_id"] == rid
    assert 0 <= body["score"] <= 100
    assert body["maturity"] in {
        "defective",
        "draft",
        "lab_ready",
        "production_ready",
        "reference",
    }
    assert isinstance(body["findings"], list)
    assert "errors" in body["summary"]


async def test_assessment_404_when_missing(api: AsyncClient) -> None:
    r = await api.get("/recipes/nope/assessment")
    assert r.status_code == 404


async def test_openapi_declares_assessment(api: AsyncClient) -> None:
    spec = (await api.get("/openapi.json")).json()
    assert "/recipes/{recipe_id}/assessment" in spec["paths"]
    assert "get" in spec["paths"]["/recipes/{recipe_id}/assessment"]
