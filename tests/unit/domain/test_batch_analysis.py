"""Tests for the batch-level analysis service."""

from __future__ import annotations

import pytest

from formulation_workbench.domain.entities.experiment import BatchInfo
from formulation_workbench.domain.entities.recipe import (
    Component,
    CompositionStage,
    ProcessParams,
    ProductClass,
    Recipe,
)
from formulation_workbench.domain.services.batch_analysis import (
    analyse_batch,
    analyse_batch_cost,
    analyse_batch_mass_balance,
    analyse_batch_regulatory,
)
from formulation_workbench.domain.value_objects.citation import Citation
from formulation_workbench.domain.value_objects.cost import Price
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


def _recipe(components: list[Component]) -> Recipe:
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


def _c(name, role, mass, *, cas="mixture"):  # type: ignore[no-untyped-def]
    return Component(
        name=name,
        cas_number=cas,
        function=role.value,
        mass_percent=mass,
        functional_role=role,
    )


class TestBatchCost:
    def test_batch_cost_scales_with_size(self) -> None:
        recipe = _recipe(
            [
                _c("Water", ComponentFunction.VEHICLE, 40.0, cas="7732-18-5"),
                _c("Acrylic", ComponentFunction.BINDER, 40.0),
                _c("TiO2", ComponentFunction.PIGMENT, 20.0, cas="13463-67-7"),
            ]
        )
        batch = BatchInfo(
            batch_number="B-2026-001",
            target_mass_kg=100.0,
            actual_mass_kg=99.5,
            lot_numbers={"Water": "L-W-42", "Acrylic": "L-A-77", "TiO2": "L-T-11"},
        )
        prices = {
            "Water": Price(0.001, "EUR", "kg"),
            "Acrylic": Price(3.00, "EUR", "kg"),
            "TiO2": Price(4.50, "EUR", "kg"),
        }
        breakdown = analyse_batch_cost(recipe, batch, prices)
        # per-kg cost = 0.4*0.001 + 0.4*3.0 + 0.2*4.5 = 2.1004
        # actual batch mass 99.5 kg → 208.99 EUR
        assert breakdown.total_cost == pytest.approx(2.1004 * 99.5, rel=1e-4)
        assert breakdown.currency == "EUR"
        assert not breakdown.missing_prices
        # Lot numbers propagate to each line.
        water_line = next(ln for ln in breakdown.lines if ln.component_name == "Water")
        assert water_line.lot_number == "L-W-42"

    def test_missing_price_reported_but_batch_cost_still_priced_fraction(self) -> None:
        recipe = _recipe(
            [
                _c("Water", ComponentFunction.VEHICLE, 40.0, cas="7732-18-5"),
                _c("Acrylic", ComponentFunction.BINDER, 60.0),
            ]
        )
        batch = BatchInfo(batch_number="B-1", target_mass_kg=10.0, actual_mass_kg=10.0)
        prices = {"Acrylic": Price(3.00, "EUR", "kg")}
        breakdown = analyse_batch_cost(recipe, batch, prices)
        assert "Water" in breakdown.missing_prices
        assert breakdown.priced_fraction == pytest.approx(0.6, rel=1e-4)
        assert breakdown.total_cost == pytest.approx(0.6 * 3.0 * 10.0)


class TestMassBalance:
    def test_yield_within_tolerance(self) -> None:
        mb = analyse_batch_mass_balance(
            BatchInfo(batch_number="B-1", target_mass_kg=100.0, actual_mass_kg=99.0)
        )
        assert mb.yield_percent == pytest.approx(99.0)
        assert mb.is_within_tolerance

    def test_yield_outside_tolerance(self) -> None:
        mb = analyse_batch_mass_balance(
            BatchInfo(batch_number="B-2", target_mass_kg=100.0, actual_mass_kg=95.0)
        )
        assert mb.yield_percent == pytest.approx(95.0)
        assert not mb.is_within_tolerance

    def test_missing_actual_returns_none(self) -> None:
        mb = analyse_batch_mass_balance(BatchInfo(batch_number="B-3", target_mass_kg=100.0))
        assert mb.yield_percent is None
        assert not mb.is_within_tolerance


class TestBatchRegulatory:
    def test_lead_over_limit_batch_flagged(self) -> None:
        recipe = _recipe(
            [
                _c("Water", ComponentFunction.VEHICLE, 59.9, cas="7732-18-5"),
                _c("Lead pigment", ComponentFunction.PIGMENT, 0.1, cas="7439-92-1"),
                _c("Acrylic", ComponentFunction.BINDER, 40.0),
            ]
        )
        batch = BatchInfo(
            batch_number="B-Pb",
            target_mass_kg=50.0,
            actual_mass_kg=50.0,
            lot_numbers={"Lead pigment": "PB-2024-01"},
        )
        report = analyse_batch_regulatory(recipe, batch)
        assert report.batch_number == "B-Pb"
        assert report.has_error


class TestBundle:
    def test_analyse_batch_returns_three_reports(self) -> None:
        recipe = _recipe(
            [
                _c("Water", ComponentFunction.VEHICLE, 60.0, cas="7732-18-5"),
                _c("Acrylic", ComponentFunction.BINDER, 40.0),
            ]
        )
        batch = BatchInfo(batch_number="B-9", target_mass_kg=10.0, actual_mass_kg=10.1)
        prices = {
            "Water": Price(0.001, "EUR", "kg"),
            "Acrylic": Price(3.0, "EUR", "kg"),
        }
        report = analyse_batch(recipe, batch, prices)
        assert report.cost.total_cost > 0
        assert report.mass_balance.is_within_tolerance
        assert isinstance(report.regulatory.findings, tuple)
