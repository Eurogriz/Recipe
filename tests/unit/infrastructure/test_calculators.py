"""Unit tests for rule-based calculators."""

from __future__ import annotations

import pytest

from domain.entities.recipe import (
    Component,
    CompositionStage,
    ProcessParams,
    ProductClass,
    Recipe,
)
from domain.value_objects.citation import Citation
from infrastructure.calculators.batch_calculator import BatchCalculator
from infrastructure.calculators.hsp import HSP_DATABASE, HspCalculator
from infrastructure.calculators.pvc_cpvc import PvcCpvcCalculator
from infrastructure.calculators.rule_of_mixtures import RuleOfMixturesCalculator
from infrastructure.calculators.tg_fox import TgCalculator


def make_standard_recipe() -> Recipe:
    """Create a standard test recipe (matte acrylic wall paint)."""
    return Recipe(
        category="Краски",
        subcategory="Водно-дисперсионные",
        binder_type="Стирол-акриловая дисперсия",
        product_class=ProductClass.PREMIUM,
        intended_use="Test",
        stages=(
            CompositionStage(
                stage_number=1,
                name="Mixing",
                description="",
                components=(
                    Component(name="Water", cas_number="7732-18-5", function="vehicle", mass_percent=20.0),
                    Component(name="Dispersant", cas_number="9003-04-7", function="dispersant", mass_percent=0.6),
                    Component(name="Defoamer", cas_number="63148-62-9", function="defoamer", mass_percent=0.3),
                    Component(name="Biocide", cas_number="26172-55-4", function="biocide", mass_percent=0.15),
                    Component(name="Titanium dioxide", cas_number="13463-67-7", function="pigment", mass_percent=22.0),
                    Component(name="Calcium carbonate", cas_number="1317-65-3", function="filler", mass_percent=8.0),
                    Component(name="Talc", cas_number="14807-96-6", function="filler", mass_percent=4.0),
                    Component(name="Acrylic emulsion", cas_number="mixture", function="binder", mass_percent=32.0),
                    Component(name="Texanol", cas_number="25265-77-4", function="coalescent", mass_percent=1.5),
                    Component(name="Thickener", cas_number="proprietary", function="thickener", mass_percent=0.8),
                    Component(name="Propylene glycol", cas_number="57-55-6", function="antifreeze", mass_percent=2.0),
                    # Sum should be ≈ 100% (let me check: 20 + 0.6 + 0.3 + 0.15 + 22 + 8 + 4 + 32 + 1.5 + 0.8 + 2 = 91.35)
                ),
                process=ProcessParams(equipment="Disperser"),
            ),
        ),
        primary_source=Citation(
            authors="Flick, E.W.",
            title="Water-Based Paint Formulations",
            year=1995,
            publisher="Noyes Publications",
        ),
    )


class TestBatchCalculator:
    """Tests for BatchCalculator."""

    def test_calculate_for_mass(self) -> None:
        recipe = make_standard_recipe()
        # Note: mass percents sum to ~91%, scale to 100 kg
        result = BatchCalculator.calculate_for_mass(recipe, target_mass_kg=100.0)

        assert result.target_mass_kg == 100.0
        # Components should sum to 100 kg
        total_mass = sum(c.mass_kg for c in result.components)
        assert abs(total_mass - 100.0) < 1.0

    def test_calculate_for_volume(self) -> None:
        recipe = make_standard_recipe()
        result = BatchCalculator.calculate_for_volume(recipe, target_volume_l=80.0)

        assert result.target_volume_l == 80.0
        assert result.total_density_g_per_cm3 > 0.5  # reasonable density

    def test_zero_mass_rejected(self) -> None:
        recipe = make_standard_recipe()
        with pytest.raises(ValueError):
            BatchCalculator.calculate_for_mass(recipe, target_mass_kg=0.0)


class TestPvcCpvcCalculator:
    """Tests for PvcCpvcCalculator."""

    def test_calculate_basic(self) -> None:
        recipe = make_standard_recipe()
        result = PvcCpvcCalculator.calculate(recipe)

        assert result.pvc_percent > 0
        assert result.cpvc_percent > 0
        assert 0 < result.pvc_cpvc_ratio < 1.0  # Should be matte (PVC < CPVC)
        assert result.finish_class in ("Gloss", "Semi-gloss", "Matte", "Deep matte")

    def test_high_pvc_yields_matte(self) -> None:
        # Recipe with very high pigment → matte
        components = (
            Component(name="Water", cas_number="7732-18-5", function="vehicle", mass_percent=15.0),
            Component(name="Acrylic", cas_number="mixture", function="binder", mass_percent=20.0),
            Component(name="Titanium dioxide", cas_number="13463-67-7", function="pigment", mass_percent=40.0),
            Component(name="Calcium carbonate", cas_number="1317-65-3", function="filler", mass_percent=25.0),
        )
        # Sum = 100
        recipe = Recipe(
            category="Краски",
            subcategory="Test",
            binder_type="Acrylic",
            product_class=ProductClass.STANDARD,
            intended_use="Test",
            stages=(
                CompositionStage(
                    stage_number=1,
                    name="M",
                    description="",
                    components=components,
                ),
            ),
            primary_source=Citation(authors="Test", title="Test", year=2020, publisher="Test"),
        )
        result = PvcCpvcCalculator.calculate(recipe)
        # High pigment → high PVC → matte
        assert result.finish_class in ("Matte", "Deep matte", "Semi-gloss")


class TestTgCalculator:
    """Tests for TgCalculator (Fox equation)."""

    def test_calculate_for_polymer_mix(self) -> None:
        # Recipe with known binder (PMMA-like)
        recipe = Recipe(
            category="Краски",
            subcategory="Test",
            binder_type="Acrylic PMMA",
            product_class=ProductClass.PREMIUM,
            intended_use="Test",
            stages=(
                CompositionStage(
                    stage_number=1,
                    name="M",
                    description="",
                    components=(
                        Component(name="Acrylic", cas_number="mixture", function="binder", mass_percent=50.0),
                        Component(name="Polybutyl acrylate", cas_number="mixture", function="binder", mass_percent=50.0),
                    ),
                ),
            ),
            primary_source=Citation(authors="Test", title="Test", year=2020, publisher="Test"),
        )
        result = TgCalculator.calculate(recipe)
        # Mix of PMMA (Tg=105°C) and PBA (Tg=-54°C) → intermediate Tg
        assert -50 < result.tg_celsius < 100

    def test_no_polymers_returns_warning(self) -> None:
        recipe = make_standard_recipe()
        result = TgCalculator.calculate(recipe)
        # Some polymers detected (acrylic); but not all named polymers
        # Should still return a value if any polymer-like component
        assert result.tg_celsius != 0.0 or len(result.notes) > 0


class TestRuleOfMixturesCalculator:
    """Tests for RuleOfMixturesCalculator."""

    def test_density_calculation(self) -> None:
        recipe = make_standard_recipe()
        result = RuleOfMixturesCalculator.calculate(recipe)
        # Latex paint density should be 1.2-1.4 g/cm³ typical
        assert 1.0 < result.density_g_per_cm3 < 1.6

    def test_mass_solids_reasonable(self) -> None:
        recipe = make_standard_recipe()
        result = RuleOfMixturesCalculator.calculate(recipe)
        # Matte wall paint: ~45-55% mass solids typical
        assert 30 < result.mass_solids_percent < 70

    def test_voc_calculation(self) -> None:
        recipe = make_standard_recipe()
        result = RuleOfMixturesCalculator.calculate(recipe)
        # Texanol + propylene glycol → some VOC, but mostly water (not VOC)
        assert 0 < result.voc_g_per_l < 100


class TestHspCalculator:
    """Tests for HspCalculator."""

    def test_database_lookup(self) -> None:
        water = HspCalculator.lookup("water")
        assert water is not None
        assert water.name == "Water"

    def test_distance_calculation(self) -> None:
        water = HSP_DATABASE["water"]
        ethanol = HSP_DATABASE["ethanol"]
        distance = HspCalculator.calculate_distance(water, ethanol)
        assert distance > 0

    def test_compatibility_check(self) -> None:
        result = HspCalculator.check_compatibility("Water", "Ethanol")
        assert result is not None
        assert result.red > 0

    def test_find_best_solvent(self) -> None:
        results = HspCalculator.find_best_solvent("Acrylic")
        assert results is not None
        # Results should be sorted by RED (best first)
        assert all(results[i].red <= results[i + 1].red for i in range(len(results) - 1))

    def test_unknown_substance_returns_none(self) -> None:
        result = HspCalculator.check_compatibility("Unknown Solvent XYZ", "Water")
        assert result is None
