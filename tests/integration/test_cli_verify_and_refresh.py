"""Smoke tests for the v1.20 bootstrap CLIs.

Both are small facades — the heavy logic lives in the use cases and
the domain snapshot they wrap.  We assert only that:

  * ``formulation-verify-catalog`` walks a real seed through the
    workflow and lands rows in ``Verified``.
  * ``formulation-refresh-reach`` writes the compiled snapshot to
    disk with the expected header + row counts and refuses to
    overwrite without ``--force``.
"""

from __future__ import annotations

import csv
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
from formulation_workbench.domain.value_objects.doi import Doi
from formulation_workbench.domain.value_objects.isbn import Isbn
from formulation_workbench.infrastructure.config import AppSettings, reset_settings_cache
from formulation_workbench.infrastructure.db.connection import Database
from formulation_workbench.infrastructure.db.models import Base
from formulation_workbench.infrastructure.di import Container
from formulation_workbench.presentation.commands.refresh_reach import (
    _main_async as refresh_main_async,
)
from formulation_workbench.presentation.commands.verify_catalog import (
    _main_async as verify_main_async,
)

pytestmark = [pytest.mark.integration]


# --------------------------------------------------------------------------- helpers


def _make_recipe(i: int, *, with_identifier: bool = True) -> Recipe:
    """Build a minimal but valid recipe.

    ``with_identifier=True`` gives it an ISBN so R1 lets it through
    the review workflow; ``False`` intentionally omits identifiers so
    the verify-catalog CLI can be shown to refuse gracefully.
    """
    return Recipe(
        id=uuid.uuid4().hex,
        category="Краски",
        subcategory=f"seed-{i}",
        binder_type="Acrylic",
        product_class=ProductClass.STANDARD,
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
            isbn=Isbn("9780815513773") if with_identifier else None,
            doi=Doi("10.1234/example") if not with_identifier else None,
        )
        if with_identifier
        else Citation(
            authors="T",
            title="T",
            year=2020,
            publisher="Noyes Publications",
        ),
    )


async def _fresh_env(tmp_path: Path) -> AppSettings:
    """Fresh SQLite + pinned settings cache."""
    reset_settings_cache()
    db = tmp_path / "verify.db"
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
        regulatory_data_dir=tmp_path / "regulatory",
    )
    import formulation_workbench.infrastructure.config as cfg

    cfg._cached = settings  # type: ignore[attr-defined]
    return settings


# --------------------------------------------------------------------------- verify-catalog


async def test_verify_catalog_moves_recipes_to_verified(tmp_path: Path) -> None:
    settings = await _fresh_env(tmp_path)
    container = await Container.build(settings)
    try:
        for i in range(3):
            await container.create_recipe.execute(
                CreateRecipeCommand(recipe=_make_recipe(i), actor="seed")
            )
    finally:
        await container.close()

    rc = await verify_main_async(["--actor", "bootstrap-admin"])
    assert rc == 0

    # Re-inspect the DB.
    container = await Container.build(settings)
    try:
        by_status = await container.recipe_repository.count_by_status()
        # All three should have landed in Verified — the seed uses a
        # real ISBN so R1 doesn't block.
        from formulation_workbench.domain.value_objects.verification_status import (
            VerificationState,
        )

        assert by_status[VerificationState.VERIFIED] == 3
        assert by_status[VerificationState.DRAFT] == 0
    finally:
        await container.close()


async def test_verify_catalog_exit_2_when_no_recipes(tmp_path: Path) -> None:
    await _fresh_env(tmp_path)
    rc = await verify_main_async(["--actor", "bootstrap"])
    # Empty catalogue → distinct exit code so CI can tell "nothing
    # to do" from a real error.
    assert rc == 2


async def test_verify_catalog_dry_run_does_not_mutate(tmp_path: Path) -> None:
    settings = await _fresh_env(tmp_path)
    container = await Container.build(settings)
    try:
        await container.create_recipe.execute(
            CreateRecipeCommand(recipe=_make_recipe(0), actor="seed")
        )
    finally:
        await container.close()

    rc = await verify_main_async(["--actor", "x", "--dry-run"])
    assert rc == 0

    container = await Container.build(settings)
    try:
        from formulation_workbench.domain.value_objects.verification_status import (
            VerificationState,
        )

        by_status = await container.recipe_repository.count_by_status()
        assert by_status[VerificationState.DRAFT] == 1
        assert by_status[VerificationState.VERIFIED] == 0
    finally:
        await container.close()


async def test_verify_catalog_rejects_empty_actor(tmp_path: Path) -> None:
    await _fresh_env(tmp_path)
    rc = await verify_main_async(["--actor", "   "])
    assert rc == 1


async def test_verify_catalog_json_report(tmp_path: Path, capsys) -> None:
    settings = await _fresh_env(tmp_path)
    container = await Container.build(settings)
    try:
        for i in range(2):
            await container.create_recipe.execute(
                CreateRecipeCommand(recipe=_make_recipe(i), actor="seed")
            )
    finally:
        await container.close()

    rc = await verify_main_async(["--actor", "x", "--json"])
    captured = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(captured)
    assert payload["processed"] == 2
    assert payload["verified"] == 2
    assert payload["failed"] == []


# --------------------------------------------------------------------------- refresh-reach


async def test_refresh_reach_writes_snapshot(tmp_path: Path) -> None:
    reset_settings_cache()
    out = tmp_path / "reg"
    rc = await refresh_main_async(["--output-dir", str(out)])
    assert rc == 0
    svhc = out / "reach_svhc.csv"
    annex = out / "reach_annex_xvii.csv"
    assert svhc.exists()
    assert annex.exists()

    # Header shape matches the loader's expectations.
    with svhc.open(encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        rows = list(reader)
    assert header == ["cas_number", "name", "reference", "notes"]
    assert len(rows) >= 15  # at least the built-in snapshot size
    # Every CAS looks like ``\d{2,7}-\d{2}-\d`` — the loader's regex.
    import re

    cas_pattern = re.compile(r"^\d{2,7}-\d{2}-\d$")
    for row in rows:
        assert cas_pattern.match(row[0]), f"bad CAS: {row[0]}"


async def test_refresh_reach_refuses_overwrite_without_force(tmp_path: Path) -> None:
    reset_settings_cache()
    out = tmp_path / "reg"
    # First call: creates the files.
    rc1 = await refresh_main_async(["--output-dir", str(out)])
    assert rc1 == 0
    # Second call: should refuse (exit 2) without --force.
    rc2 = await refresh_main_async(["--output-dir", str(out)])
    assert rc2 == 2
    # Third call: --force wins.
    rc3 = await refresh_main_async(["--output-dir", str(out), "--force"])
    assert rc3 == 0


async def test_refresh_reach_json_summary(tmp_path: Path, capsys) -> None:
    reset_settings_cache()
    out = tmp_path / "reg"
    rc = await refresh_main_async(["--output-dir", str(out), "--json"])
    assert rc == 0
    captured = capsys.readouterr().out
    # The JSON summary is the LAST thing on stdout — logger output
    # goes to stderr, so parsing the whole stdout should be safe.
    payload = json.loads(captured)
    assert payload["source"] == "snapshot"
    assert payload["svhc_rows"] >= 15
    assert payload["annex_rows"] >= 5
    assert payload["svhc_written"] is True
    assert payload["annex_written"] is True
