"""SQLAlchemy round-trip tests for ExperimentRun persistence."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio

from formulation_workbench.domain.entities.experiment import (
    BatchInfo,
    ExperimentRun,
    MeasuredValue,
    Verdict,
)
from formulation_workbench.domain.value_objects.target_properties import (
    TargetSpecification,
    ToleranceMode,
)
from formulation_workbench.infrastructure.db.connection import Database
from formulation_workbench.infrastructure.db.models import Base
from formulation_workbench.infrastructure.db.repositories.sqlalchemy_experiment_repository import (
    ScopedExperimentRepository,
)

pytestmark = [pytest.mark.integration]


@pytest_asyncio.fixture
async def repo(tmp_path: Path) -> AsyncIterator[ScopedExperimentRepository]:
    db_file = tmp_path / "exp.db"
    db = Database.from_url(url=f"sqlite+aiosqlite:///{db_file}")
    await db.init()
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield ScopedExperimentRepository(db)
    await db.close()


def _planned(recipe_id: str = "recipe-1") -> ExperimentRun:
    return ExperimentRun(
        recipe_id=recipe_id,
        recipe_version=1,
        title="Trial 1",
        hypothesis="Verify gloss target",
        operator="alice",
        target_properties=(
            TargetSpecification(property_code="gloss_60", target_value=80.0, tolerance=5.0),
            TargetSpecification(
                property_code="voc_content",
                target_value=30.0,
                tolerance_mode=ToleranceMode.MAX,
            ),
        ),
    )


async def test_save_and_load_planned(repo: ScopedExperimentRepository) -> None:
    run = _planned()
    await repo.save(run)

    loaded = await repo.get_by_id(run.id)
    assert loaded is not None
    assert loaded.id == run.id
    assert loaded.title == "Trial 1"
    assert loaded.operator == "alice"
    assert loaded.status.value == "planned"
    assert len(loaded.target_properties) == 2
    assert loaded.target_properties[0].property_code == "gloss_60"


async def test_complete_then_reload(repo: ScopedExperimentRepository) -> None:
    run = (
        _planned()
        .start()
        .complete(
            BatchInfo(
                batch_number="B-001",
                target_mass_kg=10.0,
                actual_mass_kg=9.9,
                equipment_used="Disperser",
                lot_numbers={"Water": "L-42"},
            ),
            (
                MeasuredValue(property_code="gloss_60", value=82.0, unit="GU", operator="alice"),
                MeasuredValue(property_code="voc_content", value=25.0, unit="g/L"),
            ),
        )
    )
    await repo.save(run)

    loaded = await repo.get_by_id(run.id)
    assert loaded is not None
    assert loaded.status.value == "completed"
    assert loaded.verdict is Verdict.PASSED
    assert loaded.batch is not None
    assert loaded.batch.batch_number == "B-001"
    assert loaded.batch.lot_numbers == {"Water": "L-42"}
    assert len(loaded.measured_properties) == 2
    codes = {mv.property_code for mv in loaded.measured_properties}
    assert codes == {"gloss_60", "voc_content"}


async def test_get_missing_returns_none(repo: ScopedExperimentRepository) -> None:
    assert await repo.get_by_id("does-not-exist") is None


async def test_list_for_recipe(repo: ScopedExperimentRepository) -> None:
    run_a = _planned(recipe_id="recipe-A")
    run_b = _planned(recipe_id="recipe-A")
    run_c = _planned(recipe_id="recipe-B")
    for r in (run_a, run_b, run_c):
        await repo.save(r)

    only_a = await repo.list_for_recipe("recipe-A")
    assert {r.id for r in only_a} == {run_a.id, run_b.id}

    only_c = await repo.list_for_recipe("recipe-B")
    assert {r.id for r in only_c} == {run_c.id}


async def test_replace_measurements_updates_row(repo: ScopedExperimentRepository) -> None:
    """Saving twice with different measurements must succeed (no UNIQUE trip)."""
    run = (
        _planned()
        .start()
        .complete(
            BatchInfo(batch_number="B-1", target_mass_kg=5.0),
            (
                MeasuredValue(property_code="gloss_60", value=80.0),
                MeasuredValue(property_code="voc_content", value=25.0),
            ),
        )
    )
    await repo.save(run)

    # Simulate an out-of-band correction:
    revised = ExperimentRun(
        recipe_id=run.recipe_id,
        recipe_version=run.recipe_version,
        id=run.id,
        title=run.title,
        hypothesis=run.hypothesis,
        status=run.status,
        verdict=run.verdict,
        batch=run.batch,
        target_properties=run.target_properties,
        measured_properties=(
            MeasuredValue(property_code="gloss_60", value=85.0),  # updated
            MeasuredValue(property_code="voc_content", value=20.0),  # updated
        ),
        operator=run.operator,
        created_at=run.created_at,
        completed_at=run.completed_at,
    )
    await repo.save(revised)

    loaded = await repo.get_by_id(run.id)
    assert loaded is not None
    values = {mv.property_code: mv.value for mv in loaded.measured_properties}
    assert values == {"gloss_60": 85.0, "voc_content": 20.0}
