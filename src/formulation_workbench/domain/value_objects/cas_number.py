"""CAS Registry Number value object.

CAS (Chemical Abstracts Service) Registry Numbers are universally recognized
identifiers for chemical substances. Format: XXXXXX-XX-X where:
- Up to 7 digits
- Two hyphens
- Single check digit at the end

The check digit is calculated by multiplying each digit (right-to-left, starting from 2)
and summing the products modulo 10.

Example: 7732-18-5 (water) → digits 7,7,3,2,1,8 → weights 6,5,4,3,2,1
   → 7*6 + 7*5 + 3*4 + 2*3 + 1*2 + 8*1 = 42+35+12+6+2+8 = 105 → 105 mod 10 = 5 ✓

References:
    - https://www.cas.org/support/documentation/chemical-substances/check-digit
    - ASTM E1189 — Standard Terminology for CAS Registry Numbers
"""

from __future__ import annotations

import re
from dataclasses import dataclass


class InvalidCasNumberError(ValueError):
    """Raised when CAS number format or checksum is invalid."""


@dataclass(frozen=True, slots=True)
class CasNumber:
    """CAS Registry Number value object.

    Immutable. Validates format and checksum on construction.
    """

    value: str

    PATTERN: re.Pattern[str] = re.compile(r"^\d{2,7}-\d{2}-\d$")

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise InvalidCasNumberError(
                f"CAS number must be a string, got {type(self.value).__name__}"
            )

        # Normalize: strip whitespace
        normalized = self.value.strip()

        if not self.PATTERN.match(normalized):
            raise InvalidCasNumberError(
                f"Invalid CAS number format: '{self.value}'. "
                f"Expected format: XXXXXX-XX-X (e.g., 7732-18-5)"
            )

        if not self._is_valid_checksum(normalized):
            raise InvalidCasNumberError(
                f"Invalid CAS number checksum: '{self.value}'. "
                f"The check digit does not match the calculated value."
            )

        # Freeze normalized value
        object.__setattr__(self, "value", normalized)

    @staticmethod
    def _is_valid_checksum(cas: str) -> bool:
        """Validate the CAS check digit.

        The check digit is calculated by taking the digits preceding the
        check digit, multiplying each by its position (starting from 1 at
        the rightmost digit before the check), summing, and taking mod 10.
        """
        # Strip hyphens, get the check digit (last char) and the rest
        digits_only = cas.replace("-", "")
        check_digit = int(digits_only[-1])
        digits = digits_only[:-1]

        # Multiply each digit by its position (right-to-left starting from 1)
        total = sum(int(digit) * (index + 1) for index, digit in enumerate(reversed(digits)))

        return total % 10 == check_digit

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return f"CasNumber('{self.value}')"

    @classmethod
    def try_parse(cls, value: str) -> CasNumber | None:
        """Try to parse a CAS number, returning None on failure instead of raising."""
        try:
            return cls(value)
        except InvalidCasNumberError:
            return None
