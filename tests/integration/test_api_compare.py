"""Integration tests for /recipes/compare (v1.26).

Seeds recipes with controlled overlaps and asserts:
  * union of CAS across compared recipes forms the row set;
  * ``is_diff`` is True for rows present in some recipes but not
    others, AND for rows where the mass_percent spread exceeds the
    threshold;
  * ordering is by max mass_percent DESC (dominant material first);
  * property predictions fill cells when trained, ``None`` otherwise;
  * the endpoint enforces the 2..4 range and rejects duplicates.
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


def _make_recipe(
    category: str,
    subcategory: str,
    *,
    water: float,
    tio2: float,
    binder: float,
    binder_cas: str = "mixture",
) -> Recipe:
    """Build a recipe with three components summing ~100%."""
    return Recipe(
        id=uuid.uuid4().hex,
        category=category,
        subcategory=subcategory,
        binder_type="Acrylic",
        product_class=ProductClass.STANDARD,
        intended_use="compare test seed",
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
                        mass_percent=water,
                        tolerance_percent=1.0,
                    ),
                    Component(
                        name="TiO2",
                        cas_number="13463-67-7",
                        function="pigment",
                        mass_percent=tio2,
                        tolerance_percent=1.0,
                    ),
                    Component(
                        name="Binder",
                        cas_number=binder_cas,
                        function="binder",
                        mass_percent=binder,
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
            isbn=Isbn("9780815511502"),
        ),
    )


@pytest_asyncio.fixture
async def api_with_compare_catalog(
    tmp_path: Path,
) -> AsyncIterator[tuple[AsyncClient, list[str]]]:
    reset_settings_cache()
    db = tmp_path / "cmp.db"
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

    ids: list[str] = []
    container = await Container.build(settings)
    try:
        # Recipe A: 60% water + 15% TiO2 + 25% mixture
        r_a = _make_recipe("Краски", "A", water=60.0, tio2=15.0, binder=25.0)
        await container.create_recipe.execute(CreateRecipeCommand(recipe=r_a, actor="s"))
        ids.append(r_a.id)
        # Recipe B: 55% water + 20% TiO2 + 25% mixture — small TiO2
        # spread (5 > 0.1 threshold → is_diff), and shares every CAS.
        r_b = _make_recipe("Краски", "B", water=55.0, tio2=20.0, binder=25.0)
        await container.create_recipe.execute(CreateRecipeCommand(recipe=r_b, actor="s"))
        ids.append(r_b.id)
        # Recipe C: same shape but with proprietary binder (differs
        # from A/B on the binder CAS entirely).
        r_c = _make_recipe(
            "Краски",
            "C",
            water=55.0,
            tio2=20.0,
            binder=25.0,
            binder_cas="proprietary",
        )
        await container.create_recipe.execute(CreateRecipeCommand(recipe=r_c, actor="s"))
        ids.append(r_c.id)
    finally:
        await container.close()

    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client, ids


# --------------------------------------------------------------------------- e2e


async def test_compare_two_recipes_shapes_response(
    api_with_compare_catalog: tuple[AsyncClient, list[str]],
) -> None:
    api, ids = api_with_compare_catalog
    r = await api.get(
        f"/recipes/compare?ids={ids[0]},{ids[1]}",
        headers=_basic("root", "root-password!"),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # 2 columns.
    assert len(body["recipes"]) == 2
    # 3 CAS (water, tio2, mixture) all shared by both recipes.
    assert len(body["components"]) == 3
    # Every row has exactly 2 cells (one per compared recipe).
    for row in body["components"]:
        assert len(row["cells"]) == 2


async def test_compare_flags_diff_when_mass_percent_spread(
    api_with_compare_catalog: tuple[AsyncClient, list[str]],
) -> None:
    """Water spread 55 vs 60 = 5 > threshold 0.1 → is_diff=True."""
    api, ids = api_with_compare_catalog
    body = (
        await api.get(
            f"/recipes/compare?ids={ids[0]},{ids[1]}",
            headers=_basic("root", "root-password!"),
        )
    ).json()
    water_row = next(r for r in body["components"] if r["cas_number"] == "7732-18-5")
    assert water_row["is_diff"] is True
    tio2_row = next(r for r in body["components"] if r["cas_number"] == "13463-67-7")
    assert tio2_row["is_diff"] is True


async def test_compare_flags_diff_when_row_absent_in_one_recipe(
    api_with_compare_catalog: tuple[AsyncClient, list[str]],
) -> None:
    """Recipe A has binder=mixture; Recipe C has binder=proprietary.
    Both CAS'ы должны быть в отдельных строках, is_diff=True."""
    api, ids = api_with_compare_catalog
    body = (
        await api.get(
            f"/recipes/compare?ids={ids[0]},{ids[2]}",
            headers=_basic("root", "root-password!"),
        )
    ).json()
    mixture_row = next(r for r in body["components"] if r["cas_number"] == "mixture")
    proprietary_row = next(r for r in body["components"] if r["cas_number"] == "proprietary")
    # Each present in exactly one recipe → is_diff=True.
    assert mixture_row["is_diff"] is True
    assert proprietary_row["is_diff"] is True
    # And one cell is None in each.
    mixture_pcts = [c["mass_percent"] for c in mixture_row["cells"]]
    assert None in mixture_pcts


async def test_compare_row_ordering_dominant_first(
    api_with_compare_catalog: tuple[AsyncClient, list[str]],
) -> None:
    """Rows sorted by max mass_percent DESC — water (60) first, then
    binder (25), then TiO2 (20/15)."""
    api, ids = api_with_compare_catalog
    body = (
        await api.get(
            f"/recipes/compare?ids={ids[0]},{ids[1]}",
            headers=_basic("root", "root-password!"),
        )
    ).json()
    order = [r["cas_number"] for r in body["components"]]
    assert order == ["7732-18-5", "mixture", "13463-67-7"]


async def test_compare_diff_threshold_query_param(
    api_with_compare_catalog: tuple[AsyncClient, list[str]],
) -> None:
    """A 10-point threshold silences the water row (5 point spread)
    but keeps TiO2 (5 → still <10, so both silenced now)."""
    api, ids = api_with_compare_catalog
    body = (
        await api.get(
            f"/recipes/compare?ids={ids[0]},{ids[1]}&diff_threshold=10",
            headers=_basic("root", "root-password!"),
        )
    ).json()
    water_row = next(r for r in body["components"] if r["cas_number"] == "7732-18-5")
    tio2_row = next(r for r in body["components"] if r["cas_number"] == "13463-67-7")
    binder_row = next(r for r in body["components"] if r["cas_number"] == "mixture")
    assert water_row["is_diff"] is False
    assert tio2_row["is_diff"] is False
    assert binder_row["is_diff"] is False


async def test_compare_rejects_single_id(
    api_with_compare_catalog: tuple[AsyncClient, list[str]],
) -> None:
    api, ids = api_with_compare_catalog
    r = await api.get(
        f"/recipes/compare?ids={ids[0]}",
        headers=_basic("root", "root-password!"),
    )
    assert r.status_code == 422


async def test_compare_rejects_five_ids(
    api_with_compare_catalog: tuple[AsyncClient, list[str]],
) -> None:
    api, ids = api_with_compare_catalog
    fake_ids = [*ids, uuid.uuid4().hex, uuid.uuid4().hex]
    r = await api.get(
        f"/recipes/compare?ids={','.join(fake_ids)}",
        headers=_basic("root", "root-password!"),
    )
    assert r.status_code == 422


async def test_compare_rejects_duplicates(
    api_with_compare_catalog: tuple[AsyncClient, list[str]],
) -> None:
    api, ids = api_with_compare_catalog
    r = await api.get(
        f"/recipes/compare?ids={ids[0]},{ids[0]}",
        headers=_basic("root", "root-password!"),
    )
    assert r.status_code == 422


async def test_compare_returns_404_on_unknown_id(
    api_with_compare_catalog: tuple[AsyncClient, list[str]],
) -> None:
    api, ids = api_with_compare_catalog
    r = await api.get(
        f"/recipes/compare?ids={ids[0]},{uuid.uuid4().hex}",
        headers=_basic("root", "root-password!"),
    )
    assert r.status_code == 404


async def test_compare_properties_grid_present(
    api_with_compare_catalog: tuple[AsyncClient, list[str]],
) -> None:
    """Fresh catalogue has no trained models → property rows empty,
    but the top-level ``properties`` field still exists (list, not
    None) so the UI can render an empty state cleanly."""
    api, ids = api_with_compare_catalog
    body = (
        await api.get(
            f"/recipes/compare?ids={ids[0]},{ids[1]}",
            headers=_basic("root", "root-password!"),
        )
    ).json()
    assert "properties" in body
    assert isinstance(body["properties"], list)


async def test_compare_route_ordering_regression(
    api_with_compare_catalog: tuple[AsyncClient, list[str]],
) -> None:
    """``/recipes/compare`` MUST resolve as a fixed segment, not be
    eaten by ``/recipes/{recipe_id}``.  Wrong route order would give
    us 404 (no such recipe named 'compare') rather than 422 for the
    missing ``ids`` query param."""
    api, _ = api_with_compare_catalog
    r = await api.get(
        "/recipes/compare",
        headers=_basic("root", "root-password!"),
    )
    # Missing ``ids`` → 422, not 404.
    assert r.status_code == 422
