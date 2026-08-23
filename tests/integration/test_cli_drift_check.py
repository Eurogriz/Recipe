"""Integration test for ``formulation-drift-check`` CLI."""

from __future__ import annotations

from pathlib import Path

import pytest

from formulation_workbench.infrastructure.config import (
    AppSettings,
    reset_settings_cache,
)
from formulation_workbench.infrastructure.db.connection import Database
from formulation_workbench.infrastructure.db.models import Base
from formulation_workbench.infrastructure.notifications import Alert
from formulation_workbench.presentation.commands.drift_check import (
    _main_async,
    _parse_context,
)

pytestmark = [pytest.mark.integration]


# --------------------------------------------------------------------------- helpers


async def _fresh_db(tmp_path: Path) -> AppSettings:
    reset_settings_cache()
    db = tmp_path / "drift.db"
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


class _RecordingNotifier:
    """A stand-in for the DI-provided notifier — records what it saw."""

    def __init__(self, *, accept: bool = True) -> None:
        self.accept = accept
        self.alerts: list[Alert] = []

    async def notify(self, alert: Alert) -> bool:
        self.alerts.append(alert)
        return self.accept


# --------------------------------------------------------------------------- unit


def test_parse_context_pairs() -> None:
    assert _parse_context(["plant=Tallinn", "batch=42"]) == {
        "plant": "Tallinn",
        "batch": "42",
    }


def test_parse_context_rejects_bad_pair() -> None:
    import argparse

    with pytest.raises(argparse.ArgumentTypeError):
        _parse_context(["plant"])
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_context(["=value"])


# --------------------------------------------------------------------------- e2e


async def test_returns_1_when_no_training_snapshot(tmp_path: Path) -> None:
    await _fresh_db(tmp_path)
    exit_code = await _main_async(["--property", "gloss_60", "--source", "catalog", "--limit", "5"])
    assert exit_code == 1


async def _seed_recipe_and_train(settings: AppSettings) -> str:
    """Create one recipe + completed experiments + trained model."""
    from datetime import datetime, timezone

    from formulation_workbench.application.use_cases.create_recipe import (
        CreateRecipeCommand,
    )
    from formulation_workbench.application.use_cases.ml_train import (
        TrainPropertyModelsCommand,
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
    from formulation_workbench.infrastructure.di import Container

    container = await Container.build(settings)
    try:
        rids: list[str] = []
        for i in range(15):
            binder = 20.0 + i * 3.0
            water = 100.0 - binder - 20.0
            recipe = Recipe(
                id=f"r{i}",
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
                                mass_percent=water,
                                tolerance_percent=1.0,
                            ),
                            Component(
                                name="Binder",
                                cas_number="mixture",
                                function="binder",
                                mass_percent=binder,
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
            rids.append(recipe.id)
            run = ExperimentRun(
                id=f"e{i}",
                recipe_id=recipe.id,
                recipe_version=1,
                operator="op",
                status=ExperimentStatus.COMPLETED,
                verdict=Verdict.PASSED,
                created_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
                batch=BatchInfo(batch_number=f"B{i}", target_mass_kg=5.0),
                measured_properties=(
                    MeasuredValue(
                        property_code="gloss_60",
                        value=90.0 - binder + (i % 5),
                        unit="GU",
                        operator="=",
                    ),
                ),
            )
            await container.experiment_repository.save(run)

        await container.train_property_models.execute(
            TrainPropertyModelsCommand(recipe_ids=tuple(rids))
        )
        return rids[0]
    finally:
        await container.close()


async def test_dry_run_returns_3_when_random_source_severe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = await _fresh_db(tmp_path)
    await _seed_recipe_and_train(settings)

    # Ingest 30 production vectors that are all zeros — this always
    # produces severe drift on the model trained above.
    from formulation_workbench.infrastructure.di import Container
    from formulation_workbench.infrastructure.ml.features import FEATURE_NAMES

    container = await Container.build(settings)
    try:
        rows = [(f"ext-{i}", [0.0] * len(FEATURE_NAMES), "production", "") for i in range(30)]
        await container.production_vector_repository.add_many(rows)
    finally:
        await container.close()

    # Swap the notifier so we notice if the CLI tries to dispatch.
    recorder = _RecordingNotifier()
    monkeypatch.setattr(
        "formulation_workbench.infrastructure.di.build_notifier",
        lambda **_: recorder,
    )

    exit_code = await _main_async(
        [
            "--property",
            "gloss_60",
            "--source",
            "production",
            "--limit",
            "30",
            "--dispatch-level",
            "moderate_drift",
            "--context",
            "plant=Tallinn-1",
            "--dry-run",
        ]
    )
    assert exit_code == 3  # drift ≥ threshold detected
    assert recorder.alerts == []  # dry-run must not dispatch

    # The JSON summary is the last line on stdout.
    lines = capsys.readouterr().out.strip().splitlines()
    payload = lines[-1]
    assert '"dry_run": true' in payload
    assert '"plant": "Tallinn-1"' in payload


async def test_dispatches_and_returns_3_when_notifier_accepts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = await _fresh_db(tmp_path)
    await _seed_recipe_and_train(settings)

    from formulation_workbench.infrastructure.di import Container
    from formulation_workbench.infrastructure.ml.features import FEATURE_NAMES

    container = await Container.build(settings)
    try:
        rows = [(f"ext-{i}", [0.0] * len(FEATURE_NAMES), "production", "") for i in range(30)]
        await container.production_vector_repository.add_many(rows)
    finally:
        await container.close()

    recorder = _RecordingNotifier(accept=True)
    monkeypatch.setattr(
        "formulation_workbench.infrastructure.di.build_notifier",
        lambda **_: recorder,
    )

    exit_code = await _main_async(
        [
            "--property",
            "gloss_60",
            "--source",
            "production",
            "--limit",
            "30",
            "--dispatch-level",
            "moderate_drift",
        ]
    )
    assert exit_code == 3
    assert len(recorder.alerts) == 1
    alert = recorder.alerts[0]
    assert alert.kind == "ml.drift"
    assert alert.fields["property_code"] == "gloss_60"


async def test_returns_4_when_notifier_rejects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = await _fresh_db(tmp_path)
    await _seed_recipe_and_train(settings)

    from formulation_workbench.infrastructure.di import Container
    from formulation_workbench.infrastructure.ml.features import FEATURE_NAMES

    container = await Container.build(settings)
    try:
        rows = [(f"ext-{i}", [0.0] * len(FEATURE_NAMES), "production", "") for i in range(30)]
        await container.production_vector_repository.add_many(rows)
    finally:
        await container.close()

    recorder = _RecordingNotifier(accept=False)
    monkeypatch.setattr(
        "formulation_workbench.infrastructure.di.build_notifier",
        lambda **_: recorder,
    )

    exit_code = await _main_async(
        [
            "--property",
            "gloss_60",
            "--source",
            "production",
            "--limit",
            "30",
        ]
    )
    assert exit_code == 4
