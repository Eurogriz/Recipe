"""Tests for the Price value object and cost calculator."""

from __future__ import annotations

import pytest

from formulation_workbench.domain.entities.recipe import (
    Component,
    CompositionStage,
    ProcessParams,
    ProductClass,
    Recipe,
)
from formulation_workbench.domain.services.cost_calculator import RecipeCostCalculator
from formulation_workbench.domain.value_objects.citation import Citation
from formulation_workbench.domain.value_objects.cost import InvalidPriceError, Price
from formulation_workbench.domain.value_objects.functions import ComponentFunction
from formulation_workbench.domain.value_objects.isbn import Isbn
from formulation_workbench.domain.value_objects.physical_properties import PhysicalProperties


def _cite() -> Citation:
    return Citation(
        authors="Flick",
        title="WBPF",
        year=1995,
        publisher="Noyes Publications",
        isbn=Isbn("9780815513773"),
    )


class TestPrice:
    def test_valid_price(self) -> None:
        p = Price(amount=1.50, currency="EUR", unit="kg")
        assert p.per_kg() == pytest.approx(1.50)

    def test_negative_amount_rejected(self) -> None:
        with pytest.raises(InvalidPriceError):
            Price(amount=-0.1, currency="EUR")

    def test_bad_currency_rejected(self) -> None:
        with pytest.raises(InvalidPriceError):
            Price(amount=1.0, currency="EURO")

    def test_unknown_unit_rejected(self) -> None:
        with pytest.raises(InvalidPriceError):
            Price(amount=1.0, currency="EUR", unit="barrel")

    def test_grams_convert(self) -> None:
        assert Price(2.0, "EUR", "g").per_kg() == pytest.approx(2000.0)

    def test_tonnes_convert(self) -> None:
        assert Price(1000.0, "EUR", "t").per_kg() == pytest.approx(1.0)

    def test_litre_needs_density(self) -> None:
        p = Price(2.0, "EUR", "l")
        with pytest.raises(InvalidPriceError):
            p.per_kg()
        assert p.per_kg(density_g_per_cm3=0.8) == pytest.approx(2.5)


class TestRecipeCostCalculator:
    def _recipe(self, water_mass: float = 60.0, binder_mass: float = 40.0) -> Recipe:
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
                    components=(
                        Component(
                            name="Water",
                            cas_number="7732-18-5",
                            function="vehicle",
                            mass_percent=water_mass,
                            functional_role=ComponentFunction.VEHICLE,
                            properties=PhysicalProperties(density_g_per_cm3=1.00),
                        ),
                        Component(
                            name="Acrylic",
                            cas_number="mixture",
                            function="binder",
                            mass_percent=binder_mass,
                            functional_role=ComponentFunction.BINDER,
                            properties=PhysicalProperties(density_g_per_cm3=1.05),
                        ),
                    ),
                    process=ProcessParams(equipment="Disperser"),
                ),
            ),
            primary_source=_cite(),
        )

    def test_simple_cost(self) -> None:
        cost = RecipeCostCalculator.calculate(
            self._recipe(),
            prices={
                "Water": Price(0.001, "EUR", "kg"),
                "Acrylic": Price(3.00, "EUR", "kg"),
            },
        )
        # 0.6 * 0.001 + 0.4 * 3.00 = 1.2006 EUR/kg
        assert cost.total_cost_per_kg == pytest.approx(1.2006, rel=1e-6)
        assert cost.priced_fraction == pytest.approx(1.0)
        assert not cost.missing_prices

    def test_missing_price_still_computes_priced_fraction(self) -> None:
        cost = RecipeCostCalculator.calculate(
            self._recipe(water_mass=30.0, binder_mass=70.0),
            prices={"Acrylic": Price(3.00, "EUR", "kg")},
        )
        assert "Water" in cost.missing_prices
        assert cost.priced_fraction == pytest.approx(0.7)
        assert cost.total_cost_per_kg == pytest.approx(2.10, rel=1e-6)

    def test_currency_mismatch_treated_as_missing(self) -> None:
        cost = RecipeCostCalculator.calculate(
            self._recipe(),
            prices={
                "Water": Price(0.001, "EUR", "kg"),
                "Acrylic": Price(3.30, "USD", "kg"),
            },
        )
        assert "Acrylic" in cost.missing_prices
        assert cost.currency == "EUR"

    def test_volumetric_price_uses_density(self) -> None:
        cost = RecipeCostCalculator.calculate(
            self._recipe(water_mass=0.0, binder_mass=100.0),
            prices={"Acrylic": Price(3.15, "EUR", "l")},  # 3.15 EUR/L, density 1.05 → 3.0/kg
        )
        assert cost.total_cost_per_kg == pytest.approx(3.0, rel=1e-6)

    def test_summary_contains_key_fields(self) -> None:
        cost = RecipeCostCalculator.calculate(
            self._recipe(),
            prices={"Water": Price(0.001, "EUR", "kg"), "Acrylic": Price(3.00, "EUR", "kg")},
        )
        summary = cost.summary()
        assert summary["currency"] == "EUR"
        assert summary["missing_prices"] == 0
        assert summary["cost_per_kg"] > 0
