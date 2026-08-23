"""Integration tests for ``formulation-train-models``.

Full end-to-end: seed a small catalogue with real experiments, run
the CLI, verify weights land on disk with correct metadata.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from formulation_workbench.application.use_cases.apply_lab_results import (
    ApplyLabResultsCommand,
)
from formulation_workbench.application.use_cases.create_recipe import (
    CreateRecipeCommand,
)
from formulation_workbench.domain.entities.experiment import (
    BatchInfo,
    ExperimentRun,
    ExperimentStatus,
    MeasuredValue,
    Verdict,
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
from formulation_workbench.infrastructure.di import Container
from formulation_workbench.presentation.commands.train_models import _main_async

pytestmark = [pytest.mark.integration]


# --------------------------------------------------------------------------- helpers


def _make_recipe(seed_i: int) -> Recipe:
    """Slight per-recipe variation so training samples aren't clones."""
    binder_share = 20.0 + (seed_i % 5) * 2.0  # 20..28
    return Recipe(
        id=uuid.uuid4().hex,
        category="Краски" if seed_i % 2 == 0 else "Лаки",
        subcategory=f"seed-{seed_i}",
        binder_type="Acrylic",
        product_class=ProductClass.STANDARD,
        intended_use="training seed",
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
                        mass_percent=100.0 - 15.0 - binder_share,
                        tolerance_percent=1.0,
                    ),
                    Component(
                        name="Binder",
                        cas_number="mixture",
                        function="binder",
                        mass_percent=binder_share,
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


async def _seed_catalogue(settings: AppSettings, n_recipes: int = 12) -> list[str]:
    """Create ``n_recipes`` recipes + one completed experiment each."""
    container = await Container.build(settings)
    recipe_ids: list[str] = []
    try:
        for i in range(n_recipes):
            recipe = _make_recipe(i)
            await container.create_recipe.execute(CreateRecipeCommand(recipe=recipe, actor="seed"))
            recipe_ids.append(recipe.id)

            # Vary the target smoothly with i so the model has real signal.
            gloss = 60.0 + (i % 5) * 5.0
            run = ExperimentRun(
                id=uuid.uuid4().hex,
                recipe_id=recipe.id,
                recipe_version=1,
                title=f"seed-{i}",
                status=ExperimentStatus.COMPLETED,
                verdict=Verdict.PASSED,
                batch=BatchInfo(
                    batch_number=f"B-{i:03d}",
                    target_mass_kg=1.0,
                    actual_mass_kg=1.0,
                ),
                measured_properties=(
                    MeasuredValue(
                        property_code="gloss_60",
                        value=gloss,
                        unit="GU",
                        measured_at=datetime.now(timezone.utc),
                    ),
                ),
                operator="tester",
                completed_at=datetime.now(timezone.utc),
            )
            await container.experiment_repository.save(run)
            await container.apply_lab_results.execute(
                ApplyLabResultsCommand(experiment_id=run.id, actor="seed")
            )
    finally:
        await container.close()
    return recipe_ids


async def _make_settings(tmp_path: Path) -> AppSettings:
    reset_settings_cache()
    db = tmp_path / "train.db"
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


async def test_full_catalogue_training_writes_weights(tmp_path: Path) -> None:
    settings = await _make_settings(tmp_path)
    await _seed_catalogue(settings, n_recipes=12)

    rc = await _main_async([])
    assert rc == 0
    weights = tmp_path / "models" / "gloss_60.pkl"
    meta = tmp_path / "models" / "gloss_60.meta.json"
    samples = tmp_path / "models" / "gloss_60.samples.json"
    assert weights.exists(), "weights file must land on disk"
    assert meta.exists(), "metadata file must land on disk"
    assert samples.exists(), "training-set fingerprint file must land on disk"
    metadata = json.loads(meta.read_text(encoding="utf-8"))
    assert metadata["n_samples"] == 12
    assert metadata["property_code"] == "gloss_60"
    assert len(metadata["training_recipe_ids"]) == 12
    # We only assert that a numeric cv_mean_r2 was written — the
    # value depends on the tiny synthetic signal and the stacking
    # model's ability to fit it, and on a 12-sample corpus it can
    # easily be negative.  Meaningful R² thresholds are enforced
    # via the --min-r2 gate in a separate test.
    assert isinstance(metadata["cv_mean_r2"], float)


async def test_empty_catalogue_exits_2(tmp_path: Path) -> None:
    """A cold-start with no experiments must return exit code 2 —
    distinct from a bad flag (1) or a metric regression (3)."""
    await _make_settings(tmp_path)
    rc = await _main_async([])
    assert rc == 2


async def test_min_r2_gate_fails_on_regression(tmp_path: Path) -> None:
    """The --min-r2 gate is the CI safety net."""
    settings = await _make_settings(tmp_path)
    await _seed_catalogue(settings, n_recipes=8)
    # An impossible threshold → gate refuses.
    rc = await _main_async(["--min-r2", "0.9999999"])
    assert rc == 3


async def test_min_r2_flag_range_validation(tmp_path: Path) -> None:
    await _make_settings(tmp_path)
    rc = await _main_async(["--min-r2", "2.0"])
    assert rc == 1


async def test_json_report_is_parseable(tmp_path: Path, capsys) -> None:
    settings = await _make_settings(tmp_path)
    await _seed_catalogue(settings, n_recipes=10)
    rc = await _main_async(["--json"])
    captured = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(captured)
    assert "trained" in payload
    assert len(payload["trained"]) >= 1
    entry = payload["trained"][0]
    assert entry["property_code"] == "gloss_60"
    assert entry["n_samples"] == 10
    assert "cv_mean_r2" in entry
    assert "algorithm" in entry


async def test_property_filter_narrows_training(tmp_path: Path) -> None:
    """--property gloss_60 must not attempt to train other codes."""
    settings = await _make_settings(tmp_path)
    await _seed_catalogue(settings, n_recipes=10)
    rc = await _main_async(["--property", "gloss_60"])
    assert rc == 0
    weights_dir = tmp_path / "models"
    assert (weights_dir / "gloss_60.pkl").exists()
    # The seed only measured gloss_60 anyway, so the negative side
    # of this test is trivial; the main point is that the flag is
    # accepted and the code trains.
