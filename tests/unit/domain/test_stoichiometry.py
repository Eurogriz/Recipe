"""Tests for the 2-K stoichiometry engine."""

from __future__ import annotations

import pytest

from formulation_workbench.domain.entities.recipe import (
    Component,
    CompositionStage,
    ProcessParams,
    ProductClass,
    Recipe,
)
from formulation_workbench.domain.services.stoichiometry import (
    ChemicalGroup,
    Severity,
    analyse,
    batch_mix_ratio,
)
from formulation_workbench.domain.value_objects.citation import Citation
from formulation_workbench.domain.value_objects.functions import ComponentFunction
from formulation_workbench.domain.value_objects.isbn import Isbn
from formulation_workbench.domain.value_objects.physical_properties import PhysicalProperties


def _cite() -> Citation:
    return Citation(
        authors="Wicks",
        title="Organic Coatings",
        year=2007,
        publisher="Wiley-VCH",
        isbn=Isbn("9780470391662"),
    )


def _recipe_with(components: list[Component]) -> Recipe:
    return Recipe(
        category="Лаки",
        subcategory="ПУ",
        binder_type="Polyol/HDI",
        product_class=ProductClass.PREMIUM,
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
    name: str,
    role: ComponentFunction,
    mass: float,
    *,
    ew: float | None = None,
    inci: str = "",
    cas: str = "mixture",
) -> Component:
    return Component(
        name=name,
        cas_number=cas,
        function=role.value,
        mass_percent=mass,
        functional_role=role,
        inci_name=inci,
        properties=(PhysicalProperties(equivalent_weight_g_per_eq=ew) if ew else None),
    )


class TestPolyurethane:
    def test_balanced_ratio_gives_info(self) -> None:
        # Balanced 1:1 equivalents: OH-polyol 100 g/eq at 50 %; NCO 100 g/eq at 50 %.
        recipe = _recipe_with(
            [
                _c("Solvent", ComponentFunction.SOLVENT, 30.0),
                _c("Polyol (OH)", ComponentFunction.BINDER, 20.0, ew=100.0),
                _c(
                    "HDI trimer (NCO)",
                    ComponentFunction.HARDENER,
                    20.0,
                    ew=100.0,
                    inci="polyisocyanate HDI",
                ),
                _c("Extender", ComponentFunction.EXTENDER, 30.0),
            ]
        )
        report = analyse(recipe)
        assert report.detected_system == "polyurethane"
        assert report.ratio_reactive_to_co == pytest.approx(1.0, rel=1e-6)
        assert report.is_balanced
        assert any(f.rule_id == "S0" for f in report.findings)

    def test_under_dosed_hardener_warns(self) -> None:
        recipe = _recipe_with(
            [
                _c("Polyol", ComponentFunction.BINDER, 50.0, ew=100.0),
                _c("HDI trimer", ComponentFunction.HARDENER, 5.0, ew=100.0, inci="polyisocyanate"),
                _c("Solvent", ComponentFunction.SOLVENT, 45.0),
            ]
        )
        report = analyse(recipe)
        assert report.ratio_reactive_to_co is not None
        assert report.ratio_reactive_to_co < 0.95
        assert any(f.rule_id == "S3" and f.severity is Severity.WARNING for f in report.findings)

    def test_over_dosed_hardener_warns(self) -> None:
        recipe = _recipe_with(
            [
                _c("Polyol", ComponentFunction.BINDER, 20.0, ew=100.0),
                _c("HDI trimer", ComponentFunction.HARDENER, 40.0, ew=100.0, inci="polyisocyanate"),
                _c("Solvent", ComponentFunction.SOLVENT, 40.0),
            ]
        )
        report = analyse(recipe)
        assert report.ratio_reactive_to_co is not None
        assert report.ratio_reactive_to_co > 1.10
        assert any(f.rule_id == "S4" and f.severity is Severity.WARNING for f in report.findings)


class TestEpoxyAmine:
    def test_epoxy_amine_matching(self) -> None:
        recipe = _recipe_with(
            [
                _c(
                    "Bisphenol A epoxy",
                    ComponentFunction.BINDER,
                    60.0,
                    ew=190.0,
                    inci="epoxy resin BPA",
                ),
                _c(
                    "Amine adduct",
                    ComponentFunction.HARDENER,
                    30.0,
                    ew=95.0,
                    inci="polyamide amine adduct",
                ),
                _c("Solvent", ComponentFunction.SOLVENT, 10.0),
            ]
        )
        report = analyse(recipe)
        assert report.detected_system == "epoxy_amine"
        assert report.reactive_pair is not None
        assert report.reactive_pair.reactive_group is ChemicalGroup.AMINE_HYDROGEN
        # Not balanced (30/95=0.315 amine H eq vs 60/190=0.316 epoxide eq) → ~0.998
        assert report.is_balanced


class TestNoReactivePair:
    def test_single_component_returns_none_pair(self) -> None:
        recipe = _recipe_with(
            [
                _c("Water", ComponentFunction.VEHICLE, 60.0, cas="7732-18-5"),
                _c("Acrylic emulsion", ComponentFunction.BINDER, 40.0),
            ]
        )
        report = analyse(recipe)
        assert report.reactive_pair is None
        assert report.ratio_reactive_to_co is None
        # No S2/S3/S4 findings expected.
        assert all(f.rule_id != "S2" for f in report.findings)

    def test_hardener_without_binder_group_warns(self) -> None:
        recipe = _recipe_with(
            [
                _c("Water", ComponentFunction.VEHICLE, 60.0, cas="7732-18-5"),
                _c("Acrylic emulsion", ComponentFunction.BINDER, 30.0),
                _c("Amine adduct", ComponentFunction.HARDENER, 10.0, ew=95.0, inci="amine"),
            ]
        )
        report = analyse(recipe)
        assert any(f.rule_id == "S1" and f.severity is Severity.WARNING for f in report.findings)


class TestBatchMixRatio:
    def test_pu_1to1_mass_ratio(self) -> None:
        recipe = _recipe_with(
            [
                _c("Solvent", ComponentFunction.SOLVENT, 30.0),
                _c("Polyol", ComponentFunction.BINDER, 35.0, ew=100.0),
                _c("HDI trimer", ComponentFunction.HARDENER, 35.0, ew=100.0, inci="polyisocyanate"),
            ]
        )
        report = analyse(recipe)
        ratio = batch_mix_ratio(report)
        assert ratio == (100.0, 100.0)


class TestAssessmentIntegration:
    def test_off_ratio_pu_downgrades_score(self) -> None:
        from formulation_workbench.domain.services.recipe_assessment import (
            RecipeAssessmentService,
        )

        recipe = _recipe_with(
            [
                _c("Polyol", ComponentFunction.BINDER, 60.0, ew=100.0),
                _c("HDI trimer", ComponentFunction.HARDENER, 5.0, ew=100.0, inci="polyisocyanate"),
                _c("Solvent", ComponentFunction.SOLVENT, 35.0),
            ]
        )
        assessment = RecipeAssessmentService.assess(recipe)
        # Stoichiometry warning must appear in the summary counts.
        assert assessment.stoichiometry is not None
        assert not assessment.stoichiometry.is_balanced
        assert assessment.summary()["stoichiometry_balanced"] is False
