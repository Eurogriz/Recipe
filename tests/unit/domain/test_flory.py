"""Tests for the Flory-Stockmayer network analysis."""

from __future__ import annotations

import math

import pytest

from formulation_workbench.domain.entities.recipe import (
    Component,
    CompositionStage,
    ProcessParams,
    ProductClass,
    Recipe,
)
from formulation_workbench.domain.services.flory import (
    amine_h_breakdown,
    analyse_flory,
)
from formulation_workbench.domain.services.stoichiometry import analyse
from formulation_workbench.domain.value_objects.citation import Citation
from formulation_workbench.domain.value_objects.functions import ComponentFunction
from formulation_workbench.domain.value_objects.isbn import Isbn
from formulation_workbench.domain.value_objects.physical_properties import PhysicalProperties


def _cite() -> Citation:
    return Citation(
        authors="Flory",
        title="Principles of Polymer Chemistry",
        year=1953,
        publisher="Wiley",
        isbn=Isbn("9780801401343"),
    )


def _recipe(components: list[Component]) -> Recipe:
    return Recipe(
        category="Лаки",
        subcategory="Эпоксидные",
        binder_type="Epoxy/amine",
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


def _c(name, role, mass, *, props=None, inci="", cas="mixture"):  # type: ignore[no-untyped-def]
    return Component(
        name=name,
        cas_number=cas,
        function=role.value,
        mass_percent=mass,
        functional_role=role,
        inci_name=inci,
        properties=props,
    )


class TestAmineBreakdown:
    def test_primary_only_matches_raw(self) -> None:
        # 100 g of a hardener with 100 g/eq amine H; 100 % pure component.
        component = _c(
            "Amine A",
            ComponentFunction.HARDENER,
            100.0,
            inci="polyamide amine",
            props=PhysicalProperties(
                equivalent_weight_g_per_eq=100.0,
                primary_amine_h_count=2,
                secondary_amine_h_count=0,
            ),
        )
        breakdown = amine_h_breakdown(component)
        assert breakdown is not None
        assert breakdown.effective_ah_equivalents_per_100g == pytest.approx(1.0)
        assert breakdown.raw_ah_equivalents_per_100g == pytest.approx(1.0)

    def test_secondary_only_uses_reactivity_factor(self) -> None:
        component = _c(
            "Amine B",
            ComponentFunction.HARDENER,
            100.0,
            inci="secondary amine adduct",
            props=PhysicalProperties(
                equivalent_weight_g_per_eq=100.0,
                primary_amine_h_count=0,
                secondary_amine_h_count=2,
            ),
        )
        breakdown = amine_h_breakdown(component)
        assert breakdown is not None
        # Default secondary reactivity = 0.5, so effective = 0.5 × raw.
        assert breakdown.effective_ah_equivalents_per_100g == pytest.approx(0.5)

    def test_mixed_primary_and_secondary(self) -> None:
        component = _c(
            "Amine C",
            ComponentFunction.HARDENER,
            100.0,
            inci="amine",
            props=PhysicalProperties(
                equivalent_weight_g_per_eq=100.0,
                primary_amine_h_count=2,
                secondary_amine_h_count=2,
            ),
        )
        breakdown = amine_h_breakdown(component)
        assert breakdown is not None
        # 50 % primary (×1) + 50 % secondary (×0.5) = 0.75.
        assert breakdown.effective_ah_equivalents_per_100g == pytest.approx(0.75)

    def test_without_metadata_returns_none(self) -> None:
        component = _c(
            "Amine D",
            ComponentFunction.HARDENER,
            50.0,
            inci="amine",
            props=PhysicalProperties(equivalent_weight_g_per_eq=100.0),
        )
        assert amine_h_breakdown(component) is None

    def test_missing_ew_returns_none(self) -> None:
        component = _c(
            "Amine E",
            ComponentFunction.HARDENER,
            50.0,
            inci="amine",
            props=PhysicalProperties(
                primary_amine_h_count=2,
                secondary_amine_h_count=0,
            ),
        )
        assert amine_h_breakdown(component) is None


class TestFloryAnalysis:
    def test_perfect_stoichiometry(self) -> None:
        # Classic epoxy DGEBA (f=2) + polyamine (f=3), balanced eq.
        result = analyse_flory(
            equivalents_a=1.0,
            equivalents_b=1.0,
            functionality_a=2.0,
            functionality_b=3.0,
        )
        assert result.equivalents_ratio_r == 1.0
        assert result.can_form_network  # (2-1)(3-1) = 2 > 1
        # p_c = 1 / sqrt(1 × 1 × 2) ≈ 0.707
        assert result.gel_point_conversion == pytest.approx(1 / math.sqrt(2), rel=1e-6)

    def test_linear_system_flags_no_gel(self) -> None:
        # Two difunctional monomers — no branching, no gel.
        result = analyse_flory(
            equivalents_a=1.0,
            equivalents_b=1.0,
            functionality_a=2.0,
            functionality_b=2.0,
        )
        assert not result.can_form_network
        assert result.gel_point_conversion is None
        assert any("linear" in n.lower() for n in result.notes)

    def test_missing_functionality_returns_partial_report(self) -> None:
        result = analyse_flory(
            equivalents_a=1.0,
            equivalents_b=1.0,
            functionality_a=None,
            functionality_b=3.0,
        )
        assert result.gel_point_conversion is None
        assert result.can_form_network is False
        assert any("Functionality unknown" in n for n in result.notes)

    def test_off_ratio_bounds_max_conversion(self) -> None:
        # r = 0.5 → majority side can only reach 50 % conversion.
        result = analyse_flory(
            equivalents_a=2.0,
            equivalents_b=1.0,
            functionality_a=3.0,
            functionality_b=2.0,
        )
        assert result.equivalents_ratio_r == 0.5
        assert result.max_conversion_minority == 1.0
        assert result.max_conversion_majority == 0.5

    def test_zero_side_short_circuits(self) -> None:
        result = analyse_flory(
            equivalents_a=0.0,
            equivalents_b=1.0,
            functionality_a=2.0,
            functionality_b=3.0,
        )
        assert result.equivalents_ratio_r is None
        assert not result.can_form_network


class TestStoichiometryFloryIntegration:
    def test_report_populates_flory_when_functionalities_present(self) -> None:
        # Epoxy–amine system, both sides carry functionality.
        recipe = _recipe(
            [
                _c(
                    "Epoxy DGEBA",
                    ComponentFunction.BINDER,
                    60.0,
                    inci="epoxy resin BPA",
                    props=PhysicalProperties(equivalent_weight_g_per_eq=190.0, functionality=2.0),
                ),
                _c(
                    "Polyamine",
                    ComponentFunction.HARDENER,
                    30.0,
                    inci="polyamide amine",
                    props=PhysicalProperties(
                        equivalent_weight_g_per_eq=95.0,
                        functionality=3.0,
                        primary_amine_h_count=2,
                        secondary_amine_h_count=2,
                    ),
                ),
                _c("Solvent", ComponentFunction.SOLVENT, 10.0),
            ]
        )
        report = analyse(recipe)
        assert report.flory is not None
        assert report.flory.functionality_a == pytest.approx(2.0)
        assert report.flory.functionality_b == pytest.approx(3.0)
        assert report.flory.can_form_network
        assert report.amine_breakdown  # non-empty — primary+secondary counts present

    def test_amine_breakdown_shifts_reactive_equivalents(self) -> None:
        """Effective AHEW reduces reactive_eq when secondary amines dominate."""
        # Pure secondary — default reactivity 0.5, so eff = 0.5 × raw.
        recipe_secondary = _recipe(
            [
                _c(
                    "Epoxy",
                    ComponentFunction.BINDER,
                    50.0,
                    inci="epoxy",
                    props=PhysicalProperties(equivalent_weight_g_per_eq=190.0, functionality=2.0),
                ),
                _c(
                    "Secondary amine",
                    ComponentFunction.HARDENER,
                    50.0,
                    inci="secondary amine",
                    props=PhysicalProperties(
                        equivalent_weight_g_per_eq=95.0,
                        functionality=3.0,
                        primary_amine_h_count=0,
                        secondary_amine_h_count=2,
                    ),
                ),
            ]
        )
        report = analyse(recipe_secondary)
        # Raw AHEW would give 50 / 95 = 0.526 eq/100g; effective ≈ 0.263.
        assert report.reactive_equivalents == pytest.approx(0.263, rel=1e-2)
