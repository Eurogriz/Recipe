"""Hansen Solubility Parameters (HSP) Calculator.

HSP описывают совместимость полимеров и растворителей через три параметра:
- δD: дисперсионные силы
- δP: полярные силы
- δH: водородные связи

Расстояние в HSP-пространстве:
    R₀ = √(4(δD₁-δD₂)² + (δP₁-δP₂)² + (δH₁-δH₂)²)

где 4 — весовой коэффициент (Hansen, 1967).

Совместимость: R₁ < R₀ → растворимо; R₁ > R₀ → нерастворимо.
RED (Relative Energy Difference) = R₁/R₀:
    RED < 1: хорошая совместимость
    RED ≈ 1: граница
    RED > 1: плохая совместимость

Источники:
    - Hansen, C.M. (2007). "Hansen Solubility Parameters: A User's Handbook" (2nd ed.).
      CRC Press. ISBN: 978-0849372488.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...domain.entities.recipe import Recipe


@dataclass(frozen=True, slots=True)
class HspPoint:
    """HSP coordinates for a single substance."""

    name: str
    delta_d: float  # Dispersion
    delta_p: float  # Polar
    delta_h: float  # Hydrogen bonding
    radius: float  # R₀ (interaction radius)


@dataclass(frozen=True, slots=True)
class HspCompatibility:
    """Compatibility result between two substances."""

    substance_a: str
    substance_b: str
    distance: float  # R₁
    radius_a: float
    radius_b: float
    red: float  # R₁/R₀(average)
    compatible: bool
    notes: tuple[str, ...] = ()


# Reference HSP values (from Hansen 2007 + Wicks/Jones/Pappas)
HSP_DATABASE: dict[str, HspPoint] = {
    "water": HspPoint("Water", delta_d=15.5, delta_p=16.0, delta_h=42.3, radius=12.3),
    "ethanol": HspPoint("Ethanol", delta_d=15.8, delta_p=8.8, delta_h=19.4, radius=12.4),
    "acetone": HspPoint("Acetone", delta_d=15.5, delta_p=10.4, delta_h=7.0, radius=9.4),
    "toluene": HspPoint("Toluene", delta_d=18.0, delta_p=1.4, delta_h=2.0, radius=9.0),
    "xylene": HspPoint("Xylene", delta_d=17.8, delta_p=1.0, delta_h=3.0, radius=9.0),
    "mineral spirits": HspPoint("Mineral spirits", delta_d=16.0, delta_p=1.0, delta_h=2.0, radius=10.0),
    "Texanol": HspPoint("Texanol", delta_d=16.1, delta_p=5.1, delta_h=9.8, radius=10.0),
    "butyl acetate": HspPoint("Butyl acetate", delta_d=15.8, delta_p=3.7, delta_h=6.3, radius=8.0),
    "propylene glycol": HspPoint("Propylene glycol", delta_d=16.8, delta_p=9.4, delta_h=23.3, radius=12.0),
    "ethylene glycol": HspPoint("Ethylene glycol", delta_d=17.0, delta_p=11.0, delta_h=26.0, radius=12.0),
    # Polymers
    "acrylic (PMMA-like)": HspPoint("Acrylic", delta_d=18.0, delta_p=10.0, delta_h=8.0, radius=10.0),
    "polyurethane": HspPoint("Polyurethane", delta_d=18.5, delta_p=9.5, delta_h=10.0, radius=11.0),
    "epoxy": HspPoint("Epoxy", delta_d=18.5, delta_p=11.0, delta_h=12.0, radius=11.5),
    "alkyd": HspPoint("Alkyd", delta_d=18.5, delta_p=9.0, delta_h=8.0, radius=11.0),
    "silicone": HspPoint("Silicone", delta_d=15.0, delta_p=3.0, delta_h=3.0, radius=8.0),
    "PVA": HspPoint("PVA", delta_d=17.5, delta_p=12.0, delta_h=20.0, radius=14.0),
}


class HspCalculator:
    """Калькулятор совместимости по Hansen Solubility Parameters."""

    @classmethod
    def lookup(cls, name: str) -> HspPoint | None:
        """Look up HSP for a known substance."""
        name_lower = name.lower().strip()
        for key, point in HSP_DATABASE.items():
            if name_lower in key.lower() or key.lower() in name_lower:
                return point
        return None

    @classmethod
    def calculate_distance(cls, point_a: HspPoint, point_b: HspPoint) -> float:
        """Calculate HSP distance R₁ between two substances.

        R₁ = √(4(δD_a-δD_b)² + (δP_a-δP_b)² + (δH_a-δH_b)²)
        """
        term_d = 4 * (point_a.delta_d - point_b.delta_d) ** 2
        term_p = (point_a.delta_p - point_b.delta_p) ** 2
        term_h = (point_h := (point_a.delta_h - point_b.delta_h) ** 2)
        return sqrt(term_d + term_p + term_h)

    @classmethod
    def check_compatibility(
        cls,
        substance_a: str,
        substance_b: str,
    ) -> HspCompatibility | None:
        """Check HSP compatibility between two substances.

        Returns None if one of the substances is not in the database.
        """
        point_a = cls.lookup(substance_a)
        point_b = cls.lookup(substance_b)

        if point_a is None or point_b is None:
            return None

        distance = cls.calculate_distance(point_a, point_b)
        avg_radius = (point_a.radius + point_b.radius) / 2
        red = distance / avg_radius if avg_radius > 0 else float("inf")
        compatible = red < 1.0

        notes: list[str] = []
        if red > 1.5:
            notes.append(f"⚠ RED={red:.2f} — poor compatibility, expect phase separation")
        elif red < 0.5:
            notes.append(f"✓ RED={red:.2f} — excellent compatibility")

        return HspCompatibility(
            substance_a=point_a.name,
            substance_b=point_b.name,
            distance=round(distance, 2),
            radius_a=point_a.radius,
            radius_b=point_b.radius,
            red=round(red, 3),
            compatible=compatible,
            notes=tuple(notes),
        )

    @classmethod
    def find_best_solvent(
        cls,
        polymer_name: str,
        solvent_candidates: tuple[str, ...] | None = None,
    ) -> tuple[HspCompatibility, ...] | None:
        """Find best solvent for a polymer from candidates.

        Default candidates: common coating solvents.
        """
        candidates = solvent_candidates or (
            "Water", "Ethanol", "Acetone", "Toluene", "Xylene",
            "Mineral spirits", "Texanol", "Butyl acetate",
            "Propylene glycol", "Ethylene glycol",
        )

        polymer = cls.lookup(polymer_name)
        if polymer is None:
            return None

        results: list[HspCompatibility] = []
        for solvent_name in candidates:
            result = cls.check_compatibility(polymer_name, solvent_name)
            if result is not None:
                results.append(result)

        # Sort by RED (lowest = best)
        results.sort(key=lambda r: r.red)
        return tuple(results)

    @classmethod
    def analyze_recipe_compatibility(
        cls,
        recipe: Recipe,
    ) -> tuple[HspCompatibility, ...]:
        """Analyze HSP compatibility for all pairs of identified substances in a recipe."""
        # Find substances in recipe (heuristic by name)
        identified: list[HspPoint] = []
        for comp in recipe.all_components:
            point = cls.lookup(comp.name)
            if point is not None:
                identified.append(point)

        if len(identified) < 2:
            return ()

        results: list[HspCompatibility] = []
        for i, a in enumerate(identified):
            for b in identified[i + 1 :]:
                distance = cls.calculate_distance(a, b)
                avg_radius = (a.radius + b.radius) / 2
                red = distance / avg_radius if avg_radius > 0 else float("inf")
                results.append(
                    HspCompatibility(
                        substance_a=a.name,
                        substance_b=b.name,
                        distance=round(distance, 2),
                        radius_a=a.radius,
                        radius_b=b.radius,
                        red=round(red, 3),
                        compatible=red < 1.0,
                    )
                )

        # Sort by RED
        results.sort(key=lambda r: r.red)
        return tuple(results)
