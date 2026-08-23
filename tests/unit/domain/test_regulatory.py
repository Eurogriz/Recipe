"""Tests for the REACH / Annex XVII compliance checker."""

from __future__ import annotations

from formulation_workbench.domain.entities.recipe import (
    Component,
    CompositionStage,
    ProcessParams,
    ProductClass,
    Recipe,
)
from formulation_workbench.domain.services.regulatory import (
    RegulatoryComplianceChecker,
    Severity,
    SubstanceRestriction,
)
from formulation_workbench.domain.value_objects.citation import Citation
from formulation_workbench.domain.value_objects.functions import ComponentFunction
from formulation_workbench.domain.value_objects.isbn import Isbn


def _cite() -> Citation:
    return Citation(
        authors="Flick",
        title="WBPF",
        year=1995,
        publisher="Noyes Publications",
        isbn=Isbn("9780815513773"),
    )


def _recipe_with(components: list[Component]) -> Recipe:
    return Recipe(
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
                components=tuple(components),
                process=ProcessParams(equipment="Disperser"),
            ),
        ),
        primary_source=_cite(),
    )


def _c(
    name: str, cas: str, mass: float, *, role: ComponentFunction = ComponentFunction.SOLVENT
) -> Component:
    return Component(
        name=name,
        cas_number=cas,
        function=role.value,
        mass_percent=mass,
        functional_role=role,
    )


class TestSvhcDetection:
    def test_dehp_flagged(self) -> None:
        recipe = _recipe_with(
            [
                _c("Water", "7732-18-5", 60.0, role=ComponentFunction.VEHICLE),
                _c("DEHP", "117-81-7", 5.0, role=ComponentFunction.PLASTICIZER),
                _c("Acrylic", "mixture", 35.0, role=ComponentFunction.BINDER),
            ]
        )
        findings = RegulatoryComplianceChecker().check(recipe)
        assert any(f.rule_id == "REACH-SVHC" and "DEHP" in f.substance for f in findings)

    def test_mixture_cas_ignored(self) -> None:
        recipe = _recipe_with([_c("Blend", "mixture", 100.0, role=ComponentFunction.BINDER)])
        assert RegulatoryComplianceChecker().check(recipe) == []


class TestAnnexXviiLimits:
    def test_lead_over_limit(self) -> None:
        # Lead limit is 0.03 %; using 0.1 % → error.
        recipe = _recipe_with(
            [
                _c("Water", "7732-18-5", 60.0, role=ComponentFunction.VEHICLE),
                _c("Lead pigment", "7439-92-1", 0.1, role=ComponentFunction.PIGMENT),
                _c("Acrylic", "mixture", 39.9, role=ComponentFunction.BINDER),
            ]
        )
        findings = RegulatoryComplianceChecker().check(recipe)
        errors = [f for f in findings if f.rule_id == "REACH-XVII" and f.severity is Severity.ERROR]
        assert errors, "expected an ERROR for Pb > 0.03 %"

    def test_lead_within_limit_only_warning(self) -> None:
        recipe = _recipe_with(
            [
                _c("Water", "7732-18-5", 60.0, role=ComponentFunction.VEHICLE),
                _c("Lead trace", "7439-92-1", 0.01, role=ComponentFunction.PIGMENT),
                _c("Acrylic", "mixture", 39.99, role=ComponentFunction.BINDER),
            ]
        )
        findings = RegulatoryComplianceChecker().check(recipe)
        # SVHC warning still present but no ERROR from Annex XVII.
        assert not any(f.rule_id == "REACH-XVII" and f.severity is Severity.ERROR for f in findings)
        assert any(f.rule_id == "REACH-SVHC" for f in findings)

    def test_professional_only_downgrades_consumer_restriction(self) -> None:
        recipe = _recipe_with(
            [
                _c("Water", "7732-18-5", 60.0, role=ComponentFunction.VEHICLE),
                _c("Toluene", "108-88-3", 5.0, role=ComponentFunction.SOLVENT),
                _c("Acrylic", "mixture", 35.0, role=ComponentFunction.BINDER),
            ]
        )
        findings = RegulatoryComplianceChecker().check(recipe, consumer_use=False)
        # Consumer-scope restriction is downgraded to INFO for pro-only recipe.
        toluene_infos = [
            f for f in findings if f.rule_id == "REACH-XVII-INFO" and "Toluene" in f.substance
        ]
        assert toluene_infos

    def test_professional_only_still_flagged_by_svhc(self) -> None:
        recipe = _recipe_with(
            [
                _c("Water", "7732-18-5", 60.0, role=ComponentFunction.VEHICLE),
                _c("Toluene", "108-88-3", 5.0, role=ComponentFunction.SOLVENT),
                _c("Acrylic", "mixture", 35.0, role=ComponentFunction.BINDER),
            ]
        )
        findings = RegulatoryComplianceChecker().check(recipe, consumer_use=False)
        assert any(f.rule_id == "REACH-SVHC" and "Toluene" in f.substance for f in findings)


class TestCustomRestrictions:
    def test_injected_restriction_applies(self) -> None:
        custom = (
            SubstanceRestriction(
                cas_number="9999-99-9",
                name="TestBanned",
                max_concentration_percent=None,
                scope="general",
                reference="internal QA policy",
            ),
        )
        checker = RegulatoryComplianceChecker(svhc_list=(), annex_xvii_list=custom)
        recipe = _recipe_with(
            [
                _c("Water", "7732-18-5", 60.0, role=ComponentFunction.VEHICLE),
                _c("TestBanned", "9999-99-9", 1.0, role=ComponentFunction.SOLVENT),
                _c("Acrylic", "mixture", 39.0, role=ComponentFunction.BINDER),
            ]
        )
        findings = checker.check(recipe)
        assert any(f.severity is Severity.ERROR and f.substance == "TestBanned" for f in findings)


class TestAssessmentIntegration:
    def test_regulatory_error_downgrades_maturity(self) -> None:
        from formulation_workbench.domain.services.recipe_assessment import (
            Maturity,
            RecipeAssessmentService,
        )

        # Same clean recipe, but with lead over the limit.
        recipe = _recipe_with(
            [
                _c("Water", "7732-18-5", 59.5, role=ComponentFunction.VEHICLE),
                _c("Lead pigment", "7439-92-1", 0.5, role=ComponentFunction.PIGMENT),
                _c("Acrylic", "mixture", 40.0, role=ComponentFunction.BINDER),
            ]
        )
        assessment = RecipeAssessmentService.assess(recipe)
        assert assessment.has_errors
        assert assessment.maturity in {Maturity.DEFECTIVE, Maturity.DRAFT}
        assert assessment.regulatory_findings  # non-empty
