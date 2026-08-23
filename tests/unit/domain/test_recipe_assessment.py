"""Tests for the aggregated RecipeAssessment service."""

from __future__ import annotations

from formulation_workbench.domain.entities.recipe import (
    Component,
    CompositionStage,
    ProcessParams,
    ProductClass,
    Recipe,
)
from formulation_workbench.domain.services.recipe_assessment import (
    Maturity,
    RecipeAssessmentService,
)
from formulation_workbench.domain.services.technological_rules import Severity
from formulation_workbench.domain.value_objects.citation import Citation
from formulation_workbench.domain.value_objects.functions import ComponentFunction
from formulation_workbench.domain.value_objects.isbn import Isbn
from formulation_workbench.domain.value_objects.target_properties import (
    TargetSpecification,
    ToleranceMode,
)


def _cite() -> Citation:
    return Citation(
        authors="Flick",
        title="WBPF",
        year=1995,
        publisher="Noyes Publications",
        isbn=Isbn("9780815513773"),
    )


def _c(name: str, role: ComponentFunction, mass: float, *, cas: str = "mixture") -> Component:
    return Component(
        name=name,
        cas_number=cas,
        function=role.value,
        mass_percent=mass,
        functional_role=role,
    )


def _healthy_recipe() -> Recipe:
    """A clean, textbook water-based interior white paint."""
    return Recipe(
        category="Краски",
        subcategory="Водно-дисперсионные",
        binder_type="Стирол-акриловая дисперсия",
        product_class=ProductClass.PREMIUM,
        intended_use="Interior wall paint",
        stages=(
            CompositionStage(
                stage_number=1,
                name="Mix",
                description="",
                components=(
                    _c("Water", ComponentFunction.VEHICLE, 33.5, cas="7732-18-5"),
                    _c("Dispex", ComponentFunction.DISPERSANT, 0.6),
                    _c("Foamex", ComponentFunction.DEFOAMER, 0.3),
                    _c("Kathon", ComponentFunction.IN_CAN_BIOCIDE, 0.15),
                    _c("TiO2", ComponentFunction.PIGMENT, 22.0, cas="13463-67-7"),
                    _c("CaCO3", ComponentFunction.EXTENDER, 8.0, cas="1317-65-3"),
                    _c("Talc", ComponentFunction.EXTENDER, 4.0, cas="14807-96-6"),
                    _c("Acrylic", ComponentFunction.BINDER, 27.85),
                    _c("Texanol", ComponentFunction.COALESCENT, 1.5, cas="25265-77-4"),
                    _c("Rheo", ComponentFunction.RHEOLOGY_MODIFIER, 0.8),
                    _c("PG", ComponentFunction.ANTIFREEZE, 1.3, cas="57-55-6"),
                ),
                process=ProcessParams(equipment="Disperser"),
            ),
        ),
        primary_source=_cite(),
        target_properties=(
            TargetSpecification(
                property_code="voc_content", target_value=15.0, tolerance_mode=ToleranceMode.MAX
            ),
            TargetSpecification(property_code="ph", target_value=8.5, tolerance=1.0),
            TargetSpecification(property_code="gloss_60", target_value=3.0, tolerance=2.0),
        ),
    )


def _broken_recipe() -> Recipe:
    """Deliberately broken: no binder, defoamer overdose, VOC over the ceiling."""
    return Recipe(
        category="Краски",
        subcategory="Водно-дисперсионные",
        binder_type="???",
        product_class=ProductClass.PREMIUM,
        intended_use="Broken test",
        stages=(
            CompositionStage(
                stage_number=1,
                name="Mix",
                description="",
                components=(
                    _c("Water", ComponentFunction.VEHICLE, 45.0, cas="7732-18-5"),
                    _c("TiO2", ComponentFunction.PIGMENT, 45.0, cas="13463-67-7"),
                    _c("Foamex", ComponentFunction.DEFOAMER, 10.0),
                ),
                process=ProcessParams(equipment="Disperser"),
            ),
        ),
        primary_source=_cite(),
        target_properties=(
            TargetSpecification(
                property_code="voc_content",
                target_value=250.0,
                tolerance_mode=ToleranceMode.MAX,
            ),
        ),
    )


class TestHealthyRecipe:
    def test_score_and_maturity(self) -> None:
        assessment = RecipeAssessmentService.assess(_healthy_recipe())
        assert assessment.score >= 80
        assert assessment.maturity in {Maturity.PRODUCTION_READY, Maturity.REFERENCE}
        assert not assessment.has_errors

    def test_summary_reports_zero_errors(self) -> None:
        summary = RecipeAssessmentService.assess(_healthy_recipe()).summary()
        assert summary["errors"] == 0


class TestBrokenRecipe:
    def test_defective_labelled_correctly(self) -> None:
        assessment = RecipeAssessmentService.assess(_broken_recipe())
        assert assessment.has_errors
        # An error in T1 (no binder) + T7 (VOC over ceiling) + T13 (only
        # pigment+vehicle) is enough to cap maturity at DRAFT even if
        # score arithmetic remains above zero.
        assert assessment.maturity in {Maturity.DEFECTIVE, Maturity.DRAFT}

    def test_findings_include_error_severities(self) -> None:
        findings = RecipeAssessmentService.assess(_broken_recipe()).findings
        severities = {f.severity for f in findings}
        assert Severity.ERROR in severities

    def test_score_is_bounded(self) -> None:
        assessment = RecipeAssessmentService.assess(_broken_recipe())
        assert 0.0 <= assessment.score <= 100.0
