"""Unit tests for Recipe aggregate root.

Tests domain invariants and business logic.
"""

from __future__ import annotations

import pytest

from formulation_workbench.domain.entities.recipe import (
    Component,
    CompositionStage,
    InvalidRecipeError,
    ProcessParams,
    ProductClass,
    Recipe,
)
from formulation_workbench.domain.value_objects.citation import Citation
from formulation_workbench.domain.value_objects.isbn import Isbn
from formulation_workbench.domain.value_objects.verification_status import (
    VerificationState,
)


def make_valid_citation() -> Citation:
    """Create a valid citation for testing."""
    return Citation(
        authors="Flick, E.W.",
        title="Water-Based Paint Formulations, Vol. 3",
        year=1995,
        publisher="Noyes Publications",
        isbn=Isbn("9780815513773"),
        page_or_formula="pp. 78-82",
    )


def make_valid_components() -> tuple[Component, ...]:
    """Create valid components totaling 100%."""
    return (
        Component(name="Water", cas_number="7732-18-5", function="vehicle", mass_percent=50.0),
        Component(
            name="Acrylic emulsion",
            cas_number="mixture",
            function="binder",
            mass_percent=40.0,
        ),
        Component(
            name="TiO2",
            cas_number="13463-67-7",
            function="pigment",
            mass_percent=10.0,
        ),
    )


def make_valid_stages() -> tuple[CompositionStage, ...]:
    return (
        CompositionStage(
            stage_number=1,
            name="Mixing",
            description="Mix all components",
            components=make_valid_components(),
            process=ProcessParams(
                equipment="Disperser",
                rotational_speed_rpm=1000.0,
                temperature_c=23.0,
                duration_min=30,
            ),
        ),
    )


class TestRecipeInvariants:
    """Tests for domain invariants."""

    def test_valid_recipe_can_be_created(self) -> None:
        recipe = Recipe(
            category="Краски",
            subcategory="Водно-дисперсионные",
            binder_type="Акриловая",
            product_class=ProductClass.PREMIUM,
            intended_use="Interior walls",
            stages=make_valid_stages(),
            primary_source=make_valid_citation(),
        )
        assert recipe.category == "Краски"
        assert recipe.product_class == ProductClass.PREMIUM
        assert len(recipe.stages) == 1
        assert len(recipe.all_components) == 3

    def test_empty_stages_rejected(self) -> None:
        with pytest.raises(InvalidRecipeError, match="at least one composition stage"):
            Recipe(
                category="Краски",
                subcategory="Водно-дисперсионные",
                binder_type="Акриловая",
                intended_use="Test",
                stages=(),
                primary_source=make_valid_citation(),
            )

    def test_missing_primary_source_rejected(self) -> None:
        with pytest.raises(InvalidRecipeError, match="primary source"):
            Recipe(
                category="Краски",
                subcategory="Водно-дисперсионные",
                binder_type="Акриловая",
                intended_use="Test",
                stages=make_valid_stages(),
                primary_source=None,
            )

    def test_empty_category_rejected(self) -> None:
        with pytest.raises(InvalidRecipeError, match="category"):
            Recipe(
                category="",
                subcategory="Водно-дисперсионные",
                binder_type="Акриловая",
                intended_use="Test",
                stages=make_valid_stages(),
                primary_source=make_valid_citation(),
            )

    def test_mass_percents_must_sum_to_100(self) -> None:
        bad_components = (
            Component(name="Water", cas_number="7732-18-5", function="vehicle", mass_percent=50.0),
            Component(name="Other", cas_number="123", function="filler", mass_percent=30.0),
            # Total: 80%, not 100%
        )
        with pytest.raises(InvalidRecipeError, match="sum to 100"):
            Recipe(
                category="Краски",
                subcategory="Водно-дисперсионные",
                binder_type="Акриловая",
                intended_use="Test",
                stages=(
                    CompositionStage(
                        stage_number=1,
                        name="Mixing",
                        description="",
                        components=bad_components,
                    ),
                ),
                primary_source=make_valid_citation(),
            )

    def test_mass_percents_within_tolerance_accepted(self) -> None:
        """±0.5% tolerance allows 99.6% total."""
        components = (
            Component(name="Water", cas_number="7732-18-5", function="vehicle", mass_percent=49.6),
            Component(name="Binder", cas_number="mixture", function="binder", mass_percent=50.0),
            # Total: 99.6%, within 0.5% of 100
        )
        recipe = Recipe(
            category="Краски",
            subcategory="Водно-дисперсионные",
            binder_type="Акриловая",
            intended_use="Test",
            stages=(
                CompositionStage(
                    stage_number=1,
                    name="Mixing",
                    description="",
                    components=components,
                ),
            ),
            primary_source=make_valid_citation(),
        )
        assert recipe is not None

    def test_sequential_stage_numbers_required(self) -> None:
        components = make_valid_components()
        stages = (
            CompositionStage(
                stage_number=1,
                name="Mixing",
                description="",
                components=components,
            ),
            CompositionStage(
                stage_number=3,  # Skip 2
                name="Dilution",
                description="",
                components=components,
            ),
        )
        with pytest.raises(InvalidRecipeError, match="sequential"):
            Recipe(
                category="Краски",
                subcategory="Водно-дисперсионные",
                binder_type="Акриловая",
                intended_use="Test",
                stages=stages,
                primary_source=make_valid_citation(),
            )

    def test_component_without_cas_rejected(self) -> None:
        with pytest.raises(InvalidRecipeError, match="CAS number"):
            Component(name="Mystery", cas_number="", function="filler", mass_percent=1.0)

    def test_component_mass_percent_out_of_range(self) -> None:
        with pytest.raises(InvalidRecipeError, match="mass_percent"):
            Component(name="Bad", cas_number="123-45-6", function="filler", mass_percent=150.0)


class TestRecipeWorkflow:
    """Tests for verification workflow on Recipe."""

    def test_submit_for_review(self) -> None:
        recipe = _make_recipe()
        submitted = recipe.submit_for_review()
        assert submitted.status.state == VerificationState.PENDING_REVIEW
        assert recipe.status.state == VerificationState.DRAFT  # original unchanged

    def test_verify_three_times_reaches_verified(self) -> None:
        recipe = _make_recipe()
        submitted = recipe.submit_for_review()
        v1 = submitted.verify()
        v2 = v1.verify()
        v3 = v2.verify()
        assert v3.status.state == VerificationState.VERIFIED
        assert v3.status.verification_count == 3

    def test_create_new_version(self) -> None:
        recipe = _make_recipe()
        verified = recipe.submit_for_review().verify().verify().verify()
        assert verified.status.is_verified

        new_version = verified.create_new_version()
        assert new_version.version == 2
        assert new_version.previous_version_id == verified.id
        assert new_version.status.state == VerificationState.DRAFT
        assert new_version.id != verified.id


class TestRecipeEquality:
    """Tests for equality semantics."""

    def test_equal_by_id(self) -> None:
        r1 = _make_recipe()
        r2 = _make_recipe(id=r1.id)
        assert r1 == r2

    def test_different_ids_not_equal(self) -> None:
        r1 = _make_recipe()
        r2 = _make_recipe()
        assert r1 != r2


def _make_recipe(id: str | None = None) -> Recipe:
    return Recipe(
        id=id,
        category="Краски",
        subcategory="Водно-дисперсионные",
        binder_type="Акриловая",
        product_class=ProductClass.PREMIUM,
        intended_use="Test interior paint",
        stages=make_valid_stages(),
        primary_source=make_valid_citation(),
        created_by="system",
    )
