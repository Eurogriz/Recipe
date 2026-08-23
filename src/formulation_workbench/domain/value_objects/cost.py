"""Money / cost value objects.

We keep it dependency-free: no ``decimal.Decimal`` gymnastics, no
``babel`` locale-aware formatting. Cost accounting for a formulation
almost always happens at four significant figures, so a ``float`` +
canonical rounding is perfectly adequate.
"""

from __future__ import annotations

from dataclasses import dataclass


class InvalidPriceError(ValueError):
    """Raised when a price value violates domain invariants."""


@dataclass(frozen=True, slots=True)
class Price:
    """Price of a raw material, per unit of measure.

    ``amount`` is expressed in the currency's minor unit-agnostic form
    (i.e. ``12.34 EUR``, not ``1234 cents``) so the value round-trips
    through JSON without losing readability.  ``unit`` describes what
    the amount is per — a canonical list is used by
    :meth:`normalise_to_kg`.
    """

    amount: float
    currency: str = "EUR"
    unit: str = "kg"  # kg | l | t | m3 | g | ml

    def __post_init__(self) -> None:
        if self.amount < 0:
            raise InvalidPriceError(f"Price cannot be negative: {self.amount}")
        if not self.currency or len(self.currency) != 3:
            raise InvalidPriceError(f"Currency must be a 3-letter ISO code, got {self.currency!r}")
        if self.unit not in _UNIT_TO_KG:
            raise InvalidPriceError(
                f"Unsupported unit {self.unit!r}. Allowed: {sorted(_UNIT_TO_KG)}"
            )

    # ------------------------------------------------------------------ helpers
    def per_kg(self, *, density_g_per_cm3: float | None = None) -> float:
        """Return the amount in *currency / kg*.

        Volumetric units require a density to translate.  If the caller
        cannot provide one and the unit is volumetric, a
        :class:`InvalidPriceError` is raised.
        """
        factor = _UNIT_TO_KG[self.unit]
        if factor is None:
            if density_g_per_cm3 is None or density_g_per_cm3 <= 0:
                raise InvalidPriceError(f"Unit {self.unit!r} requires a positive density_g_per_cm3")
            # 1 L = 1 dm^3 = 1000 cm^3 → density in kg/L equals density_g_per_cm3.
            kg_per_unit = _VOLUME_TO_L[self.unit] * density_g_per_cm3
        else:
            kg_per_unit = factor
        return self.amount / kg_per_unit


# Mass units: how many kg does one unit represent?  `None` means volumetric.
_UNIT_TO_KG: dict[str, float | None] = {
    "kg": 1.0,
    "g": 1e-3,
    "t": 1_000.0,
    "l": None,
    "ml": None,
    "m3": None,
}
_VOLUME_TO_L: dict[str, float] = {
    "l": 1.0,
    "ml": 1e-3,
    "m3": 1_000.0,
}


__all__ = ["InvalidPriceError", "Price"]
