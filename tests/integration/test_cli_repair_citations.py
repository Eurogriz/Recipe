"""Tests for the v1.23 repair-citations CLI.

Covers both repair passes (ISBN extraction/autofix, R3 CAS
backfill) plus idempotency and the dry-run mode.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

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
from formulation_workbench.infrastructure.config import (
    AppSettings,
    reset_settings_cache,
)
from formulation_workbench.infrastructure.db.connection import Database
from formulation_workbench.infrastructure.db.models import Base
from formulation_workbench.infrastructure.di import Container
from formulation_workbench.presentation.commands.repair_citations import (
    _isbn13_checksum,
    _main_async,
    _repair_citation,
    _try_isbn_from_text,
)

pytestmark = [pytest.mark.integration]


# --------------------------------------------------------------------------- unit


def test_isbn_regex_extracts_dashed_form() -> None:
    """Regression guard for the specific citation formats the seed uses."""
    assert (
        _try_isbn_from_text("Wicks, Z.W. Organic Coatings. Wiley, 2017. ISBN: 978-1-118-83620-6.")
        is not None
    )


def test_isbn_regex_extracts_undashed_form() -> None:
    assert _try_isbn_from_text("blah ISBN 9780815511502") is not None


def test_isbn_regex_returns_none_when_missing() -> None:
    assert _try_isbn_from_text("no identifier in this string") is None


def test_isbn_autofix_recomputes_bad_checksum() -> None:
    """Real books occasionally have a typo'd check digit in the seed;
    the autofix must produce a valid ISBN pointing at the same book."""
    result = _try_isbn_from_text("ISBN: 978-1-118-83620-6")
    assert result is not None
    # Recomputed to correct check-digit 0.
    assert result.value.replace("-", "").endswith("0")


def test_isbn13_checksum_matches_known_values() -> None:
    # 978-0-8155-1150-2 is a real Noyes Publications ISBN.
    assert _isbn13_checksum("978081551150") == "2"
    # 978-1-118-83620-? — computed as 0.
    assert _isbn13_checksum("978111883620") == "0"


def test_repair_citation_leaves_valid_isbn_alone() -> None:
    """Idempotency guard — a Citation that already has an isbn must
    not be rebuilt (returns None)."""
    from formulation_workbench.domain.value_objects.isbn import Isbn

    cite = Citation(
        authors="T",
        title="T",
        year=2020,
        publisher="Noyes Publications",
        isbn=Isbn("9780815511502"),
    )
    assert _repair_citation(cite) is None


def test_repair_citation_extracts_from_title() -> None:
    cite = Citation(
        authors="A",
        title="Wicks et al. Organic Coatings. Wiley 2017. ISBN: 978-1-118-83620-6.",
        year=2017,
        publisher="Wiley",
    )
    repaired = _repair_citation(cite)
    assert repaired is not None
    assert repaired.isbn is not None
    # Original book — same first 12 digits.
    assert repaired.isbn.value.replace("-", "").startswith("978111883620")


# --------------------------------------------------------------------------- fixtures


def _make_recipe(*, cas_broken: bool = False, isbn_in_title: str = "") -> Recipe:
    """Build a recipe with optional R3/R1 defects for testing."""
    binder_cas = "see-variant" if cas_broken else "mixture"
    title = f"Seed source ISBN: {isbn_in_title}." if isbn_in_title else "Seed source"
    return Recipe(
        id=uuid.uuid4().hex,
        category="Колеры и пигментные пасты",
        subcategory="Универсальные (на воде)",
        binder_type="Acrylic",
        product_class=ProductClass.STANDARD,
        intended_use="repair test seed",
        color="Красный",
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
                        name="PIGMENT",
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
            authors="Test",
            title=title,
            year=2020,
            publisher="Noyes Publications",
        ),
    )


async def _fresh_env(tmp_path: Path) -> AppSettings:
    reset_settings_cache()
    db = tmp_path / "repair.db"
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
    import formulation_workbench.infrastructure.config as cfg

    cfg._cached = settings  # type: ignore[attr-defined]
    return settings


# --------------------------------------------------------------------------- e2e


async def test_full_repair_fixes_both_defects(tmp_path: Path) -> None:
    settings = await _fresh_env(tmp_path)
    container = await Container.build(settings)
    try:
        for _ in range(3):
            await container.create_recipe.execute(
                CreateRecipeCommand(
                    recipe=_make_recipe(cas_broken=True, isbn_in_title="978-1-118-83620-6"),
                    actor="seed",
                )
            )
    finally:
        await container.close()

    rc = await _main_async([])
    assert rc == 0

    # Re-read: every recipe now has ISBN AND real CAS on the binder.
    container = await Container.build(settings)
    try:
        ids = await container.recipe_repository.list_all_ids()
        for rid in ids:
            r = await container.recipe_repository.get_by_id(rid)
            assert r is not None
            assert r.primary_source.isbn is not None
            # No lingering placeholders.
            for stage in r.stages:
                for comp in stage.components:
                    assert comp.cas_number != "see-variant"
    finally:
        await container.close()


async def test_repair_is_idempotent(tmp_path: Path) -> None:
    """Second invocation is a clean no-op — nothing repaired, no error."""
    settings = await _fresh_env(tmp_path)
    container = await Container.build(settings)
    try:
        await container.create_recipe.execute(
            CreateRecipeCommand(
                recipe=_make_recipe(cas_broken=True, isbn_in_title="978-1-118-83620-6"),
                actor="seed",
            )
        )
    finally:
        await container.close()

    rc1 = await _main_async([])
    assert rc1 == 0
    # Second run: nothing to repair.
    rc2 = await _main_async(["--json"])
    assert rc2 == 0


async def test_dry_run_does_not_mutate(tmp_path: Path) -> None:
    settings = await _fresh_env(tmp_path)
    container = await Container.build(settings)
    try:
        await container.create_recipe.execute(
            CreateRecipeCommand(
                recipe=_make_recipe(cas_broken=True, isbn_in_title="978-1-118-83620-6"),
                actor="seed",
            )
        )
    finally:
        await container.close()

    rc = await _main_async(["--dry-run"])
    assert rc == 0
    # Verify state unchanged.
    container = await Container.build(settings)
    try:
        ids = await container.recipe_repository.list_all_ids()
        r = await container.recipe_repository.get_by_id(ids[0])
        assert r is not None
        assert r.primary_source.isbn is None
        for stage in r.stages:
            for comp in stage.components:
                if comp.name == "PIGMENT":
                    assert comp.cas_number == "see-variant"
    finally:
        await container.close()


async def test_skip_flags_narrow_the_work(tmp_path: Path) -> None:
    settings = await _fresh_env(tmp_path)
    container = await Container.build(settings)
    try:
        await container.create_recipe.execute(
            CreateRecipeCommand(
                recipe=_make_recipe(cas_broken=True, isbn_in_title="978-1-118-83620-6"),
                actor="seed",
            )
        )
    finally:
        await container.close()

    # Skip CAS pass — only ISBN gets fixed.
    rc = await _main_async(["--skip-cas"])
    assert rc == 0
    container = await Container.build(settings)
    try:
        ids = await container.recipe_repository.list_all_ids()
        r = await container.recipe_repository.get_by_id(ids[0])
        assert r is not None
        assert r.primary_source.isbn is not None
        # CAS placeholder is still there.
        for stage in r.stages:
            for comp in stage.components:
                if comp.name == "PIGMENT":
                    assert comp.cas_number == "see-variant"
    finally:
        await container.close()


async def test_both_skips_reject(tmp_path: Path) -> None:
    """--skip-isbn + --skip-cas leaves nothing to do — exit 1."""
    await _fresh_env(tmp_path)
    rc = await _main_async(["--skip-isbn", "--skip-cas"])
    assert rc == 1


async def test_empty_catalogue_exits_2(tmp_path: Path) -> None:
    await _fresh_env(tmp_path)
    rc = await _main_async([])
    assert rc == 2


async def test_json_report_shape(tmp_path: Path, capsys) -> None:
    settings = await _fresh_env(tmp_path)
    container = await Container.build(settings)
    try:
        await container.create_recipe.execute(
            CreateRecipeCommand(
                recipe=_make_recipe(cas_broken=True, isbn_in_title="978-1-118-83620-6"),
                actor="seed",
            )
        )
    finally:
        await container.close()

    rc = await _main_async(["--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["processed"] == 1
    outcome = payload["outcomes"][0]
    assert outcome["isbn_fixed"] is True
    assert outcome["cas_placeholders_fixed"] == 1
    assert outcome["isbn_source"] in {"extracted", "autofix-checksum"}
