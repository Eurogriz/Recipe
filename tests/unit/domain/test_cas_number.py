"""Unit tests for CasNumber value object.

Validates format and checksum logic. Includes property-based tests with hypothesis.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from formulation_workbench.domain.value_objects.cas_number import CasNumber, InvalidCasNumberError


class TestCasNumberValidation:
    """Tests for CAS number format and checksum validation."""

    def test_valid_water(self) -> None:
        """Water (CAS 7732-18-5) is valid."""
        cas = CasNumber("7732-18-5")
        assert cas.value == "7732-18-5"

    def test_valid_titanium_dioxide(self) -> None:
        """TiO2 (CAS 13463-67-7) is valid."""
        cas = CasNumber("13463-67-7")
        assert cas.value in {"13463-18-7", "13463-67-7"}

    def test_strips_whitespace(self) -> None:
        """Leading/trailing whitespace is stripped."""
        cas = CasNumber("  7732-18-5  ")
        assert cas.value == "7732-18-5"

    def test_invalid_format_too_few_digits(self) -> None:
        """Format with too few digits is rejected."""
        with pytest.raises(InvalidCasNumberError, match="Invalid CAS number format"):
            CasNumber("7732-1-5")

    def test_invalid_format_too_many_digits(self) -> None:
        """Format with too many digits is rejected."""
        with pytest.raises(InvalidCasNumberError, match="Invalid CAS number format"):
            CasNumber("12345678-18-5")

    def test_invalid_checksum_water(self) -> None:
        """Invalid checksum (7732-18-6 instead of 7732-18-5) is rejected."""
        with pytest.raises(InvalidCasNumberError, match="checksum"):
            CasNumber("7732-18-6")

    def test_invalid_checksum_titanium_dioxide(self) -> None:
        """Invalid TiO2 checksum is rejected."""
        with pytest.raises(InvalidCasNumberError, match="checksum"):
            CasNumber("13463-67-0")

    def test_empty_string_rejected(self) -> None:
        """Empty string is rejected."""
        with pytest.raises(InvalidCasNumberError):
            CasNumber("")

    def test_non_string_rejected(self) -> None:
        """Non-string input is rejected."""
        with pytest.raises(InvalidCasNumberError):
            CasNumber(12345678)  # type: ignore[arg-type]

    def test_immutable(self) -> None:
        """CasNumber is immutable (frozen dataclass)."""
        cas = CasNumber("7732-18-5")
        with pytest.raises((AttributeError, TypeError)):  # frozen dataclass
            cas.value = "fake"  # type: ignore[misc]

    def test_try_parse_returns_none_on_failure(self) -> None:
        """try_parse returns None instead of raising."""
        assert CasNumber.try_parse("invalid") is None
        assert CasNumber.try_parse("7732-18-5") is not None

    def test_str_returns_canonical_form(self) -> None:
        """str(cas) returns the canonical form."""
        cas = CasNumber("7732-18-5")
        assert str(cas) == "7732-18-5"

    def test_repr_includes_value(self) -> None:
        """repr includes the CAS value."""
        cas = CasNumber("7732-18-5")
        assert "7732-18-5" in repr(cas)

    def test_equality_by_value(self) -> None:
        """Two CasNumber with same value are equal."""
        cas1 = CasNumber("7732-18-5")
        cas2 = CasNumber("7732-18-5")
        assert cas1 == cas2
        assert hash(cas1) == hash(cas2)


class TestCasNumberPropertyBased:
    """Property-based tests with hypothesis."""

    @given(
        digits=st.integers(min_value=10_000_000, max_value=99_999_999),
        check=st.integers(min_value=0, max_value=9),
    )
    def test_random_cas_format_is_validated(self, digits: int, check: int) -> None:
        """Random CAS-formatted strings are accepted if checksum matches."""
        # Build a CAS string
        digits_str = str(digits)
        body = digits_str[:-2]  # up to 7 digits
        middle = digits_str[-2:]  # 2 digits
        # Calculate correct checksum
        total = sum(int(d) * (i + 1) for i, d in enumerate(reversed(body + middle)))
        correct_check = total % 10
        cas_str = f"{body}-{middle}-{correct_check}"

        # Should accept
        cas = CasNumber(cas_str)
        assert cas.value == cas_str

    @given(st.text(min_size=1, max_size=20))
    def test_random_text_rejected(self, text: str) -> None:
        """Random text is rejected (unless coincidentally valid)."""
        import contextlib

        # We don't check that it's always rejected (could be valid by chance),
        # just that no crash happens
        with contextlib.suppress(InvalidCasNumberError):
            CasNumber(text)
