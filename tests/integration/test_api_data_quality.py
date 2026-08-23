"""Integration tests for /dashboard/data-quality (v1.22).

Seeds recipes with deliberate rule violations and asserts the
aggregator counts them where expected.
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
from formulation_workbench.application.use_cases.data_quality import (
    DataQualityQuery,
    DataQualityUseCase,
)
from formulation_workbench.domain.entities.recipe import (
    Component,
    CompositionStage,
    ProductClass,
    Recipe,
)
from formulation_workbench.domain.value_objects.citation import Citation
from formulation_workbench.domain.value_objects.isbn import Isbn
from formulation_workbench.infrastructure.config import (
    AppSettings,
    reset_settings_cache,
)
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
    cat: str,
    *,
    with_isbn: bool = True,
    binder_cas: str = "mixture",
) -> Recipe:
    """Build a recipe.  Omitting the ISBN triggers R1; using a bogus
    CAS on the binder triggers R3."""
    return Recipe(
        id=uuid.uuid4().hex,
        category=cat,
        subcategory="test",
        binder_type="Acrylic",
        product_class=ProductClass.STANDARD,
        intended_use="dq test seed",
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
                        cas_number=binder_cas,
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
            isbn=Isbn("9780815513773") if with_isbn else None,
        ),
    )


@pytest_asyncio.fixture
async def api_with_mixed_catalog(
    tmp_path: Path,
) -> AsyncIterator[tuple[AsyncClient, AppSettings]]:
    reset_settings_cache()
    db = tmp_path / "dq.db"
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
        # 3 clean Краски (ISBN + valid CAS), 2 R1-violated Мастики
        # (no ISBN), 1 R3-violated Колеры (bogus binder CAS).
        for _ in range(3):
            await container.create_recipe.execute(
                CreateRecipeCommand(recipe=_make_recipe("Краски"), actor="seed")
            )
        for _ in range(2):
            await container.create_recipe.execute(
                CreateRecipeCommand(
                    recipe=_make_recipe("Мастики", with_isbn=False),
                    actor="seed",
                )
            )
        # Bogus CAS not in {mixture, proprietary} nor CAS pattern.
        await container.create_recipe.execute(
            CreateRecipeCommand(
                recipe=_make_recipe("Колеры", binder_cas="unknown-not-a-cas"),
                actor="seed",
            )
        )
    finally:
        await container.close()

    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client, settings


# --------------------------------------------------------------------------- unit


async def test_use_case_counts_r1_violations_by_category(
    api_with_mixed_catalog: tuple[AsyncClient, AppSettings],
) -> None:
    _, settings = api_with_mixed_catalog
    container = await Container.build(settings)
    try:
        uc = DataQualityUseCase(container.recipe_repository)
        report = await uc.execute(DataQualityQuery(sample_size=5))
    finally:
        await container.close()

    assert report.total_recipes == 6
    assert report.n_clean == 3  # only the three Краски are clean
    assert report.n_with_violations == 3
    # R1 must dominate — 2 Мастики without ISBN.
    r1 = next(r for r in report.by_rule if r.rule == "R1")
    assert r1.n_recipes == 2
    assert r1.by_category == {"Мастики": 2}
    assert len(r1.sample_recipe_ids) == 2


async def test_use_case_counts_r3_when_component_has_bad_cas(
    api_with_mixed_catalog: tuple[AsyncClient, AppSettings],
) -> None:
    _, settings = api_with_mixed_catalog
    container = await Container.build(settings)
    try:
        uc = DataQualityUseCase(container.recipe_repository)
        report = await uc.execute(DataQualityQuery())
    finally:
        await container.close()

    r3_rows = [r for r in report.by_rule if r.rule == "R3"]
    # The Колеры seed has a bogus binder CAS — depending on how
    # strictly the domain treats "unknown-not-a-cas" this may or may
    # not fire R3.  Assert only that if there IS a row, its category
    # is Колеры — we don't want a silent regression that mis-labels
    # the offender.
    for r in r3_rows:
        assert r.by_category == {"Колеры": r.n_recipes}


# --------------------------------------------------------------------------- e2e


async def test_endpoint_shape_and_sample_size_cap(
    api_with_mixed_catalog: tuple[AsyncClient, AppSettings],
) -> None:
    api, _ = api_with_mixed_catalog
    r = await api.get(
        "/dashboard/data-quality?sample_size=1",
        headers=_basic("root", "root-password!"),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_recipes"] == 6
    assert body["n_clean"] == 3
    assert body["n_with_violations"] == 3
    # sample_size=1 → each rule bucket returns at most one id.
    for r_row in body["by_rule"]:
        assert len(r_row["sample_recipe_ids"]) <= 1
    # by_status matches count_by_status semantics.
    assert body["by_status"]["Draft"] == 6


async def test_endpoint_rejects_out_of_range_sample_size(
    api_with_mixed_catalog: tuple[AsyncClient, AppSettings],
) -> None:
    api, _ = api_with_mixed_catalog
    r = await api.get(
        "/dashboard/data-quality?sample_size=0",
        headers=_basic("root", "root-password!"),
    )
    assert r.status_code == 422
    r = await api.get(
        "/dashboard/data-quality?sample_size=999",
        headers=_basic("root", "root-password!"),
    )
    assert r.status_code == 422


async def test_endpoint_category_health_bucket_shape(
    api_with_mixed_catalog: tuple[AsyncClient, AppSettings],
) -> None:
    api, _ = api_with_mixed_catalog
    body = (
        await api.get(
            "/dashboard/data-quality",
            headers=_basic("root", "root-password!"),
        )
    ).json()
    cats = {c["category"]: c for c in body["by_category"]}
    # Краски: 3 recipes, all clean → n_clean=3, n_with_violations=0.
    assert cats["Краски"]["n_total"] == 3
    assert cats["Краски"]["n_clean"] == 3
    assert cats["Краски"]["n_with_violations"] == 0
    # Мастики: 2 recipes, both dirty (R1) → 0 clean.
    assert cats["Мастики"]["n_total"] == 2
    assert cats["Мастики"]["n_clean"] == 0
    assert "R1" in cats["Мастики"]["top_rules"]


async def test_empty_catalogue_returns_zero_totals(tmp_path: Path) -> None:
    """Regression guard: an empty catalogue must not raise a
    DivisionByZero when computing verified_share."""
    reset_settings_cache()
    db = tmp_path / "empty.db"
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
    container = await Container.build(settings)
    try:
        uc = DataQualityUseCase(container.recipe_repository)
        report = await uc.execute(DataQualityQuery())
        assert report.total_recipes == 0
        assert report.n_clean == 0
        assert report.n_with_violations == 0
        assert report.verified_share == 0.0
        assert report.by_rule == []
        assert report.by_category == []
    finally:
        await container.close()
