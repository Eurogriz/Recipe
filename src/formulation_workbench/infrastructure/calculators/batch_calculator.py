"""Batch Calculator — масштабирование рецептуры на любой объём партии.

Реализует пересчёт:
- % → кг (по массе партии)
- % → литры (по объёму партии с учётом плотности)
- кг ↔ литры (по плотности компонента)
- Стоимость партии (если указаны цены)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...domain.entities.recipe import Recipe


@dataclass(frozen=True, slots=True)
class BatchComponentAmount:
    """Количество одного компонента в партии."""

    name: str
    cas_number: str
    mass_percent: float
    mass_kg: float
    volume_l: float
    cost_estimate: float | None = None


@dataclass(frozen=True, slots=True)
class BatchResult:
    """Результат расчёта партии."""

    target_mass_kg: float
    target_volume_l: float
    total_density_g_per_cm3: float
    components: tuple[BatchComponentAmount, ...]
    total_cost_estimate: float | None = None
    warnings: tuple[str, ...] = ()


class BatchCalculator:
    """Калькулятор для масштабирования рецептуры на заданную массу/объём партии.

    Формулы:
        mass_i = mass_percent_i / 100 × target_mass_kg
        volume_i = mass_i / density_i / 1000 (кг → литры, если density в г/см³)
        density_total = 1 / Σ(mass_percent_i / 100 / density_i)
        target_volume_l = target_mass_kg / density_total / 1000 × 1000 = target_mass_kg / density_total

    Если плотности компонентов неизвестны, используются разумные предположения:
        - Вода: 1.0 г/см³
        - Пигменты/наполнители: 2.5–4.5 г/см³ (зависит от типа)
        - Связующие: 1.0–1.2 г/см³ (для дисперсий)
        - Растворители: 0.8–1.5 г/см³

    Defaults могут быть переопределены пользователем.
    """

    # Default densities for common material types (g/cm³)
    DEFAULT_DENSITIES: dict[str, float] = {
        "water": 1.000,
        "titanium dioxide": 4.230,
        "calcium carbonate": 2.711,
        "talc": 2.750,
        "kaolin": 2.600,
        "silica": 2.650,
        "acrylic": 1.050,  # for dispersions
        "polyurethane": 1.100,
        "alkyd": 1.050,
        "epoxy": 1.150,
        "silicone": 1.020,
        "pva": 1.050,
        "Texanol": 0.950,
        "propylene glycol": 1.036,
        "ethylene glycol": 1.113,
        "glycol ether": 0.960,
    }

    @classmethod
    def calculate_for_mass(
        cls,
        recipe: Recipe,
        target_mass_kg: float,
        densities: dict[str, float] | None = None,
        prices_per_kg: dict[str, float] | None = None,
    ) -> BatchResult:
        """Рассчитать партию по целевой массе.

        Args:
            recipe: Рецептура.
            target_mass_kg: Целевая масса партии в кг.
            densities: Плотности компонентов (name → g/cm³). None → использовать defaults.
            prices_per_kg: Цены (name → price/kg). None → без расчёта стоимости.
        """
        if target_mass_kg <= 0:
            raise ValueError(f"target_mass_kg must be positive, got {target_mass_kg}")

        densities = densities or cls.DEFAULT_DENSITIES
        warnings: list[str] = []

        # Sum mass percents (should be ~100)
        total_percent = sum(c.mass_percent for c in recipe.all_components)
        if abs(total_percent - 100.0) > 1.0:
            warnings.append(f"⚠ Mass percents sum to {total_percent:.2f}% (expected 100%)")

        # Compute scale factor
        target_mass_kg / (total_percent / 100.0)

        components: list[BatchComponentAmount] = []
        total_cost = 0.0
        cost_known = False

        for comp in recipe.all_components:
            mass_kg = comp.mass_percent / 100.0 * target_mass_kg
            density = densities.get(comp.name.lower(), 1.0)
            if comp.name.lower() not in densities:
                warnings.append(f"⚠ No density for '{comp.name}', assuming 1.0 g/cm³")
            volume_l = mass_kg / density  # kg / (g/cm³) = L (1 kg = 1000 cm³ = 1 L at density 1)

            cost = None
            if prices_per_kg is not None and comp.name in prices_per_kg:
                cost = mass_kg * prices_per_kg[comp.name]
                total_cost += cost
                cost_known = True

            components.append(
                BatchComponentAmount(
                    name=comp.name,
                    cas_number=comp.cas_number,
                    mass_percent=comp.mass_percent,
                    mass_kg=round(mass_kg, 4),
                    volume_l=round(volume_l, 4),
                    cost_estimate=round(cost, 2) if cost is not None else None,
                )
            )

        # Total density via rule of mixtures (volume-weighted inverse)
        total_volume_l = sum(c.volume_l for c in components)
        total_density = target_mass_kg / total_volume_l if total_volume_l > 0 else 1.0

        return BatchResult(
            target_mass_kg=target_mass_kg,
            target_volume_l=round(target_mass_kg / total_density, 4),
            total_density_g_per_cm3=round(total_density, 4),
            components=tuple(components),
            total_cost_estimate=round(total_cost, 2) if cost_known else None,
            warnings=tuple(warnings),
        )

    @classmethod
    def calculate_for_volume(
        cls,
        recipe: Recipe,
        target_volume_l: float,
        densities: dict[str, float] | None = None,
    ) -> BatchResult:
        """Рассчитать партию по целевому объёму.

        Сначала рассчитываем для произвольной массы, потом масштабируем.
        """
        # Rough calculation
        densities = densities or cls.DEFAULT_DENSITIES
        avg_density = cls._estimate_average_density(recipe, densities)
        target_mass_kg = target_volume_l * avg_density

        result = cls.calculate_for_mass(recipe, target_mass_kg, densities)
        # Scale to exact volume
        if result.total_density_g_per_cm3 > 0:
            scale = target_volume_l / result.target_volume_l
            new_components = tuple(
                BatchComponentAmount(
                    name=c.name,
                    cas_number=c.cas_number,
                    mass_percent=c.mass_percent,
                    mass_kg=round(c.mass_kg * scale, 4),
                    volume_l=round(c.volume_l * scale, 4),
                    cost_estimate=c.cost_estimate,
                )
                for c in result.components
            )
            return BatchResult(
                target_mass_kg=round(target_mass_kg * scale, 4),
                target_volume_l=target_volume_l,
                total_density_g_per_cm3=result.total_density_g_per_cm3,
                components=new_components,
                total_cost_estimate=result.total_cost_estimate,
                warnings=result.warnings,
            )
        return result

    @classmethod
    def _estimate_average_density(cls, recipe: Recipe, densities: dict[str, float]) -> float:
        """Rough average density estimate from composition."""
        weighted_sum = 0.0
        for comp in recipe.all_components:
            density = densities.get(comp.name.lower(), 1.0)
            weighted_sum += comp.mass_percent / 100.0 / density
        if weighted_sum > 0:
            return 1.0 / weighted_sum
        return 1.0
