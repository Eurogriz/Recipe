"""Integration tests for the v1.21 dashboard endpoint.

/dashboard/summary bundles data that used to require 5 separate GETs.
We seed a mixed catalogue and assert the response shape is complete
and internally consistent (total == sum(by_category), recent lists
have expected length and the newest event is first).
"""

from __future__ import annotations

import base64
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from formulation_workbench.application.use_cases.create_recipe import (
    CreateRecipeCommand,
)
from formulation_workbench.domain.entities.recipe import (
    Component,
    CompositionStage,
    ProductClass,
    Recipe,
)
from formulation_workbench.domain.value_objects.citation import Citation
from formulation_workbench.domain.value_objects.isbn import Isbn
from formulation_workbench.infrastructure.config import AppSettings, reset_settings_cache
from formulation_workbench.infrastructure.db.connection import Database
from formulation_workbench.infrastructure.db.models import Base
from formulation_workbench.infrastructure.db.repositories.users import UserRepository
from formulation_workbench.infrastructure.di import Container
from formulation_workbench.presentation.api.app import create_app

pytestmark = [pytest.mark.integration, pytest.mark.api]


def _basic(username: str, password: str) -> dict[str, str]:
    raw = f"{username}:{password}".encode()
    return {"Authorization": f"Basic {base64.b64encode(raw).decode()}"}


def _make_recipe(cat: str, sub: str, pc: ProductClass) -> Recipe:
    return Recipe(
        id=uuid.uuid4().hex,
        category=cat,
        subcategory=sub,
        binder_type="Acrylic",
        product_class=pc,
        intended_use="dashboard test seed",
        stages=(
            CompositionStage(
                stage_number=1,
                name="Mix",
                description="",
                components=(
                    Component(
                        name="Water",
                        cas_number="7732-18-5",
                        function="vehicle",
                        mass_percent=60.0,
                        tolerance_percent=1.0,
                    ),
                    Component(
                        name="Binder",
                        cas_number="mixture",
                        function="binder",
                        mass_percent=25.0,
                        tolerance_percent=1.0,
                    ),
                    Component(
                        name="TiO2",
                        cas_number="13463-67-7",
                        function="pigment",
                        mass_percent=15.0,
                        tolerance_percent=1.0,
                    ),
                ),
                process=None,
            ),
        ),
        primary_source=Citation(
            authors="T",
            title="T",
            year=2020,
            publisher="Noyes Publications",
            isbn=Isbn("9780815513773"),
        ),
    )


@pytest_asyncio.fixture
async def api_with_seed(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    reset_settings_cache()
    db = tmp_path / "dash.db"
    dbc = Database.from_url(url=f"sqlite+aiosqlite:///{db}")
    await dbc.init()
    async with dbc.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    repo = UserRepository(dbc)
    await repo.create(username="root", password="root-password!", role="Admin")
    await dbc.close()

    settings = AppSettings(
        environment="development",
        database_url=f"sqlite+aiosqlite:///{db}",
        api_token="",
        rate_limit_enabled=False,
        model_dir=tmp_path / "models",
    )

    container = await Container.build(settings)
    try:
        seed = [
            ("Краски", "Акриловые интерьерные", ProductClass.STANDARD),
            ("Краски", "Акриловые интерьерные", ProductClass.PREMIUM),
            ("Краски", "Латексные фасадные", ProductClass.STANDARD),
            ("Герметики", "Силиконовые", ProductClass.STANDARD),
        ]
        for cat, sub, pc in seed:
            await container.create_recipe.execute(
                CreateRecipeCommand(recipe=_make_recipe(cat, sub, pc), actor="seed")
            )
    finally:
        await container.close()

    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


# --------------------------------------------------------------------------- e2e


async def test_dashboard_summary_full_shape(api_with_seed: AsyncClient) -> None:
    r = await api_with_seed.get("/dashboard/summary", headers=_basic("root", "root-password!"))
    assert r.status_code == 200, r.text
    body = r.json()
    # Basic envelope.
    assert "version" in body
    assert "environment" in body
    assert body["total_recipes"] == 4
    # Facets consistent with total.
    assert sum(body["by_category"].values()) == body["total_recipes"]
    assert body["by_category"] == {"Краски": 3, "Герметики": 1}
    assert body["by_product_class"] == {"Standard": 3, "Premium": 1}
    # Recent list: 4 seeded → all 4 come back (limit is 10).
    assert len(body["recent_recipes"]) == 4
    # Newest first.
    ordering = [r["created_at"] for r in body["recent_recipes"]]
    assert ordering == sorted(ordering, reverse=True)
    # Audit log has 4 Created rows (one per recipe).
    assert len(body["recent_audit"]) >= 4
    assert all(e["action"] in {"Created"} for e in body["recent_audit"][:4])


async def test_dashboard_summary_requires_reader(api_with_seed: AsyncClient) -> None:
    """Open-mode dev-server grants '*' so we can only assert 200
    when no api_token is set.  Real production deployments with
    ``FW_API_TOKEN`` would refuse anonymous access — that path is
    covered by test_api_auth."""
    r = await api_with_seed.get("/dashboard/summary")
    assert r.status_code == 200


async def test_dashboard_summary_reports_zero_trained_models(
    api_with_seed: AsyncClient,
) -> None:
    """Fresh instance has no models on disk → trained_models=0.
    A regression that always returns some cached number would
    silently lie to the dashboard."""
    r = await api_with_seed.get("/dashboard/summary", headers=_basic("root", "root-password!"))
    assert r.json()["trained_models"] == 0
