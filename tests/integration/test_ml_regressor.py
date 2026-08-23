"""End-to-end training + prediction against a synthetic corpus."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from formulation_workbench.domain.entities.experiment import (
    BatchInfo,
    ExperimentRun,
    MeasuredValue,
)
from formulation_workbench.domain.entities.recipe import (
    Component,
    CompositionStage,
    ProcessParams,
    ProductClass,
    Recipe,
)
from formulation_workbench.domain.value_objects.citation import Citation
from formulation_workbench.domain.value_objects.functions import ComponentFunction
from formulation_workbench.domain.value_objects.isbn import Isbn
from formulation_workbench.infrastructure.ml.property_regressor import (
    PropertyRegressor,
    build_training_samples,
)

pytestmark = [pytest.mark.integration]


def _cite() -> Citation:
    return Citation(
        authors="Flick",
        title="WBPF",
        year=1995,
        publisher="Noyes Publications",
        isbn=Isbn("9780815513773"),
    )


def _make_recipe(binder_pct: float, seed: int) -> Recipe:
    """Return a valid recipe parameterised by binder content."""
    water = round(100.0 - binder_pct - 10.0, 2)
    return Recipe(
        id=f"recipe-{seed:04d}",
        category="Краски",
        subcategory="Водно-дисперсионные",
        binder_type="Acrylic",
        product_class=ProductClass.STANDARD,
        intended_use="ML training",
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
                        functional_role=ComponentFunction.VEHICLE,
                    ),
                    Component(
                        name="Acrylic",
                        cas_number="mixture",
                        function="binder",
                        mass_percent=binder_pct,
                        functional_role=ComponentFunction.BINDER,
                    ),
                    Component(
                        name="TiO2",
                        cas_number="13463-67-7",
                        function="pigment",
                        mass_percent=10.0,
                        functional_role=ComponentFunction.PIGMENT,
                    ),
                ),
                process=ProcessParams(equipment="Disperser"),
            ),
        ),
        primary_source=_cite(),
    )


def _run_for(recipe: Recipe, gloss: float, viscosity: float) -> ExperimentRun:
    return (
        ExperimentRun(
            recipe_id=recipe.id,
            recipe_version=1,
            operator="alice",
        )
        .start()
        .complete(
            BatchInfo(batch_number=f"B-{recipe.id}", target_mass_kg=5.0),
            (
                MeasuredValue(property_code="gloss_60", value=gloss),
                MeasuredValue(property_code="viscosity_mid_shear", value=viscosity),
            ),
        )
    )


def _synthetic_corpus(n: int = 30) -> tuple[list[Recipe], list[ExperimentRun]]:
    """Recipes whose measurements depend deterministically on binder %."""
    rng = random.Random(1234)
    recipes: list[Recipe] = []
    runs: list[ExperimentRun] = []
    for i in range(n):
        binder = 20.0 + i * 1.5  # 20..64.5 %
        recipe = _make_recipe(binder, seed=i)
        recipes.append(recipe)
        # Simple deterministic response + tiny noise.
        gloss = 20.0 + 1.5 * binder + rng.uniform(-1.5, 1.5)
        viscosity = 200.0 + 30.0 * binder + rng.uniform(-10.0, 10.0)
        runs.append(_run_for(recipe, gloss, viscosity))
    return recipes, runs


class TestTrainingAndPrediction:
    def test_train_then_predict_recovers_signal(self, tmp_path: Path) -> None:
        recipes, runs = _synthetic_corpus(n=30)
        recipes_by_id = {r.id: r for r in recipes}

        samples = build_training_samples(runs, recipes_by_id)
        assert len(samples) == 30 * 2  # two properties per run

        regressor = PropertyRegressor(storage_dir=tmp_path)
        result = regressor.train(samples)
        codes = {m.property_code for m in result.trained}
        assert codes == {"gloss_60", "viscosity_mid_shear"}
        assert not result.skipped
        for metadata in result.trained:
            # Signal is strong; CV R² should be sane.
            assert metadata.cv_mean_r2 > 0.5
            assert metadata.n_samples == 30
            assert metadata.n_features > 0

        # Predict on a fresh recipe.
        new_recipe = _make_recipe(binder_pct=45.0, seed=999)
        pred_gloss = regressor.predict(new_recipe, "gloss_60")
        assert pred_gloss is not None
        # Linear ground truth: gloss ≈ 20 + 1.5 * 45 = 87.5
        assert 70.0 <= pred_gloss.predicted_value <= 100.0

    def test_skipped_property_when_too_few_samples(self, tmp_path: Path) -> None:
        recipes, runs = _synthetic_corpus(n=3)
        recipes_by_id = {r.id: r for r in recipes}
        samples = build_training_samples(runs, recipes_by_id)
        regressor = PropertyRegressor(storage_dir=tmp_path)
        result = regressor.train(samples)
        assert not result.trained
        assert "gloss_60" in result.skipped
        assert "viscosity_mid_shear" in result.skipped

    def test_predict_returns_none_for_missing_model(self, tmp_path: Path) -> None:
        regressor = PropertyRegressor(storage_dir=tmp_path)
        recipe = _make_recipe(30.0, seed=1)
        assert regressor.predict(recipe, "gloss_60") is None

    def test_metadata_persisted_and_listable(self, tmp_path: Path) -> None:
        recipes, runs = _synthetic_corpus(n=15)
        samples = build_training_samples(runs, {r.id: r for r in recipes})
        regressor = PropertyRegressor(storage_dir=tmp_path)
        regressor.train(samples)

        # Re-instantiate and confirm the models load.
        regressor_reloaded = PropertyRegressor(storage_dir=tmp_path)
        models = regressor_reloaded.list_models()
        assert {m.property_code for m in models} == {"gloss_60", "viscosity_mid_shear"}
        for m in models:
            assert m.fingerprint != ""
            assert m.version.endswith("Z")
