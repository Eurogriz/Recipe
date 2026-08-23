"""Synthetic 'reality' the qualification suite trains against.

A tiny physicochemical model that captures the shape of well-known
paint dependencies without pretending to be a real physics engine:

- **gloss_60** grows with binder %, dampens with pigment/extender at
  high PVC (matte at PVC > 0.5), and is capped at 95.
- **hiding_power** grows with TiO2 mass %.
- **viscosity_mid_shear** grows quickly once thickener > 0.4 % and
  softens with water content.
- **voc_content** = mass % of a labelled solvent × its density factor.
- **freeze_thaw_cycles** benefits from antifreeze.

The model is deliberately nonlinear + interaction-heavy so the
RandomForest can learn something non-trivial and the optimiser has
real trade-offs to solve.  Every function returns a plain float — no
numpy dependency for the ground truth itself.
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LabMeasurements:
    gloss_60: float
    hiding_power_m2_per_l: float
    viscosity_mid_shear: float
    voc_content: float
    freeze_thaw_cycles: int


def _get(mass_pct: dict[str, float], name: str) -> float:
    return mass_pct.get(name, 0.0)


def _pvc(mass_pct: dict[str, float]) -> float:
    """Rough PVC proxy — pigment volume vs binder volume."""
    pig = _get(mass_pct, "TiO2") + _get(mass_pct, "CaCO3") + _get(mass_pct, "Talc")
    binder = _get(mass_pct, "Acrylic") + _get(mass_pct, "PU resin")
    if pig + binder == 0:
        return 0.0
    # Rough densities: pigment 3.5, binder 1.05 → PVC ≈ (pig/3.5) / ((pig/3.5) + binder/1.05)
    pv = pig / 3.5
    bv = binder / 1.05
    return pv / (pv + bv) if (pv + bv) > 0 else 0.0


def gloss_60(mass_pct: dict[str, float]) -> float:
    binder = _get(mass_pct, "Acrylic") + _get(mass_pct, "PU resin")
    pvc = _pvc(mass_pct)
    # Base gloss driven by binder; PVC beyond 0.35 kills gloss.
    base = 5.0 + 1.4 * binder
    if pvc > 0.35:
        base -= (pvc - 0.35) * 220.0
    # Coalescent gives a small boost at 1-3 %.
    coa = _get(mass_pct, "Texanol")
    base += min(coa, 3.0) * 1.5
    return max(0.0, min(95.0, base))


def hiding_power(mass_pct: dict[str, float]) -> float:
    tio2 = _get(mass_pct, "TiO2")
    return max(0.0, 0.35 * tio2)


def viscosity_mid_shear(mass_pct: dict[str, float]) -> float:
    thickener = _get(mass_pct, "Rheo")
    water = _get(mass_pct, "Water")
    base = 40.0 + 1200.0 * (max(0.0, thickener - 0.3)) ** 1.4
    base *= max(0.4, 1.0 - water / 200.0)  # more water → thinner
    return base


def voc_content(mass_pct: dict[str, float]) -> float:
    """Assume Xylene/Texanol contribute; TDS-style g/L via density 0.87 kg/L."""
    xyl = _get(mass_pct, "Xylene")
    tex = _get(mass_pct, "Texanol")
    return xyl * 8.7 + tex * 4.0


def freeze_thaw_cycles(mass_pct: dict[str, float]) -> int:
    antifreeze = _get(mass_pct, "PG")
    return int(max(0, min(15, antifreeze * 2.5)))


def measure(
    mass_pct: dict[str, float],
    *,
    noise_std: float = 1.0,
    seed: int | None = None,
) -> LabMeasurements:
    rng = random.Random(seed)
    return LabMeasurements(
        gloss_60=max(0.0, gloss_60(mass_pct) + rng.gauss(0.0, noise_std)),
        hiding_power_m2_per_l=max(0.0, hiding_power(mass_pct) + rng.gauss(0.0, noise_std * 0.3)),
        viscosity_mid_shear=max(
            0.0, viscosity_mid_shear(mass_pct) + rng.gauss(0.0, noise_std * 12.0)
        ),
        voc_content=max(0.0, voc_content(mass_pct) + rng.gauss(0.0, noise_std * 0.5)),
        freeze_thaw_cycles=freeze_thaw_cycles(mass_pct),
    )


__all__ = [
    "LabMeasurements",
    "freeze_thaw_cycles",
    "gloss_60",
    "hiding_power",
    "measure",
    "viscosity_mid_shear",
    "voc_content",
]
