"""Rule of Mixtures Calculator.

Расчёт различных свойств смеси на основе правила аддитивности:

1. Density (inverse volume-weighted):
    1/ρ_mix = Σ(wᵢ / ρᵢ)
    (mass-weighted inverse)

2. Mass solids:
    mass_solids = Σ(mass_i × solids_fraction_i)

3. Volume solids:
    volume_solids = Σ(volume_i × solids_fraction_i)

4. VOC (Volatile Organic Compounds):
    VOC = Σ(volatile_mass) / total_volume
    (g/L)

5. DFT/WFT (Dry/Wet Film Thickness):
    WFT = DFT / volume_solids
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...domain.entities.recipe import Recipe


@dataclass(frozen=True, slots=True)
class RuleOfMixturesResult:
    """Результат расчёта по правилу смесей."""

    density_g_per_cm3: float
    mass_solids_percent: float
    volume_solids_percent: float
    voc_g_per_l: float
    pvc_percent: float | None = None
    notes: tuple[str, ...] = ()


class RuleOfMixturesCalculator:
    """Калькулятор свойств смеси по правилу аддитивности.

    Каждый компонент имеет атрибуты:
        density (г/см³)
        solids_fraction (0..1) — доля нелетучих веществ
        voc_fraction (0..1) — доля летучих органических (mutually exclusive с solids для воды)
    """

    # Default density (g/cm³)
    DEFAULT_DENSITIES: dict[str, float] = {
        "water": 1.000,
        "titanium dioxide": 4.230,
        "calcium carbonate": 2.711,
        "talc": 2.750,
        "acrylic": 1.050,
        "polyurethane": 1.100,
        "epoxy": 1.150,
        "alkyd": 1.050,
        "silicone": 1.020,
        "Texanol": 0.950,
        "propylene glycol": 1.036,
        "ethylene glycol": 1.113,
        "pva": 1.050,
        # Common solvents — critical for accurate VOC calculation
        "mineral spirits": 0.780,
        "white spirit": 0.780,
        "naphtha": 0.760,
        "xylene": 0.864,
        "toluene": 0.867,
        "acetone": 0.791,
        "butyl acetate": 0.882,
        "ethyl acetate": 0.902,
        "ethanol": 0.789,
        "isopropanol": 0.786,
        "butanol": 0.810,
        "methyl ethyl ketone": 0.805,
        "mek": 0.805,
        "plasticizer": 1.000,  # generic plasticizer
        "dibp": 1.043,  # diisobutyl phthalate
        "mineral oil": 0.850,
    }

    # Default solids fraction per component type
    # Heuristic: dispersions/pigments are 100% solids; water, glycols, solvents are 0%
    DEFAULT_SOLIDS: dict[str, float] = {
        "water": 0.0,
        "propylene glycol": 0.0,
        "ethylene glycol": 0.0,
        "Texanol": 0.0,
        "titanium dioxide": 1.0,
        "calcium carbonate": 1.0,
        "talc": 1.0,
        # Common solvents — all 0% solids
        "mineral spirits": 0.0,
        "white spirit": 0.0,
        "naphtha": 0.0,
        "xylene": 0.0,
        "toluene": 0.0,
        "acetone": 0.0,
        "butyl acetate": 0.0,
        "ethyl acetate": 0.0,
        "ethanol": 0.0,
        "isopropanol": 0.0,
        "butanol": 0.0,
        "methyl ethyl ketone": 0.0,
        "mek": 0.0,
        "dibp": 0.0,
        "dibutyl phthalate": 0.0,
        "mineral oil": 0.0,
    }

    # Default VOC fraction (organic volatiles — water not counted per EU 2004/42/CE)
    DEFAULT_VOC: dict[str, float] = {
        "water": 0.0,  # water is NOT VOC per EU Directive 2004/42/CE
        "propylene glycol": 1.0,  # debatable — some regs include it
        "ethylene glycol": 1.0,
        "Texanol": 1.0,
        # All common solvents — 100% VOC
        "mineral spirits": 1.0,
        "white spirit": 1.0,
        "naphtha": 1.0,
        "xylene": 1.0,
        "toluene": 1.0,
        "acetone": 1.0,
        "butyl acetate": 1.0,
        "ethyl acetate": 1.0,
        "ethanol": 1.0,
        "isopropanol": 1.0,
        "butanol": 1.0,
        "methyl ethyl ketone": 1.0,
        "mek": 1.0,
    }

    WATER_KEYWORDS: tuple[str, ...] = ("water", "вода", "aqua")
    GLYCOL_KEYWORDS: tuple[str, ...] = ("glycol", "гликоль")
    DISPERSION_KEYWORDS: tuple[str, ...] = ("emulsion", "dispersion", "дисперсия")
    SOLVENT_KEYWORDS: tuple[str, ...] = (
        "mineral spirits", "white spirit", "naphtha", "xylene", "toluene",
        "acetone", "butyl acetate", "ethyl acetate", "ethanol", "isopropanol",
        "butanol", "methyl ethyl ketone", "mek", "solvent", "растворитель",
        "сольвент", "ксилол", "толуол", "ацетон", "уайт-спирит",
    )

    @classmethod
    def calculate(
        cls,
        recipe: Recipe,
        densities: dict[str, float] | None = None,
        solids_fractions: dict[str, float] | None = None,
        voc_fractions: dict[str, float] | None = None,
    ) -> RuleOfMixturesResult:
        """Рассчитать свойства смеси.

        Args:
            recipe: Рецептура.
            densities: Overrides плотностей.
            solids_fractions: Overrides solids fraction (0..1) для каждого компонента.
            voc_fractions: Overrides VOC fraction (0..1).
        """
        densities = {**cls.DEFAULT_DENSITIES, **(densities or {})}
        solids_fractions = {**cls.DEFAULT_SOLIDS, **(solids_fractions or {})}
        voc_fractions = {**cls.DEFAULT_VOC, **(voc_fractions or {})}

        notes: list[str] = []

        # 1. Density (inverse volume-weighted)
        inverse_density_sum = 0.0
        for comp in recipe.all_components:
            density = cls._lookup_density(comp.name, densities, notes)
            if density > 0:
                inverse_density_sum += (comp.mass_percent / 100.0) / density
        density_total = 1.0 / inverse_density_sum if inverse_density_sum > 0 else 1.0

        # 2. Mass solids
        mass_solids = 0.0
        for comp in recipe.all_components:
            solids = cls._lookup_solids(comp.name, solids_fractions)
            mass_solids += (comp.mass_percent / 100.0) * solids * 100  # → percent

        # 3. Volume solids
        volume_solids_sum = 0.0
        total_volume_l_per_100g = 0.0
        for comp in recipe.all_components:
            density = cls._lookup_density(comp.name, densities, notes)
            volume_per_100g = (comp.mass_percent / 100.0) / density  # L/100g of recipe
            solids = cls._lookup_solids(comp.name, solids_fractions)
            volume_solids_sum += volume_per_100g * solids
            total_volume_l_per_100g += volume_per_100g
        volume_solids_percent = (
            (volume_solids_sum / total_volume_l_per_100g) * 100.0
            if total_volume_l_per_100g > 0
            else 0.0
        )

        # 4. VOC (g/L)
        # VOC mass per 100g of recipe
        voc_mass_per_100g = 0.0
        for comp in recipe.all_components:
            voc_frac = cls._lookup_voc(comp.name, voc_fractions)
            voc_mass_per_100g += (comp.mass_percent / 100.0) * voc_frac * 100  # g
        # VOC concentration = VOC mass / total volume
        total_volume_per_100g = total_volume_l_per_100g  # L
        voc_g_per_l = (
            voc_mass_per_100g / total_volume_per_100g
            if total_volume_per_100g > 0
            else 0.0
        )

        # EU Directive 2004/42/CE: water is NOT VOC
        # Note: this is a simplification. Real VOC per regulation is complex.

        return RuleOfMixturesResult(
            density_g_per_cm3=round(density_total, 4),
            mass_solids_percent=round(mass_solids, 2),
            volume_solids_percent=round(volume_solids_percent, 2),
            voc_g_per_l=round(voc_g_per_l, 2),
            notes=tuple(notes),
        )

    @classmethod
    def _lookup_density(
        cls, name: str, densities: dict[str, float], notes: list[str]
    ) -> float:
        """Look up density, fall back to heuristics."""
        name_lower = name.lower()
        # Exact match
        if name_lower in densities:
            return densities[name_lower]
        # Keyword match
        for key, val in densities.items():
            if key in name_lower:
                return val
        # Heuristic fallbacks
        if any(kw in name_lower for kw in cls.WATER_KEYWORDS):
            return 1.000
        if any(kw in name_lower for kw in cls.DISPERSION_KEYWORDS):
            return 1.050
        if any(kw in name_lower for kw in cls.GLYCOL_KEYWORDS):
            return 1.040
        # Pigment heuristic: assume 2.5 (typical average)
        if "pigment" in name_lower or any(
            p in name_lower
            for p in ("tio2", "titanium", "carbonate", "talc", "kaolin", "silica")
        ):
            return 2.500
        # Generic organic — assume 1.0
        notes.append(f"⚠ No density for '{name}', assuming 1.0 g/cm³")
        return 1.000

    @classmethod
    def _lookup_solids(cls, name: str, solids: dict[str, float]) -> float:
        """Look up solids fraction."""
        name_lower = name.lower()
        if name_lower in solids:
            return solids[name_lower]
        for key, val in solids.items():
            if key in name_lower:
                return val
        # Default heuristics
        if any(kw in name_lower for kw in cls.WATER_KEYWORDS):
            return 0.0
        if any(kw in name_lower for kw in cls.GLYCOL_KEYWORDS):
            return 0.0
        if any(kw in name_lower for kw in ("Texanol", "coalescent")):
            return 0.0
        # Solvents: 0% solids
        if any(kw in name_lower for kw in cls.SOLVENT_KEYWORDS):
            return 0.0
        # Dispersions/emulsions: ~50% solids
        if any(kw in name_lower for kw in cls.DISPERSION_KEYWORDS):
            return 0.5
        # Pigments, fillers: 100% solids
        if any(
            p in name_lower
            for p in ("tio2", "titanium", "carbonate", "talc", "kaolin", "silica")
        ):
            return 1.0
        # Binders/resins without dispersion/emulsion: 100% solids
        if any(kw in name_lower for kw in ("binder", "resin", "polymer")):
            return 1.0
        return 0.5  # conservative default

    @classmethod
    def _lookup_voc(cls, name: str, voc: dict[str, float]) -> float:
        """Look up VOC fraction."""
        name_lower = name.lower()
        if name_lower in voc:
            return voc[name_lower]
        for key, val in voc.items():
            if key in name_lower:
                return val
        # Default: water is 0% VOC
        if any(kw in name_lower for kw in cls.WATER_KEYWORDS):
            return 0.0
        # Glycol: 100% (EU includes glycols in VOC)
        if any(kw in name_lower for kw in cls.GLYCOL_KEYWORDS):
            return 1.0
        # Solvents: 100% VOC
        if any(kw in name_lower for kw in cls.SOLVENT_KEYWORDS):
            return 1.0
        # Coalescent: 100% VOC
        if any(kw in name_lower for kw in ("Texanol", "coalescent")):
            return 1.0
        # Pigments, fillers: 0% VOC
        if any(
            p in name_lower
            for p in ("tio2", "titanium", "carbonate", "talc", "kaolin", "silica")
        ):
            return 0.0
        return 0.0  # conservative default
