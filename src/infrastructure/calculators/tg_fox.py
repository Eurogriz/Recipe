"""Tg Calculator по уравнению Fox.

Для смесей полимеров температура стеклования (Tg) рассчитывается
по уравнению Fox (1956):

    1/Tg_mix = Σ(wᵢ / Tgᵢ)

где:
    wᵢ — массовая доля i-го полимера
    Tgᵢ — температура стеклования i-го полимера (в Кельвинах!)

Это работает для совместимых полимерных смесей (однофазных).
Для двухфазных смесей (большинство случаев) используются
другие модели (Couchman, Kwei).

Источники:
    - Fox, T.G. (1956). "Influence of diluent and of copolymer composition
      on the glass temperature of a polymer system".
      Bulletin of the American Physical Society, 1, 123.
    - Wicks/Jones/Pappas, "Organic Coatings" Chapter 4.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...domain.entities.recipe import Recipe


@dataclass(frozen=True, slots=True)
class TgResult:
    """Результат расчёта Tg."""

    tg_celsius: float
    tg_kelvin: float
    components_considered: tuple[tuple[str, float, float], ...]  # (name, mass%, Tg in K)
    notes: tuple[str, ...] = ()


class TgCalculator:
    """Калькулятор Tg для полимерных смесей по уравнению Fox.

    Типичные Tg полимеров (°C):
    - Полибутилакрилат (PBA): -54
    - Полиметилметакрилат (PMMA): 105
    - Полистирол (PS): 100
    - Поливинилацетат (PVAc): 32
    - Полиуретан (PU, soft): -40
    - Эпоксидная смола (DGEBA, cured): 80-150
    - Алкид (medium oil): -10
    - Силикон (PDMS): -127
    """

    # Typical Tg values (°C) for binder identification
    TYPICAL_TG: dict[str, float] = {
        "polybutyl acrylate": -54.0,
        "pba": -54.0,
        "polymethyl methacrylate": 105.0,
        "pmma": 105.0,
        "polystyrene": 100.0,
        "ps": 100.0,
        "polyvinyl acetate": 32.0,
        "pvac": 32.0,
        "polyurethane": -40.0,
        "epoxy": 100.0,
        "alkyd": -10.0,
        "silicone": -127.0,
        "pdms": -127.0,
        "polyacrylonitrile": 95.0,
        "pan": 95.0,
        "polyvinyl chloride": 81.0,
        "pvc": 81.0,
        "polyethylene": -120.0,
        "pe": -120.0,
        "polypropylene": -20.0,
        "pp": -20.0,
    }

    BINDER_KEYWORDS: tuple[str, ...] = (
        "acrylic", "polyurethane", "alkyd", "epoxy", "silicone",
        "pva", "vinyl acetate", "emulsion", "dispersion", "binder",
        "polymer", "resin",
    )

    @classmethod
    def calculate(
        cls,
        recipe: Recipe,
        binder_tg_overrides: dict[str, float] | None = None,
    ) -> TgResult:
        """Рассчитать Tg смеси по уравнению Fox.

        Args:
            recipe: Рецептура.
            binder_tg_overrides: Словарь overrides (component_name → Tg in °C).
        """
        # Find polymer/binder components
        polymer_components: list[tuple[str, float, float]] = []
        # (name, mass_percent, tg_K)

        for comp in recipe.all_components:
            comp_lower = comp.name.lower()
            is_binder = any(kw in comp_lower for kw in cls.BINDER_KEYWORDS)
            if not is_binder:
                continue

            # Try override first
            tg_c = binder_tg_overrides.get(comp.name) if binder_tg_overrides else None

            if tg_c is None:
                # Try keyword match
                tg_c = None
                for key, val in cls.TYPICAL_TG.items():
                    if key in comp_lower:
                        tg_c = val
                        break

            if tg_c is None:
                continue

            tg_k = tg_c + 273.15
            polymer_components.append((comp.name, comp.mass_percent, tg_k))

        notes: list[str] = []

        if not polymer_components:
            return TgResult(
                tg_celsius=0.0,
                tg_kelvin=273.15,
                components_considered=(),
                notes=("⚠ No polymer components identified for Tg calculation",),
            )

        # Apply Fox equation: 1/Tg_mix = Σ(wᵢ / Tgᵢ)
        total_mass = sum(p[1] for p in polymer_components)
        if total_mass == 0:
            return TgResult(
                tg_celsius=0.0,
                tg_kelvin=273.15,
                components_considered=(),
                notes=("⚠ Total polymer mass is zero",),
            )

        # Normalize mass percents to fractions of polymer content
        inverse_tg_sum = 0.0
        for _, mass_pct, tg_k in polymer_components:
            mass_fraction = mass_pct / total_mass
            inverse_tg_sum += mass_fraction / tg_k

        if inverse_tg_sum == 0:
            return TgResult(
                tg_celsius=0.0,
                tg_kelvin=273.15,
                components_considered=tuple(polymer_components),
                notes=("⚠ Inverse Tg sum is zero — invalid Tg values",),
            )

        tg_mix_k = 1.0 / inverse_tg_sum
        tg_mix_c = tg_mix_k - 273.15

        # Sanity checks
        if tg_mix_c < -150:
            notes.append(f"⚠ Tg very low ({tg_mix_c:.1f}°C) — verify binder Tg values")
        if tg_mix_c > 200:
            notes.append(f"⚠ Tg very high ({tg_mix_c:.1f}°C) — verify binder Tg values")

        return TgResult(
            tg_celsius=round(tg_mix_c, 2),
            tg_kelvin=round(tg_mix_k, 2),
            components_considered=tuple(polymer_components),
            notes=tuple(notes),
        )
