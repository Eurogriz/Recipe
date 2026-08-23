"""Unit tests for ClassRanker domain service."""

from __future__ import annotations

import pytest

from formulation_workbench.domain.entities.recipe import (
    Component,
    CompositionStage,
    ProcessParams,
    ProductClass,
    Recipe,
)
from formulation_workbench.domain.services.class_ranker import ClassFactor, ClassRanker
from formulation_workbench.domain.value_objects.citation import Citation


def make_recipe(
    binder_type: str = "Acrylic polyurethane",
    components: tuple[Component, ...] | None = None,
) -> Recipe:
    if components is None:
        components = (
            Component(name="Water", cas_number="7732-18-5", function="vehicle", mass_percent=30.0),
            Component(
                name="Acrylic emulsion", cas_number="mixture", function="binder", mass_percent=40.0
            ),
            Component(
                name="TiO2 rutile",
                cas_number="13463-67-7",
                function="pigment",
                mass_percent=20.0,
                notes="rutile grade",
            ),
            Component(
                name="HALS stabilizer",
                cas_number="proprietary",
                function="UV stabilizer",
                mass_percent=2.0,
                notes="hals",
            ),
            Component(
                name="Defoamer", cas_number="63148-62-9", function="defoamer", mass_percent=0.5
            ),
            Component(
                name="Coalescent", cas_number="25265-77-4", function="coalescent", mass_percent=2.0
            ),
            Component(
                name="Biocide", cas_number="26172-55-4", function="biocide", mass_percent=0.5
            ),
            Component(
                name="Thickener", cas_number="proprietary", function="thickener", mass_percent=1.0
            ),
            Component(name="Glycol", cas_number="57-55-6", function="antifreeze", mass_percent=4.0),
        )

    return Recipe(
        category="Краски",
        subcategory="Водно-дисперсионные",
        binder_type=binder_type,
        product_class=ProductClass.PREMIUM,
        intended_use="Test",
        stages=(
            CompositionStage(
                stage_number=1,
                name="Mixing",
                description="",
                components=components,
                process=ProcessParams(equipment="Disperser"),
            ),
        ),
        primary_source=Citation(
            authors="Flick, E.W.",
            title="Water-Based Paint Formulations, Vol. 3",
            year=1995,
            publisher="Noyes Publications",
        ),
    )


class TestClassRanker:
    """Tests for class ranking algorithm."""

    def test_premium_binder_scores_high(self) -> None:
        """Recipe with acrylic polyurethane binder scores high on binder quality."""
        recipe = make_recipe(binder_type="Acrylic polyurethane")
        ranking = ClassRanker.rank(recipe)
        binder_score = ranking.factor_scores[ClassFactor.BINDER_QUALITY]
        assert binder_score >= 0.7

    def test_economy_binder_scores_low(self) -> None:
        """Recipe with PVA binder scores low on binder quality."""
        recipe = make_recipe(binder_type="PVA emulsion")
        ranking = ClassRanker.rank(recipe)
        binder_score = ranking.factor_scores[ClassFactor.BINDER_QUALITY]
        assert binder_score <= 0.4

    def test_no_tio2_scores_zero_on_pigment(self) -> None:
        """Recipe without TiO2 scores 0 on pigment quality."""
        components_no_tio2 = (
            Component(name="Water", cas_number="7732-18-5", function="vehicle", mass_percent=70.0),
            Component(name="Binder", cas_number="mixture", function="binder", mass_percent=30.0),
        )
        recipe = make_recipe(components=components_no_tio2)
        ranking = ClassRanker.rank(recipe)
        pigment_score = ranking.factor_scores[ClassFactor.PIGMENT_QUALITY]
        assert pigment_score == 0.0

    def test_high_tio2_with_rutile_scores_high(self) -> None:
        """Recipe with high TiO2 and rutile scoring high on pigment quality."""
        components = (
            Component(name="Water", cas_number="7732-18-5", function="vehicle", mass_percent=30.0),
            Component(name="Binder", cas_number="mixture", function="binder", mass_percent=40.0),
            Component(
                name="TiO2 rutile R-902",
                cas_number="13463-67-7",
                function="pigment",
                mass_percent=30.0,
                notes="rutile premium grade",
            ),
        )
        recipe = make_recipe(components=components)
        ranking = ClassRanker.rank(recipe)
        pigment_score = ranking.factor_scores[ClassFactor.PIGMENT_QUALITY]
        assert pigment_score >= 0.7

    def test_premium_additives_boost_score(self) -> None:
        """Recipe with HALS, UV-absorber additives scores higher."""
        recipe = make_recipe()
        ranking = ClassRanker.rank(recipe)
        additives_score = ranking.factor_scores[ClassFactor.FUNCTIONAL_ADDITIVES]
        assert additives_score > 0.0

    def test_recommendation_class_is_valid_enum(self) -> None:
        """Recommendation must be a valid ProductClass."""
        recipe = make_recipe()
        ranking = ClassRanker.rank(recipe)
        assert isinstance(ranking.recommended_class, ProductClass)

    def test_confidence_in_valid_range(self) -> None:
        """Confidence must be in [0, 1]."""
        recipe = make_recipe()
        ranking = ClassRanker.rank(recipe)
        assert 0.0 <= ranking.confidence <= 1.0

    def test_cost_index_when_provided(self) -> None:
        """Cost index is included when provided."""
        recipe = make_recipe()
        ranking = ClassRanker.rank(recipe, cost_index=0.8)
        assert ranking.factor_scores[ClassFactor.COST_INDEX] == 0.8

    def test_invalid_weights_rejected(self) -> None:
        """Negative weights are rejected."""
        recipe = make_recipe()
        with pytest.raises(Exception):  # noqa: B017 - ranker may raise ValueError or AssertionError
            ClassRanker.rank(
                recipe,
                weights={
                    ClassFactor.BINDER_QUALITY: -0.5,
                    ClassFactor.PIGMENT_QUALITY: 0.5,
                    ClassFactor.FUNCTIONAL_ADDITIVES: 0.5,
                    ClassFactor.PREDICTED_PROPERTIES: 0.5,
                    ClassFactor.COST_INDEX: 0.5,
                },
            )
