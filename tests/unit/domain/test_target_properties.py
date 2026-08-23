"""Tests for the TargetSpecification / property catalogue."""

from __future__ import annotations

import pytest

from formulation_workbench.domain.value_objects import target_properties as _tp

PropertyCategory = _tp.PropertyCategory
PropertyDefinition = _tp.PropertyDefinition
TargetSpecification = _tp.TargetSpecification
_TestMethod = _tp.TestMethod  # aliased so pytest doesn't collect it as a test class
ToleranceMode = _tp.ToleranceMode
all_properties = _tp.all_properties
property_by_code = _tp.property_by_code


class TestCatalogue:
    def test_catalogue_covers_all_categories(self) -> None:
        props = all_properties()
        covered = {p.category for p in props}
        assert covered == set(PropertyCategory), "Every category should have at least one property"

    def test_catalogue_has_at_least_40_properties(self) -> None:
        # Contract: we promise "40+ property library" in the changelog.
        assert len(all_properties()) >= 40

    def test_property_codes_are_unique(self) -> None:
        codes = [p.code for p in all_properties()]
        assert len(codes) == len(set(codes))

    def test_lookup_by_code(self) -> None:
        p = property_by_code("gloss_60")
        assert p is not None
        assert p.category is PropertyCategory.OPTICAL
        assert p.default_unit == "GU"

    def test_missing_code_returns_none(self) -> None:
        assert property_by_code("nope") is None


class TestPropertyDefinition:
    def test_code_must_be_snake_case(self) -> None:
        with pytest.raises(ValueError):
            PropertyDefinition(
                code="Gloss60",
                display_name="X",
                category=PropertyCategory.OPTICAL,
                default_unit="GU",
            )


class TestToleranceModes:
    def test_absolute_within_tolerance(self) -> None:
        spec = TargetSpecification(property_code="gloss_60", target_value=80.0, tolerance=5.0)
        assert spec.is_satisfied_by(78.0)
        assert not spec.is_satisfied_by(90.0)

    def test_percent_mode(self) -> None:
        spec = TargetSpecification(
            property_code="viscosity_mid_shear",
            target_value=1000.0,
            tolerance=10.0,
            tolerance_mode=ToleranceMode.PERCENT,
        )
        assert spec.is_satisfied_by(1080.0)
        assert not spec.is_satisfied_by(1200.0)

    def test_min_mode(self) -> None:
        spec = TargetSpecification(
            property_code="pendulum_hardness_konig",
            target_value=90.0,
            tolerance_mode=ToleranceMode.MIN,
        )
        assert spec.is_satisfied_by(100.0)
        assert not spec.is_satisfied_by(80.0)

    def test_max_mode(self) -> None:
        spec = TargetSpecification(
            property_code="voc_content",
            target_value=30.0,
            tolerance_mode=ToleranceMode.MAX,
        )
        assert spec.is_satisfied_by(28.0)
        assert not spec.is_satisfied_by(35.0)

    def test_range_mode(self) -> None:
        spec = TargetSpecification(
            property_code="ph",
            target_value=7.5,
            tolerance=9.0,  # in RANGE mode this is the upper bound
            tolerance_mode=ToleranceMode.RANGE,
        )
        assert spec.is_satisfied_by(8.0)
        assert not spec.is_satisfied_by(10.0)
        assert not spec.is_satisfied_by(7.0)


class TestTestMethodVO:
    def test_empty_standard_rejected(self) -> None:
        with pytest.raises(ValueError):
            _TestMethod(standard="   ")

    def test_has_unit(self) -> None:
        m = _TestMethod(standard="ISO 2813", unit="GU")
        assert m.unit == "GU"
