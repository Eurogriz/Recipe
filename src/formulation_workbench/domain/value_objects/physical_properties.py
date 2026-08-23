"""Physical properties of a raw material.

Every field is optional so the domain gracefully degrades on legacy
data.  All units are SI or the convention used by the corresponding
industry practice (e.g. g/100 g for oil absorption).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PhysicalProperties:
    """Bundle of physicochemical parameters used by the calculators."""

    # Base
    density_g_per_cm3: float | None = None  # ρ at 20 °C
    molar_mass_g_per_mol: float | None = None
    melting_point_c: float | None = None
    boiling_point_c: float | None = None
    flash_point_c: float | None = None

    # Colloid / film-forming
    solids_fraction: float | None = None  # 0..1 — non-volatile mass fraction
    voc_fraction: float | None = None  # 0..1 — VOC mass fraction (per Directive 2004/42/EC)
    water_fraction: float | None = None  # 0..1 — water content
    ph: float | None = None

    # Pigment-specific
    oil_absorption_g_per_100g: float | None = None  # ISO 787-5 / ASTM D281
    mean_particle_size_um: float | None = None
    refractive_index: float | None = None
    tinting_strength: float | None = None  # relative to reference (usually TiO2 = 100)

    # Polymer-specific
    glass_transition_c: float | None = None  # Tg of the neat polymer
    minimum_film_forming_temp_c: float | None = None
    equivalent_weight_g_per_eq: float | None = None  # epoxy / OH / NCO / acid
    # Reactive-amine descriptors (used by the extended stoichiometry
    # engine).  Together they replace the naive "each amine hydrogen
    # counts equally" assumption:
    #   - primary_amine_count / secondary_amine_count = per-molecule tally,
    #   - primary_amine_reactivity / secondary_amine_reactivity = effective
    #     conversion factor at ambient cure (0..1); defaults 1.0 / 0.5 are
    #     industry norms for aliphatic amines.
    primary_amine_h_count: int | None = None
    secondary_amine_h_count: int | None = None
    primary_amine_reactivity: float | None = None
    secondary_amine_reactivity: float | None = None
    # Functionality — number of *reactive* groups per molecule.  Used by
    # Flory-Stockmayer gelation / max-conversion math.  For polymers this
    # is the number-average functionality.
    functionality: float | None = None

    # Solvent-specific
    hansen_delta_d: float | None = None  # MPa^0.5, dispersive
    hansen_delta_p: float | None = None  # polar
    hansen_delta_h: float | None = None  # hydrogen bonding
    evaporation_rate_bua: float | None = None  # butyl acetate = 1

    # Regulatory / safety
    reach_registered: bool | None = None
    ghs_pictograms: tuple[str, ...] = ()
    hazard_statements: tuple[str, ...] = ()  # e.g. ("H317", "H400")

    def is_solvent_like(self) -> bool:
        """Heuristic used by the technological rules."""
        return (self.voc_fraction is not None and self.voc_fraction > 0.5) or (
            self.hansen_delta_d is not None
        )

    def is_solids_carrier(self) -> bool:
        return self.solids_fraction is not None and self.solids_fraction >= 0.5


__all__ = ["PhysicalProperties"]
