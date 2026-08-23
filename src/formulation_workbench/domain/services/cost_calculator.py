"""Recipe cost model.

Consumes a :class:`Recipe` plus a mapping ``component name -> Price``
and returns a per-kg / per-litre cost breakdown.  Prices missing for a
component are surfaced as ``missing_prices`` — cost calculation still
proceeds with the priced fraction so the estimate is monotonically
informative.

The formulator can then chain the cost into the class-ranker (a Premium
recipe with an unrealistically low cost usually signals a mislabel) or
into commercial reporting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..value_objects.cost import Price

if TYPE_CHECKING:
    from ..entities.recipe import Recipe


@dataclass(frozen=True, slots=True)
class CostLine:
    """Cost contribution of a single component."""

    component_name: str
    mass_percent: float
    unit_price: Price | None
    cost_per_kg_recipe: float | None  # currency / kg of finished recipe
    density_g_per_cm3: float | None = None


@dataclass(frozen=True, slots=True)
class RecipeCost:
    """Aggregated cost of a recipe."""

    currency: str
    total_cost_per_kg: float  # sum of priced lines only
    priced_fraction: float  # 0..1 — mass share for which price was known
    lines: tuple[CostLine, ...]
    missing_prices: tuple[str, ...] = field(default_factory=tuple)
    average_density_g_per_cm3: float | None = None

    @property
    def total_cost_per_litre(self) -> float | None:
        """``None`` when we lack the average density."""
        if self.average_density_g_per_cm3 is None:
            return None
        return self.total_cost_per_kg * self.average_density_g_per_cm3

    def summary(self) -> dict[str, float | str | int]:
        return {
            "currency": self.currency,
            "cost_per_kg": round(self.total_cost_per_kg, 4),
            "cost_per_l": (
                round(self.total_cost_per_litre, 4) if self.total_cost_per_litre else 0.0
            ),
            "priced_fraction": round(self.priced_fraction, 4),
            "missing_prices": len(self.missing_prices),
        }


class RecipeCostCalculator:
    """Compute :class:`RecipeCost` for a recipe + price catalog."""

    @classmethod
    def calculate(
        cls,
        recipe: Recipe,
        prices: dict[str, Price],
    ) -> RecipeCost:
        # Establish the base currency from the first available price.
        currency = "EUR"
        for name in (c.name for c in recipe.all_components):
            price = prices.get(name)
            if price is not None:
                currency = price.currency
                break

        lines: list[CostLine] = []
        missing: list[str] = []
        priced_mass_pct = 0.0
        total_cost_per_kg = 0.0
        density_sum = 0.0
        density_count = 0

        for component in recipe.all_components:
            price = prices.get(component.name)
            density = None
            if component.properties is not None:
                density = component.properties.density_g_per_cm3

            if price is None:
                missing.append(component.name)
                lines.append(
                    CostLine(
                        component_name=component.name,
                        mass_percent=component.mass_percent,
                        unit_price=None,
                        cost_per_kg_recipe=None,
                        density_g_per_cm3=density,
                    )
                )
                continue

            if price.currency != currency:
                # We do not silently convert FX; surface as missing.
                missing.append(component.name)
                lines.append(
                    CostLine(
                        component_name=component.name,
                        mass_percent=component.mass_percent,
                        unit_price=price,
                        cost_per_kg_recipe=None,
                        density_g_per_cm3=density,
                    )
                )
                continue

            try:
                price_per_kg = price.per_kg(density_g_per_cm3=density)
            except Exception:
                missing.append(component.name)
                lines.append(
                    CostLine(
                        component_name=component.name,
                        mass_percent=component.mass_percent,
                        unit_price=price,
                        cost_per_kg_recipe=None,
                        density_g_per_cm3=density,
                    )
                )
                continue

            component_cost_per_kg_recipe = price_per_kg * (component.mass_percent / 100.0)
            total_cost_per_kg += component_cost_per_kg_recipe
            priced_mass_pct += component.mass_percent

            lines.append(
                CostLine(
                    component_name=component.name,
                    mass_percent=component.mass_percent,
                    unit_price=price,
                    cost_per_kg_recipe=component_cost_per_kg_recipe,
                    density_g_per_cm3=density,
                )
            )

            if density and density > 0:
                density_sum += density * (component.mass_percent / 100.0)
                density_count += 1

        avg_density = density_sum if density_count else None
        priced_fraction = priced_mass_pct / 100.0 if priced_mass_pct else 0.0

        return RecipeCost(
            currency=currency,
            total_cost_per_kg=total_cost_per_kg,
            priced_fraction=priced_fraction,
            lines=tuple(lines),
            missing_prices=tuple(missing),
            average_density_g_per_cm3=avg_density,
        )


__all__ = ["CostLine", "RecipeCost", "RecipeCostCalculator"]
