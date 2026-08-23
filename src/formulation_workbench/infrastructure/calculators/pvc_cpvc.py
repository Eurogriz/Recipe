"""PVC/CPVC Calculator.

PVC (Pigment Volume Concentration) — объёмная концентрация пигмента в сухой плёнке.
CPVC (Critical PVC) — точка, при которой связующего становится недостаточно
для заполнения пустот между пигментными частицами.

PVC/CPVC ratio определяет класс блеска:
- < 0.4: глянцевая
- 0.4-0.6: полуглянцевая
- 0.6-0.85: матовая
- 0.85-1.0: глубоко-матовая
- > 1.0: дефектная (меление, пористость)

Формулы:
    PVC = V_pigment / (V_pigment + V_binder_solids)
    CPVC ≈ f(тип пигмента, форма частиц, масляное число)
    Oil absorption → CPVC via Asbeck–Van Loo equation (упрощённая)

Эмпирическая формула (Asbeck, Van Loo, 1949):
    CPVC ≈ 1 / (1 + Σ(OAb × ρ_binder / 100)) для каждого пигмента

где:
    OAb — масляное число пигмента (г масла / 100 г пигмента)
    ρ_binder — плотность связующего
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...domain.entities.recipe import Recipe


@dataclass(frozen=True, slots=True)
class PvcCpvcResult:
    """Результат расчёта PVC/CPVC."""

    pvc_percent: float
    cpvc_percent: float
    pvc_cpvc_ratio: float
    finish_class: str  # "Gloss", "Semi-gloss", "Matte", "Deep matte", "Defective"
    binder_volume_l_per_100g: float
    pigment_volume_l_per_100g: float
    notes: tuple[str, ...] = ()


class PvcCpvcCalculator:
    """Калькулятор PVC/CPVC.

    Использует:
    - Типичные плотности пигментов и связующих (defaults)
    - Масляные числа (oil absorption) для основных пигментов
    - Может принимать overrides для конкретных рецептур
    """

    # Default densities (g/cm³)
    DEFAULT_PIGMENT_DENSITIES: dict[str, float] = {
        "titanium dioxide": 4.23,  # rutile
        "calcium carbonate": 2.71,
        "talc": 2.75,
        "kaolin": 2.60,
        "silica": 2.65,
        "zinc oxide": 5.60,
        "iron oxide": 5.00,
        "carbon black": 1.80,
        "phthalo blue": 1.60,
    }

    DEFAULT_BINDER_DENSITIES: dict[str, float] = {
        "acrylic": 1.05,
        "polyurethane": 1.10,
        "alkyd": 1.05,
        "epoxy": 1.15,
        "silicone": 1.02,
        "pva": 1.05,
        "vinyl acetate": 1.05,
    }

    # Oil absorption values (g oil / 100 g pigment)
    # Source: Wicks/Jones/Pappas, "Organic Coatings" Table 27.1
    DEFAULT_OIL_ABSORPTION: dict[str, float] = {
        "titanium dioxide": 22.0,  # Ti-Pure R-902 typical
        "calcium carbonate": 28.0,
        "talc": 35.0,
        "kaolin": 40.0,
        "silica": 35.0,
        "zinc oxide": 18.0,
        "iron oxide": 30.0,
        "carbon black": 120.0,  # high
    }

    # Pigment keywords (heuristic detection)
    PIGMENT_KEYWORDS: tuple[str, ...] = (
        "titanium dioxide",
        "tio2",
        "calcium carbonate",
        "talc",
        "kaolin",
        "silica",
        "zinc oxide",
        "iron oxide",
        "carbon black",
        "phthalocyanine",
        "pigment",
    )

    BINDER_KEYWORDS: tuple[str, ...] = (
        "acrylic",
        "polyurethane",
        "alkyd",
        "epoxy",
        "silicone",
        "pva",
        "vinyl acetate",
        "binder",
        "emulsion",
        "dispersion",
    )

    @classmethod
    def calculate(
        cls,
        recipe: Recipe,
        pigment_densities: dict[str, float] | None = None,
        binder_densities: dict[str, float] | None = None,
        oil_absorption: dict[str, float] | None = None,
    ) -> PvcCpvcResult:
        """Рассчитать PVC и CPVC для рецептуры.

        Args:
            recipe: Рецептура.
            pigment_densities: Overrides плотностей пигментов (name → g/cm³).
            binder_densities: Overrides плотностей связующих (name → g/cm³).
            oil_absorption: Overrides масляных чисел (name → g/100g).
        """
        pigment_densities = {**cls.DEFAULT_PIGMENT_DENSITIES, **(pigment_densities or {})}
        binder_densities = {**cls.DEFAULT_BINDER_DENSITIES, **(binder_densities or {})}
        oil_absorption = {**cls.DEFAULT_OIL_ABSORPTION, **(oil_absorption or {})}

        # Identify pigments vs binders (heuristic by name)
        pigment_volume_l_per_100g = 0.0
        binder_volume_l_per_100g = 0.0

        notes: list[str] = []
        pigment_count = 0
        binder_count = 0

        for comp in recipe.all_components:
            comp_lower = comp.name.lower()
            is_pigment = any(kw in comp_lower for kw in cls.PIGMENT_KEYWORDS)
            is_binder = any(kw in comp_lower for kw in cls.BINDER_KEYWORDS)

            if is_pigment:
                # Find density by exact name match or keyword match
                density = 1.0
                for key, val in pigment_densities.items():
                    if key in comp_lower:
                        density = val
                        break
                # Volume per 100g of recipe (since comp.mass_percent is mass %)
                volume = comp.mass_percent / density  # cm³ / 100g
                pigment_volume_l_per_100g += volume / 1000.0  # → L / 100g
                pigment_count += 1
            elif is_binder:
                # Find density
                density = 1.0
                for key, val in binder_densities.items():
                    if key in comp_lower:
                        density = val
                        break
                # Assume binder is 50% solids (typical emulsion); full volume contribution
                # For accurate calc, would need solids % per binder. We approximate.
                volume = comp.mass_percent / density
                binder_volume_l_per_100g += volume / 1000.0
                binder_count += 1

        total_volume = pigment_volume_l_per_100g + binder_volume_l_per_100g

        if total_volume == 0:
            return PvcCpvcResult(
                pvc_percent=0.0,
                cpvc_percent=0.0,
                pvc_cpvc_ratio=0.0,
                finish_class="Unknown",
                binder_volume_l_per_100g=0.0,
                pigment_volume_l_per_100g=0.0,
                notes=("⚠ No pigments or binders identified",),
            )

        # PVC = V_pigment / V_total
        pvc_percent = (pigment_volume_l_per_100g / total_volume) * 100.0

        # CPVC estimation (simplified Asbeck-Van Loo)
        # CPVC ≈ 1 / (1 + Σ(OAb_i × ρ_binder_avg / (100 × ρ_pigment_i)))
        # Simplified: use weighted average oil absorption
        cpvc_percent = cls._estimate_cpvc(recipe, pigment_densities, oil_absorption)

        ratio = pvc_percent / cpvc_percent if cpvc_percent > 0 else 0.0

        # Finish class
        if ratio < 0.4:
            finish = "Gloss"
        elif ratio < 0.6:
            finish = "Semi-gloss"
        elif ratio < 0.85:
            finish = "Matte"
        elif ratio < 1.0:
            finish = "Deep matte"
        else:
            finish = "Defective (above CPVC — chalk risk)"

        # Notes
        if pigment_count == 0:
            notes.append("⚠ No pigments identified — PVC=0")
        if binder_count == 0:
            notes.append("⚠ No binders identified — PVC may be inaccurate")
        if ratio > 1.0:
            notes.append("⚠ PVC > CPVC — risk of chalking, poor film integrity")
        if ratio < 0.3:
            notes.append("⚠ PVC very low — high gloss, possibly over-bound")

        return PvcCpvcResult(
            pvc_percent=round(pvc_percent, 2),
            cpvc_percent=round(cpvc_percent, 2),
            pvc_cpvc_ratio=round(ratio, 3),
            finish_class=finish,
            binder_volume_l_per_100g=round(binder_volume_l_per_100g, 4),
            pigment_volume_l_per_100g=round(pigment_volume_l_per_100g, 4),
            notes=tuple(notes),
        )

    @classmethod
    def _estimate_cpvc(
        cls,
        recipe: Recipe,
        pigment_densities: dict[str, float],
        oil_absorption: dict[str, float],
    ) -> float:
        """Estimate CPVC using weighted average oil absorption.

        Simplified formula (Pierce & Holst, 1937, modified):
            CPVC ≈ 1 / (1 + Σ(w_i × OA_i) / (100 × ρ_avg))
        """
        total_oil = 0.0
        total_mass = 0.0
        total_density_volume = 0.0

        for comp in recipe.all_components:
            comp_lower = comp.name.lower()
            is_pigment = any(kw in comp_lower for kw in cls.PIGMENT_KEYWORDS)
            if not is_pigment:
                continue

            oa = 0.0
            for key, val in oil_absorption.items():
                if key in comp_lower:
                    oa = val
                    break

            density = 1.0
            for key, val in pigment_densities.items():
                if key in comp_lower:
                    density = val
                    break

            total_oil += comp.mass_percent * oa
            total_mass += comp.mass_percent
            total_density_volume += comp.mass_percent / density

        if total_mass == 0:
            return 50.0  # default

        avg_density = total_mass / total_density_volume if total_density_volume > 0 else 2.5
        avg_oa = total_oil / total_mass

        # Asbeck-Van Loo approximation
        cpvc = 1.0 / (1.0 + avg_oa / (100.0 * avg_density))
        cpvc_percent = cpvc * 100.0

        # Sanity bound
        return max(20.0, min(cpvc_percent, 80.0))
