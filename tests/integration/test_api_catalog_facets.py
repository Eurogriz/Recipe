"""Integration tests for /catalog/facets and the fixed /catalog/stats.

These pin down the regression that motivated the endpoint: the UI
recipes page was rendering only 1-2 categories because it inferred
its dropdown from a paginated search response.  With a real
multi-category dataset we now assert that the server returns EVERY
category, that /catalog/stats stops returning {} for its by_category
field, and that search's total_count reports the total number of
matches (not the size of the returned page).
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


# --------------------------------------------------------------------------- helpers


def _basic(username: str, password: str) -> dict[str, str]:
    raw = f"{username}:{password}".encode()
    return {"Authorization": f"Basic {base64.b64encode(raw).decode()}"}


def _make_recipe(category: str, subcategory: str, product_class: ProductClass) -> Recipe:
    """Cheap recipe factory that produces distinct-id rows for the
    same (category, subcategory) so we can seed multi-count facets."""
    return Recipe(
        id=uuid.uuid4().hex,
        category=category,
        subcategory=subcategory,
        binder_type="Acrylic",
        product_class=product_class,
        intended_use="test seed",
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
async def api_with_diverse_catalog(
    tmp_path: Path,
) -> AsyncIterator[AsyncClient]:
    """Seed several categories/subcategories so facets have >2 rows
    and the total_count vs page_size gap is measurable."""
    reset_settings_cache()
    db = tmp_path / "facets.db"
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
    # Seed six recipes across three categories with different
    # subcategories and quality classes.
    container = await Container.build(settings)
    try:
        seed_plan = [
            ("Краски", "Акриловые интерьерные", ProductClass.STANDARD),
            ("Краски", "Акриловые интерьерные", ProductClass.PREMIUM),
            ("Краски", "Латексные фасадные", ProductClass.STANDARD),
            ("Герметики", "Силиконовые", ProductClass.STANDARD),
            ("Герметики", "Силиконовые", ProductClass.PREMIUM),
            ("Лаки", "Полиуретановые", ProductClass.PREMIUM),
        ]
        for cat, sub, pc in seed_plan:
            recipe = _make_recipe(cat, sub, pc)
            await container.create_recipe.execute(CreateRecipeCommand(recipe=recipe, actor="seed"))
    finally:
        await container.close()

    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


# --------------------------------------------------------------------------- facets


async def test_facets_expose_every_category(
    api_with_diverse_catalog: AsyncClient,
) -> None:
    """The bug: recipes page only ever saw the first 1-2 categories.
    /catalog/facets must return every one of the three we seeded."""
    api = api_with_diverse_catalog
    r = await api.get("/catalog/facets", headers=_basic("root", "root-password!"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["by_category"].keys()) == {"Краски", "Герметики", "Лаки"}
    assert body["by_category"]["Краски"] == 3
    assert body["by_category"]["Герметики"] == 2
    assert body["by_category"]["Лаки"] == 1
    assert body["total"] == 6


async def test_facets_subcategory_scoped_to_category(
    api_with_diverse_catalog: AsyncClient,
) -> None:
    api = api_with_diverse_catalog
    body = (await api.get("/catalog/facets", headers=_basic("root", "root-password!"))).json()
    assert body["by_subcategory"]["Краски"] == {
        "Акриловые интерьерные": 2,
        "Латексные фасадные": 1,
    }
    assert body["by_subcategory"]["Герметики"] == {"Силиконовые": 2}
    # No dangling entries from other categories.
    assert set(body["by_subcategory"].keys()) == {"Краски", "Герметики", "Лаки"}


async def test_facets_product_class_counts(
    api_with_diverse_catalog: AsyncClient,
) -> None:
    api = api_with_diverse_catalog
    body = (await api.get("/catalog/facets", headers=_basic("root", "root-password!"))).json()
    # 3 Standard + 3 Premium seeded.
    assert body["by_product_class"]["Standard"] == 3
    assert body["by_product_class"]["Premium"] == 3


async def test_facets_status_breakdown_included(
    api_with_diverse_catalog: AsyncClient,
) -> None:
    api = api_with_diverse_catalog
    body = (await api.get("/catalog/facets", headers=_basic("root", "root-password!"))).json()
    # All freshly-created recipes land in Draft.
    assert body["by_status"].get("Draft", 0) == 6


async def test_facets_requires_reader_scope(
    api_with_diverse_catalog: AsyncClient,
) -> None:
    """No credentials → 401 (open-mode gate depends on settings; here
    we run with api_token='' + rate_limit_enabled=False → open mode
    still grants everything, so we don't assert 401 here.  The
    require_reader guard is exercised elsewhere by test_api_auth.)"""
    api = api_with_diverse_catalog
    # Open mode returns 200; a stricter deployment would 401.  Just
    # smoke test that the endpoint answers.
    r = await api.get("/catalog/facets")
    assert r.status_code == 200


# --------------------------------------------------------------------------- stats


async def test_catalog_stats_by_category_no_longer_empty(
    api_with_diverse_catalog: AsyncClient,
) -> None:
    """Historical bug: /catalog/stats returned by_category={}.
    Since v1.19 it must be populated from the real query."""
    api = api_with_diverse_catalog
    r = await api.get("/catalog/stats", headers=_basic("root", "root-password!"))
    body = r.json()
    assert body["by_category"] == {"Герметики": 2, "Краски": 3, "Лаки": 1}
    assert body["by_product_class"] == {"Premium": 3, "Standard": 3}


# --------------------------------------------------------------------------- search total_count


async def test_search_total_count_reflects_real_total(
    api_with_diverse_catalog: AsyncClient,
) -> None:
    """The other historical bug: search returned len(page) as total.
    Now the total must reflect the whole matching set, so pagination
    can render "N of TOTAL" honestly."""
    api = api_with_diverse_catalog
    # Restrict to Краски (3 seeded), page size 1.
    r = await api.get(
        "/recipes?category=Краски&limit=1",
        headers=_basic("root", "root-password!"),
    )
    body = r.json()
    assert len(body["items"]) == 1
    assert body["total_count"] == 3
    assert body["has_more"] is True


async def test_search_supports_subcategory_filter(
    api_with_diverse_catalog: AsyncClient,
) -> None:
    """v1.19 added the subcategory query param — verify it filters."""
    api = api_with_diverse_catalog
    r = await api.get(
        "/recipes?category=Краски&subcategory=Акриловые интерьерные",
        headers=_basic("root", "root-password!"),
    )
    body = r.json()
    assert body["total_count"] == 2
    assert all(item["subcategory"] == "Акриловые интерьерные" for item in body["items"])


async def test_search_empty_filter_returns_full_catalog(
    api_with_diverse_catalog: AsyncClient,
) -> None:
    """Regression guard: unfiltered search must see all 6 rows."""
    api = api_with_diverse_catalog
    r = await api.get("/recipes", headers=_basic("root", "root-password!"))
    body = r.json()
    assert body["total_count"] == 6
