"""Integration tests for the CSV export endpoints."""

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


def _recipe(binder_pct: float = 30.0, name: str = "Test recipe") -> dict:
    water = round(100.0 - binder_pct - 20.0, 2)
    return {
        "category": "Краски",
        "subcategory": "Водно-дисперсионные",
        "binder_type": "Acrylic",
        "product_class": "Standard",
        "intended_use": name,
        "stages": [
            {
                "stage_number": 1,
                "name": "Mix, шаг с запятой в имени",  # tests CSV escaping
                "description": "",
                "components": [
                    {
                        "name": "Water",
                        "cas_number": "7732-18-5",
                        "function": "vehicle",
                        "mass_percent": water,
                    },
                    {
                        "name": 'Binder "premium"',  # embedded quote
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
    db = tmp_path / "csv.db"
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


async def test_recipe_csv_has_header_and_rows(api: AsyncClient) -> None:
    rid = (await api.post("/recipes", json=_recipe())).json()["id"]
    r = await api.get(f"/recipes/{rid}/export.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]

    body = r.text
    lines = body.strip().split("\n")
    assert lines[0].startswith("recipe_id,recipe_version,category")
    assert len(lines) == 1 + 3  # header + 3 components


async def test_recipe_csv_escapes_commas_and_quotes(api: AsyncClient) -> None:
    rid = (await api.post("/recipes", json=_recipe())).json()["id"]
    body = (await api.get(f"/recipes/{rid}/export.csv")).text
    # The stage name has a comma → must be wrapped in quotes.
    assert '"Mix, шаг с запятой в имени"' in body
    # The component name has an embedded quote → must be doubled and wrapped.
    assert '"Binder ""premium"""' in body


async def test_recipe_csv_404_for_unknown(api: AsyncClient) -> None:
    r = await api.get("/recipes/does-not-exist/export.csv")
    assert r.status_code == 404


async def test_catalog_csv_lists_every_recipe(api: AsyncClient) -> None:
    for i in range(3):
        await api.post("/recipes", json=_recipe(binder_pct=25.0 + i, name=f"Test {i}"))

    r = await api.get("/catalog/export.csv")
    assert r.status_code == 200
    body = r.text
    lines = body.strip().split("\n")
    assert lines[0].startswith("recipe_id,category,subcategory")
    assert len(lines) == 1 + 3
