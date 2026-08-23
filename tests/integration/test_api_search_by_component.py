"""Integration tests for reverse-composition search (v1.25).

Seeds a small catalogue with known CAS distributions and asserts:
  * the endpoint groups matches per recipe (sums mass-percent);
  * ordering is by total mass-percent descending;
  * min/max mass-percent bounds are HAVING-clause filters
    (act on the sum, not on individual stages);
  * an SVHC CAS with no recipes returns an empty result — no crash.
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


def _recipe_with_pigment(
    category: str,
    pigment_percent: float,
    *,
    extra_stage_with_same_cas: float = 0.0,
) -> Recipe:
    """Build a recipe with a controlled TiO2 (13463-67-7) percentage.

    ``extra_stage_with_same_cas`` lets us test the mass-percent SUM
    across two stages of the same recipe.
    """
    other = 100.0 - pigment_percent - extra_stage_with_same_cas
    stages = [
        CompositionStage(
            stage_number=1,
            name="Grind",
            description="",
            components=(
                Component(
                    name="Water",
                    cas_number="7732-18-5",
                    function="vehicle",
                    mass_percent=other,
                    tolerance_percent=1.0,
                ),
                Component(
                    name="TiO2",
                    cas_number="13463-67-7",
                    function="pigment",
                    mass_percent=pigment_percent,
                    tolerance_percent=1.0,
                ),
            ),
            process=None,
        ),
    ]
    if extra_stage_with_same_cas > 0:
        stages.append(
            CompositionStage(
                stage_number=2,
                name="Topcoat",
                description="",
                components=(
                    Component(
                        name="TiO2 (topcoat)",
                        cas_number="13463-67-7",
                        function="pigment",
                        mass_percent=extra_stage_with_same_cas,
                        tolerance_percent=1.0,
                    ),
                ),
                process=None,
            )
        )
    return Recipe(
        id=uuid.uuid4().hex,
        category=category,
        subcategory="seed",
        binder_type="Acrylic",
        product_class=ProductClass.STANDARD,
        intended_use="component search test seed",
        stages=tuple(stages),
        primary_source=Citation(
            authors="T",
            title="T",
            year=2020,
            publisher="Noyes Publications",
            isbn=Isbn("9780815511502"),
        ),
    )


@pytest_asyncio.fixture
async def api_with_pigment_catalog(
    tmp_path: Path,
) -> AsyncIterator[tuple[AsyncClient, AppSettings]]:
    reset_settings_cache()
    db = tmp_path / "comp.db"
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
        # Краски: 20% TiO2 in one stage
        await container.create_recipe.execute(
            CreateRecipeCommand(recipe=_recipe_with_pigment("Краски", 20.0), actor="s")
        )
        # Краски: 40% TiO2 spread across 2 stages (30 + 10)
        await container.create_recipe.execute(
            CreateRecipeCommand(
                recipe=_recipe_with_pigment("Краски", 30.0, extra_stage_with_same_cas=10.0),
                actor="s",
            )
        )
        # Лаки: 5% TiO2 — below the "≥10" threshold used in one test
        await container.create_recipe.execute(
            CreateRecipeCommand(recipe=_recipe_with_pigment("Лаки", 5.0), actor="s")
        )
    finally:
        await container.close()

    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client, settings


# --------------------------------------------------------------------------- e2e


async def test_returns_all_matches_sorted_by_mass_percent(
    api_with_pigment_catalog: tuple[AsyncClient, AppSettings],
) -> None:
    api, _ = api_with_pigment_catalog
    r = await api.get(
        "/recipes/by-component?cas=13463-67-7",
        headers=_basic("root", "root-password!"),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cas_number"] == "13463-67-7"
    assert body["n_recipes"] == 3
    # Sorted descending: 40% > 20% > 5%
    percents = [m["total_mass_percent"] for m in body["matches"]]
    assert percents == sorted(percents, reverse=True)
    assert percents == [40.0, 20.0, 5.0]


async def test_sums_across_multiple_stages(
    api_with_pigment_catalog: tuple[AsyncClient, AppSettings],
) -> None:
    """The 40% recipe has TiO2 in TWO stages (30 + 10).  The result
    must show it as one row with total 40, not two rows of 30 and 10."""
    api, _ = api_with_pigment_catalog
    body = (
        await api.get(
            "/recipes/by-component?cas=13463-67-7",
            headers=_basic("root", "root-password!"),
        )
    ).json()
    top = body["matches"][0]
    assert top["total_mass_percent"] == 40.0
    assert top["n_stages"] == 2
    # Names dedup + sort — both "TiO2" and "TiO2 (topcoat)" survive.
    assert "TiO2" in top["stage_names"]
    assert any("topcoat" in n for n in top["stage_names"])


async def test_min_mass_percent_filters_by_sum(
    api_with_pigment_catalog: tuple[AsyncClient, AppSettings],
) -> None:
    """``min_mass_percent=10`` drops the 5% Лаки but keeps the 20% and
    40% Краски.  The HAVING clause acts on the sum, so a recipe whose
    per-stage max is <10 but sum is ≥10 would also pass — that path
    is covered by the 30+10 = 40 recipe in the previous test."""
    api, _ = api_with_pigment_catalog
    body = (
        await api.get(
            "/recipes/by-component?cas=13463-67-7&min_mass_percent=10",
            headers=_basic("root", "root-password!"),
        )
    ).json()
    percents = [m["total_mass_percent"] for m in body["matches"]]
    assert 5.0 not in percents
    assert body["n_recipes"] == 2


async def test_max_mass_percent_filters_by_sum(
    api_with_pigment_catalog: tuple[AsyncClient, AppSettings],
) -> None:
    api, _ = api_with_pigment_catalog
    body = (
        await api.get(
            "/recipes/by-component?cas=13463-67-7&max_mass_percent=25",
            headers=_basic("root", "root-password!"),
        )
    ).json()
    percents = [m["total_mass_percent"] for m in body["matches"]]
    # 40% is dropped; 20 and 5 remain.
    assert percents == [20.0, 5.0]


async def test_category_narrows_the_scan(
    api_with_pigment_catalog: tuple[AsyncClient, AppSettings],
) -> None:
    api, _ = api_with_pigment_catalog
    body = (
        await api.get(
            "/recipes/by-component?cas=13463-67-7&category=Лаки",
            headers=_basic("root", "root-password!"),
        )
    ).json()
    assert body["n_recipes"] == 1
    assert body["matches"][0]["recipe_category"] == "Лаки"


async def test_unknown_cas_returns_zero_no_crash(
    api_with_pigment_catalog: tuple[AsyncClient, AppSettings],
) -> None:
    """An SVHC CAS (or any absent one) must not crash the endpoint."""
    api, _ = api_with_pigment_catalog
    body = (
        await api.get(
            "/recipes/by-component?cas=999-99-9",
            headers=_basic("root", "root-password!"),
        )
    ).json()
    assert body["n_recipes"] == 0
    assert body["matches"] == []


async def test_missing_cas_query_param_is_422(
    api_with_pigment_catalog: tuple[AsyncClient, AppSettings],
) -> None:
    api, _ = api_with_pigment_catalog
    r = await api.get(
        "/recipes/by-component",
        headers=_basic("root", "root-password!"),
    )
    assert r.status_code == 422


async def test_bad_range_clamped_by_query_validators(
    api_with_pigment_catalog: tuple[AsyncClient, AppSettings],
) -> None:
    api, _ = api_with_pigment_catalog
    r = await api.get(
        "/recipes/by-component?cas=13463-67-7&min_mass_percent=-1",
        headers=_basic("root", "root-password!"),
    )
    assert r.status_code == 422
    r = await api.get(
        "/recipes/by-component?cas=13463-67-7&min_mass_percent=101",
        headers=_basic("root", "root-password!"),
    )
    assert r.status_code == 422


async def test_endpoint_is_before_dynamic_recipe_id(
    api_with_pigment_catalog: tuple[AsyncClient, AppSettings],
) -> None:
    """Regression guard: ``/recipes/by-component`` must resolve as a
    fixed segment, not be swallowed by the ``/recipes/{recipe_id}``
    dynamic path.  A wrong route order would give us 404 (recipe
    not found) instead of a proper JSON list."""
    api, _ = api_with_pigment_catalog
    r = await api.get(
        "/recipes/by-component?cas=13463-67-7",
        headers=_basic("root", "root-password!"),
    )
    assert r.status_code == 200
    body = r.json()
    assert "matches" in body  # not a recipe DTO
