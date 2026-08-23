"""Unit tests for the RandomForest-inverse optimiser."""

from __future__ import annotations

import pytest

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

pytestmark = [pytest.mark.integration]  # scipy dependency

try:
    from formulation_workbench.infrastructure.ml.optimiser import (
        ComponentBounds,
        OptimisationRequest,
        PropertyTarget,
        RecipeOptimiser,
    )
except Exception:  # pragma: no cover
    pytest.skip("scipy not available", allow_module_level=True)


def _cite() -> Citation:
    return Citation(
        authors="Flick",
        title="WBPF",
        year=1995,
        publisher="Noyes Publications",
        isbn=Isbn("9780815513773"),
    )


def _recipe(binder_pct: float) -> Recipe:
    water = round(100.0 - binder_pct - 10.0, 2)
    return Recipe(
        id="recipe-opt",
        category="Краски",
        subcategory="Водно-дисперсионные",
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


def _linear_predictor(recipe: Recipe, property_code: str) -> float | None:
    """Stub predictor: gloss = 15 + 1.6 * binder_pct."""
    if property_code != "gloss_60":
        return None
    binder = sum(
        c.mass_percent
        for c in recipe.all_components
        if c.functional_role is ComponentFunction.BINDER
    )
    return 15.0 + 1.6 * binder


class TestRecipeOptimiser:
    def test_optimiser_moves_binder_towards_target_gloss(self) -> None:
        base = _recipe(binder_pct=30.0)  # starting gloss ~63
        optimiser = RecipeOptimiser(predictor=_linear_predictor)
        request = OptimisationRequest(
            base_recipe_id=base.id,
            targets=(PropertyTarget(property_code="gloss_60", target_value=85.0),),
            bounds=(
                ComponentBounds(component_name="Acrylic", min_percent=20.0, max_percent=70.0),
                ComponentBounds(component_name="Water", min_percent=10.0, max_percent=80.0),
                ComponentBounds(component_name="TiO2", min_percent=5.0, max_percent=25.0),
            ),
            max_iterations=40,
            population_size=20,
        )
        result = optimiser.optimise(base, request)
        assert result.base_recipe_id == base.id
        # Predicted gloss should now be close to 85 (linear stub is fully invertible).
        predicted = result.predicted_values.get("gloss_60")
        assert predicted is not None
        assert abs(predicted - 85.0) < 5.0

    def test_missing_model_raises_high_loss(self) -> None:
        base = _recipe(binder_pct=40.0)
        optimiser = RecipeOptimiser(predictor=lambda r, p: None)
        request = OptimisationRequest(
            base_recipe_id=base.id,
            targets=(PropertyTarget(property_code="gloss_60", target_value=50.0),),
            max_iterations=5,
        )
        result = optimiser.optimise(base, request)
        # Loss is at least the penalty value we designed (1e9).
        assert result.final_loss >= 1e9

    def test_minimise_direction_lowers_value(self) -> None:
        base = _recipe(binder_pct=50.0)
        optimiser = RecipeOptimiser(predictor=_linear_predictor)
        request = OptimisationRequest(
            base_recipe_id=base.id,
            targets=(
                PropertyTarget(property_code="gloss_60", target_value=30.0, direction="minimise"),
            ),
            bounds=(ComponentBounds(component_name="Acrylic", min_percent=5.0, max_percent=60.0),),
            max_iterations=20,
        )
        result = optimiser.optimise(base, request)
        predicted = result.predicted_values.get("gloss_60")
        assert predicted is not None
        # Reducing binder lowers the linear-stub gloss → predicted <= starting value.
        assert predicted <= 15.0 + 1.6 * 50.0

    def test_maximise_direction_raises_value(self) -> None:
        base = _recipe(binder_pct=30.0)
        optimiser = RecipeOptimiser(predictor=_linear_predictor)
        request = OptimisationRequest(
            base_recipe_id=base.id,
            targets=(
                PropertyTarget(property_code="gloss_60", target_value=200.0, direction="maximise"),
            ),
            bounds=(ComponentBounds(component_name="Acrylic", min_percent=10.0, max_percent=80.0),),
            max_iterations=20,
        )
        result = optimiser.optimise(base, request)
        predicted = result.predicted_values["gloss_60"]
        assert predicted >= 15.0 + 1.6 * 30.0
