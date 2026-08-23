"""DOI (Digital Object Identifier) value object.

DOI format: 10.NNNN/anything
Example: 10.1000/xyz123

The prefix "10." is mandatory; the registrant code (NNNN) is 4+ digits;
the suffix can be anything alphanumeric with various separators.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


class InvalidDoiError(ValueError):
    """Raised when DOI format is invalid."""


@dataclass(frozen=True, slots=True)
class Doi:
    """DOI value object.

    Validates format: 10.REGISTRANT/SUFFIX where REGISTRANT is 4+ digits.
    """

    value: str

    _PATTERN: re.Pattern[str] = re.compile(r"^10\.\d{4,9}/[^\s]+$")

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise InvalidDoiError(f"DOI must be a string, got {type(self.value).__name__}")

        normalized = self.value.strip()

        if not self._PATTERN.match(normalized):
            raise InvalidDoiError(
                f"Invalid DOI format: '{self.value}'. "
                f"Expected format: 10.NNNN/anything (e.g., 10.1000/xyz123)"
            )

        object.__setattr__(self, "value", normalized)

    @property
    def url(self) -> str:
        """Resolvable URL via doi.org."""
        return f"https://doi.org/{self.value}"

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return f"Doi('{self.value}')"

    @classmethod
    def try_parse(cls, value: str) -> Doi | None:
        """Try to parse a DOI, returning None on failure."""
        try:
            return cls(value)
        except InvalidDoiError:
            return None
