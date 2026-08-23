"""Integration test for the ``formulation-production-vectors`` CLI.

Runs the parser (unit-level: no DB roundtrip) + the full ingest path
against a temp SQLite database via ``settings`` monkeypatch.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from formulation_workbench.infrastructure.config import (
    AppSettings,
    get_settings,
    reset_settings_cache,
)
from formulation_workbench.infrastructure.db.connection import Database
from formulation_workbench.infrastructure.db.models import Base
from formulation_workbench.infrastructure.ml.features import FEATURE_NAMES
from formulation_workbench.presentation.commands.production_vectors import (
    _main_async,
    _parse_csv,
    _parse_json,
)

pytestmark = [pytest.mark.integration]


# --------------------------------------------------------------------------- parsers


def test_parse_json_accepts_array(tmp_path: Path) -> None:
    p = tmp_path / "items.json"
    p.write_text(
        json.dumps(
            [
                {"recipe_id": "r1"},
                {"recipe_id": "r2", "features": [0.0] * len(FEATURE_NAMES)},
            ]
        ),
        encoding="utf-8",
    )
    got = _parse_json(p)
    assert len(got) == 2
    assert got[0]["recipe_id"] == "r1"
    assert len(got[1]["features"]) == len(FEATURE_NAMES)


def test_parse_json_accepts_items_envelope(tmp_path: Path) -> None:
    p = tmp_path / "items.json"
    p.write_text(json.dumps({"items": [{"recipe_id": "r1"}]}), encoding="utf-8")
    assert len(_parse_json(p)) == 1


def test_parse_csv_without_features(tmp_path: Path) -> None:
    p = tmp_path / "rows.csv"
    with p.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["recipe_id", "source", "notes"])
        w.writerow(["r1", "production", "batch-42"])
    rows = _parse_csv(p)
    assert rows[0]["recipe_id"] == "r1"
    assert rows[0]["source"] == "production"
    assert rows[0]["notes"] == "batch-42"
    assert "features" not in rows[0]


def test_parse_csv_with_features(tmp_path: Path) -> None:
    p = tmp_path / "rows.csv"
    with p.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["recipe_id", "source", *FEATURE_NAMES])
        w.writerow(["r1", "production", *[str(float(i)) for i in range(len(FEATURE_NAMES))]])
    rows = _parse_csv(p)
    assert len(rows[0]["features"]) == len(FEATURE_NAMES)
    assert rows[0]["features"][0] == 0.0
    assert rows[0]["features"][-1] == float(len(FEATURE_NAMES) - 1)


def test_parse_csv_rejects_reordered_features(tmp_path: Path) -> None:
    p = tmp_path / "rows.csv"
    swapped = [*FEATURE_NAMES[::-1]]  # reversed order → refuse
    with p.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["recipe_id", *swapped])
        w.writerow(["r1", *[str(float(i)) for i in range(len(FEATURE_NAMES))]])
    with pytest.raises(ValueError, match="feature columns must exactly match"):
        _parse_csv(p)


# --------------------------------------------------------------------------- end-to-end CLI


async def _fresh_db(tmp_path: Path) -> AppSettings:
    reset_settings_cache()
    db = tmp_path / "cli.db"
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
    # get_settings() is a module-level cache the CLI reads; patch it.
    import formulation_workbench.infrastructure.config as cfg

    cfg._cached = settings  # type: ignore[attr-defined]
    return settings


async def test_cli_end_to_end_ingest(tmp_path: Path) -> None:
    await _fresh_db(tmp_path)
    # Pre-load one recipe via the domain so server-side extraction works.
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
    from formulation_workbench.infrastructure.di import Container

    container = await Container.build(get_settings())
    try:
        recipe = Recipe(
            id="cli-r1",
            category="Paints",
            subcategory="test",
            binder_type="Acrylic",
            product_class=ProductClass.STANDARD,
            intended_use="Test",
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
                            mass_percent=50.0,
                            tolerance_percent=1.0,
                        ),
                        Component(
                            name="Binder",
                            cas_number="mixture",
                            function="binder",
                            mass_percent=30.0,
                            tolerance_percent=1.0,
                        ),
                        Component(
                            name="TiO2",
                            cas_number="13463-67-7",
                            function="pigment",
                            mass_percent=20.0,
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
        await container.create_recipe.execute(CreateRecipeCommand(recipe=recipe, actor="test"))
    finally:
        await container.close()

    # Write a JSON payload: one row with recipe_id, one with features
    # verbatim, one with an unknown recipe (should be skipped).
    payload = [
        {"recipe_id": "cli-r1", "source": "lab"},
        {
            "recipe_id": "cli-external",
            "features": [0.0] * len(FEATURE_NAMES),
            "source": "production",
            "notes": "SAP",
        },
        {"recipe_id": "cli-missing"},
    ]
    src = tmp_path / "in.json"
    src.write_text(json.dumps(payload), encoding="utf-8")

    exit_code = await _main_async(["--source", str(src)])
    assert exit_code == 0  # ≥1 accepted → success

    # Now assert the two valid rows landed in the repository.
    container = await Container.build(get_settings())
    try:
        rows = await container.production_vector_repository.list_recent(limit=100)
        assert len(rows) == 2
        assert {r.recipe_id for r in rows} == {"cli-r1", "cli-external"}
    finally:
        await container.close()


async def test_cli_returns_nonzero_when_nothing_accepted(tmp_path: Path) -> None:
    await _fresh_db(tmp_path)
    src = tmp_path / "in.json"
    src.write_text(json.dumps([{"recipe_id": "does-not-exist"}]), encoding="utf-8")
    exit_code = await _main_async(["--source", str(src)])
    assert exit_code == 1


async def test_cli_fail_on_any_skip_flag(tmp_path: Path) -> None:
    await _fresh_db(tmp_path)
    src = tmp_path / "in.json"
    src.write_text(
        json.dumps(
            [
                {
                    "recipe_id": "external",
                    "features": [0.0] * len(FEATURE_NAMES),
                },
                {"recipe_id": "does-not-exist"},  # will be skipped
            ]
        ),
        encoding="utf-8",
    )
    # Without flag: 0 (one accepted).
    assert await _main_async(["--source", str(src)]) == 0
    # With --fail-on-any-skip: 2.
    src2 = tmp_path / "in2.json"
    src2.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    assert await _main_async(["--source", str(src2), "--fail-on-any-skip"]) == 2


async def test_cli_rejects_missing_file(tmp_path: Path) -> None:
    await _fresh_db(tmp_path)
    exit_code = await _main_async(["--source", str(tmp_path / "nope.json")])
    assert exit_code == 1
