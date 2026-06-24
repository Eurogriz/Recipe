"""Mass Percent value object.

Represents a mass percentage (0..100) with optional tolerance.
Used for composition specifications in recipes.

Example: MassPercent(50.5, tolerance_percent=1.5) represents
50.5% ± 1.5%, i.e., a valid range of [49.0%, 52.0%].
"""

from __future__ import annotations

from dataclasses import dataclass


class InvalidMassPercentError(ValueError):
    """Raised when mass percent is outside [0, 100] range."""


@dataclass(frozen=True, slots=True)
class MassPercent:
    """Mass percentage with optional tolerance, all in mass-% units.

    Invariants:
        - 0.0 <= value <= 100.0
        - 0.0 <= tolerance_percent <= 100.0
        - min_value = max(0, value - tolerance) >= 0
        - max_value = min(100, value + tolerance) <= 100
    """

    value: float
    tolerance_percent: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.value, (int, float)):
            raise InvalidMassPercentError(
                f"Mass percent value must be numeric, got {type(self.value).__name__}"
            )
        if not isinstance(self.tolerance_percent, (int, float)):
            raise InvalidMassPercentError(
                f"Tolerance must be numeric, got {type(self.tolerance_percent).__name__}"
            )

        if not 0.0 <= float(self.value) <= 100.0:
            raise InvalidMassPercentError(
                f"Mass percent must be in [0, 100], got {self.value}"
            )

        if not 0.0 <= float(self.tolerance_percent) <= 100.0:
            raise InvalidMassPercentError(
                f"Tolerance must be in [0, 100], got {self.tolerance_percent}"
            )

        # Cast to float to ensure immutability consistency
        object.__setattr__(self, "value", float(self.value))
        object.__setattr__(self, "tolerance_percent", float(self.tolerance_percent))

    @property
    def min_value(self) -> float:
        """Minimum value within tolerance."""
        return max(0.0, self.value - self.tolerance_percent)

    @property
    def max_value(self) -> float:
        """Maximum value within tolerance."""
        return min(100.0, self.value + self.tolerance_percent)

    @property
    def range(self) -> tuple[float, float]:
        """Tuple of (min, max) within tolerance."""
        return (self.min_value, self.max_value)

    def contains(self, other_value: float) -> bool:
        """Check if a value falls within the tolerance range."""
        return self.min_value <= other_value <= self.max_value

    @classmethod
    def zero(cls) -> MassPercent:
        """0% with no tolerance (useful for trace components like biocides)."""
        return cls(0.0, 0.0)

    def __str__(self) -> str:
        if self.tolerance_percent > 0:
            return f"{self.value:.2f}% ± {self.tolerance_percent:.2f}%"
        return f"{self.value:.2f}%"

    def __repr__(self) -> str:
        return f"MassPercent({self.value}, tolerance={self.tolerance_percent})"
