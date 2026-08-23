"""Batch-level cost, mass balance, and regulatory analysis.

The per-kg cost model in ``cost_calculator.py`` answers *how expensive
is the recipe as a specification*.  This module extends it to the
concrete *batch* produced in the lab — with real lot numbers, real
tolerances, and a real audit trail.

Provides:

- :class:`BatchCostBreakdown` — total cost of one batch (currency /
  amount), per-line component costs, and the lot number the cost is
  attached to.
- :class:`BatchMassBalance` — expected vs actual mass of the batch and
  the yield-vs-target percentage.
- :class:`BatchRegulatoryReport` — every regulatory finding that
  applies to the *actual* batch composition (identical to the per-kg
  check, but scoped to a specific lot).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .cost_calculator import CostLine, RecipeCost, RecipeCostCalculator
from .regulatory import RegulatoryComplianceChecker, RegulatoryFinding

if TYPE_CHECKING:
    from ..entities.experiment import BatchInfo
    from ..entities.recipe import Recipe
    from ..value_objects.cost import Price


@dataclass(frozen=True, slots=True)
class BatchCostLine:
    """Cost contribution of one component *scaled to the batch size*."""

    component_name: str
    mass_kg: float
    lot_number: str = ""
    unit_price: Price | None = None
    cost: float | None = None  # in the batch currency
    cost_per_kg_recipe: float | None = None


@dataclass(frozen=True, slots=True)
class BatchCostBreakdown:
    batch_number: str
    currency: str
    total_cost: float  # sum of priced lines
    priced_fraction: float
    lines: tuple[BatchCostLine, ...]
    missing_prices: tuple[str, ...] = field(default_factory=tuple)

    def summary(self) -> dict[str, float | str | int]:
        return {
            "batch_number": self.batch_number,
            "currency": self.currency,
            "total_cost": round(self.total_cost, 4),
            "priced_fraction": round(self.priced_fraction, 4),
            "missing_prices": len(self.missing_prices),
        }


@dataclass(frozen=True, slots=True)
class BatchMassBalance:
    batch_number: str
    target_mass_kg: float
    actual_mass_kg: float | None
    yield_percent: float | None  # None when actual missing

    @property
    def is_within_tolerance(self) -> bool:
        """Yield within ±2 % of target — an industry-typical acceptance."""
        if self.yield_percent is None:
            return False
        return 98.0 <= self.yield_percent <= 102.0


@dataclass(frozen=True, slots=True)
class BatchRegulatoryReport:
    batch_number: str
    findings: tuple[RegulatoryFinding, ...]

    @property
    def has_error(self) -> bool:
        from .regulatory import Severity

        return any(f.severity is Severity.ERROR for f in self.findings)


@dataclass(frozen=True, slots=True)
class BatchReport:
    """Bundle of all three batch analyses."""

    cost: BatchCostBreakdown
    mass_balance: BatchMassBalance
    regulatory: BatchRegulatoryReport


# ---------------------------------------------------------------------------
# Compute
# ---------------------------------------------------------------------------
def _cost_line_to_batch(
    line: CostLine,
    batch_mass_kg: float,
    lot_numbers: dict[str, str],
) -> BatchCostLine:
    mass_kg = line.mass_percent / 100.0 * batch_mass_kg
    cost_val: float | None = None
    if line.cost_per_kg_recipe is not None:
        cost_val = line.cost_per_kg_recipe * batch_mass_kg
    return BatchCostLine(
        component_name=line.component_name,
        mass_kg=mass_kg,
        lot_number=lot_numbers.get(line.component_name, ""),
        unit_price=line.unit_price,
        cost=cost_val,
        cost_per_kg_recipe=line.cost_per_kg_recipe,
    )


def analyse_batch_cost(
    recipe: Recipe,
    batch: BatchInfo,
    prices: dict[str, Price],
) -> BatchCostBreakdown:
    """Scale the per-kg cost breakdown to the actual batch size."""
    per_kg: RecipeCost = RecipeCostCalculator.calculate(recipe, prices)
    batch_mass = batch.actual_mass_kg or batch.target_mass_kg
    lot_numbers = batch.lot_numbers or {}
    lines = tuple(_cost_line_to_batch(ln, batch_mass, lot_numbers) for ln in per_kg.lines)
    return BatchCostBreakdown(
        batch_number=batch.batch_number,
        currency=per_kg.currency,
        total_cost=per_kg.total_cost_per_kg * batch_mass,
        priced_fraction=per_kg.priced_fraction,
        lines=lines,
        missing_prices=per_kg.missing_prices,
    )


def analyse_batch_mass_balance(batch: BatchInfo) -> BatchMassBalance:
    if batch.actual_mass_kg is None or batch.target_mass_kg <= 0:
        return BatchMassBalance(
            batch_number=batch.batch_number,
            target_mass_kg=batch.target_mass_kg,
            actual_mass_kg=batch.actual_mass_kg,
            yield_percent=None,
        )
    yield_pct = 100.0 * batch.actual_mass_kg / batch.target_mass_kg
    return BatchMassBalance(
        batch_number=batch.batch_number,
        target_mass_kg=batch.target_mass_kg,
        actual_mass_kg=batch.actual_mass_kg,
        yield_percent=yield_pct,
    )


def analyse_batch_regulatory(
    recipe: Recipe,
    batch: BatchInfo,
    *,
    checker: RegulatoryComplianceChecker | None = None,
    consumer_use: bool = True,
) -> BatchRegulatoryReport:
    """Same rule set as the recipe check — surface findings tied to the batch."""
    findings = (checker or RegulatoryComplianceChecker()).check(recipe, consumer_use=consumer_use)
    return BatchRegulatoryReport(batch_number=batch.batch_number, findings=tuple(findings))


def analyse_batch(
    recipe: Recipe,
    batch: BatchInfo,
    prices: dict[str, Price],
    *,
    regulatory_checker: RegulatoryComplianceChecker | None = None,
    consumer_use: bool = True,
) -> BatchReport:
    """One-shot bundle of cost / mass balance / regulatory analyses."""
    return BatchReport(
        cost=analyse_batch_cost(recipe, batch, prices),
        mass_balance=analyse_batch_mass_balance(batch),
        regulatory=analyse_batch_regulatory(
            recipe, batch, checker=regulatory_checker, consumer_use=consumer_use
        ),
    )


__all__ = [
    "BatchCostBreakdown",
    "BatchCostLine",
    "BatchMassBalance",
    "BatchRegulatoryReport",
    "BatchReport",
    "analyse_batch",
    "analyse_batch_cost",
    "analyse_batch_mass_balance",
    "analyse_batch_regulatory",
]
