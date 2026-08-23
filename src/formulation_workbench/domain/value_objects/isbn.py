"""ISBN (International Standard Book Number) value object.

Supports both ISBN-10 (legacy, 10 digits with possible 'X' check) and
ISBN-13 (modern, EAN-13 compatible). Normalizes to ISBN-13 when possible.

References:
    - ISO 2108 — Information and documentation — International Standard Book Number
"""

from __future__ import annotations

import re
from dataclasses import dataclass


class InvalidIsbnError(ValueError):
    """Raised when ISBN format or checksum is invalid."""


@dataclass(frozen=True, slots=True)
class Isbn:
    """ISBN value object. Auto-detects ISBN-10 or ISBN-13, normalizes hyphens/spaces.

    Examples of valid ISBNs:
        - ISBN-10: 0-8155-1377-2 (Flick, Water-Based Paint Formulations Vol. 3)
        - ISBN-13: 978-0-8155-1377-3

    After construction, `.value` is always the canonical form (no hyphens).
    """

    value: str
    variant: str = ""  # populated in __post_init__: "ISBN-10" or "ISBN-13"

    _ISBN10_PATTERN: re.Pattern[str] = re.compile(r"^\d{9}[\dX]$")
    _ISBN13_PATTERN: re.Pattern[str] = re.compile(r"^\d{13}$")
    _RAW_PATTERN: re.Pattern[str] = re.compile(r"^[\dX]{10}$|^[\dX]{13}$")

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise InvalidIsbnError(f"ISBN must be a string, got {type(self.value).__name__}")

        # Strip hyphens and spaces
        normalized = re.sub(r"[\s-]", "", self.value).upper()

        if not self._RAW_PATTERN.match(normalized):
            raise InvalidIsbnError(
                f"Invalid ISBN format: '{self.value}'. "
                f"Expected ISBN-10 (10 digits/X) or ISBN-13 (13 digits)."
            )

        if len(normalized) == 10:
            if not self._is_valid_isbn10(normalized):
                raise InvalidIsbnError(f"Invalid ISBN-10 checksum: '{self.value}'")
            object.__setattr__(self, "variant", "ISBN-10")
            # Keep ISBN-10 as-is for display; user can convert if needed
            object.__setattr__(self, "value", normalized)
        else:  # 13 digits
            if not self._is_valid_isbn13(normalized):
                raise InvalidIsbnError(f"Invalid ISBN-13 checksum: '{self.value}'")
            object.__setattr__(self, "variant", "ISBN-13")
            object.__setattr__(self, "value", normalized)

    @staticmethod
    def _is_valid_isbn10(isbn: str) -> bool:
        """Validate ISBN-10 checksum.

        Sum of (digit * position) where position goes from 10 to 2,
        plus check digit * 1, must be divisible by 11.
        Check digit can be 'X' (representing 10).
        """
        total = 0
        for i, char in enumerate(isbn):
            digit = 10 if char == "X" else int(char)
            weight = 10 - i
            total += digit * weight
        return total % 11 == 0

    @staticmethod
    def _is_valid_isbn13(isbn: str) -> bool:
        """Validate ISBN-13 checksum (EAN-13 algorithm).

        Alternating weights of 1 and 3 from left to right, sum mod 10 = 0.
        """
        total = 0
        for i, char in enumerate(isbn):
            digit = int(char)
            weight = 1 if i % 2 == 0 else 3
            total += digit * weight
        return total % 10 == 0

    def to_isbn13(self) -> Isbn:
        """Convert ISBN-10 to ISBN-13 (prefix 978, recalculate check digit)."""
        if self.variant == "ISBN-13":
            return self

        # ISBN-10 → ISBN-13: prepend 978, drop original check digit, recalculate
        body = "978" + self.value[:9]
        check = self._calculate_isbn13_check(body)
        new_isbn13 = body + str(check)
        return Isbn(new_isbn13)

    @staticmethod
    def _calculate_isbn13_check(twelve_digits: str) -> int:
        """Calculate the ISBN-13 check digit."""
        total = 0
        for i, char in enumerate(twelve_digits):
            digit = int(char)
            weight = 1 if i % 2 == 0 else 3
            total += digit * weight
        return (10 - (total % 10)) % 10

    def formatted(self) -> str:
        """Return ISBN formatted with hyphens (978-0-8155-1377-3 format)."""
        if self.variant == "ISBN-13":
            return f"{self.value[0:3]}-{self.value[3]}-{self.value[4:8]}-{self.value[8:12]}-{self.value[12]}"
        # ISBN-10
        return f"{self.value[0]}-{self.value[1:4]}-{self.value[4:9]}-{self.value[9]}"

    def __str__(self) -> str:
        return self.formatted()

    def __repr__(self) -> str:
        return f"Isbn('{self.formatted()}', variant='{self.variant}')"
