"""Tests for the RawMaterial aggregate."""

from __future__ import annotations

import pytest

from formulation_workbench.domain.entities.raw_material import (
    InvalidRawMaterialError,
    RawMaterial,
    SupplierReference,
)
from formulation_workbench.domain.value_objects.functions import ComponentFunction
from formulation_workbench.domain.value_objects.physical_properties import PhysicalProperties


def test_minimum_raw_material_ok() -> None:
    rm = RawMaterial(name="Water")
    assert rm.name == "Water"
    assert rm.cas_number == "unspecified"
    assert rm.function is ComponentFunction.UNSPECIFIED
    assert rm.properties.density_g_per_cm3 is None


def test_valid_cas_normalises() -> None:
    rm = RawMaterial(name="Titanium dioxide", cas_number="13463-67-7")
    assert rm.cas_number == "13463-67-7"


def test_mixture_and_proprietary_accepted() -> None:
    for token in ("mixture", "proprietary"):
        rm = RawMaterial(name="Blend", cas_number=token)
        assert rm.cas_number == token


def test_invalid_cas_rejected() -> None:
    from formulation_workbench.domain.value_objects.cas_number import InvalidCasNumberError

    with pytest.raises(InvalidCasNumberError):
        RawMaterial(name="Bad CAS", cas_number="abc-def-g")


def test_empty_name_rejected() -> None:
    with pytest.raises(InvalidRawMaterialError):
        RawMaterial(name="   ")


def test_deprecated_requires_replacement() -> None:
    with pytest.raises(InvalidRawMaterialError):
        RawMaterial(name="Old", deprecated=True)


def test_deprecate_method_returns_new_instance() -> None:
    rm = RawMaterial(name="Old")
    replaced = rm.deprecate(replacement_id="abc-def")
    assert replaced.deprecated is True
    assert replaced.replacement_id == "abc-def"
    assert rm.deprecated is False  # original untouched


def test_with_properties_returns_new_instance() -> None:
    rm = RawMaterial(name="TiO2", cas_number="13463-67-7", function=ComponentFunction.PIGMENT)
    props = PhysicalProperties(density_g_per_cm3=4.23, oil_absorption_g_per_100g=18.0)
    updated = rm.with_properties(props)
    assert updated.properties.density_g_per_cm3 == 4.23
    assert rm.properties.density_g_per_cm3 is None


def test_supplier_reference_requires_name() -> None:
    with pytest.raises(ValueError):
        SupplierReference(supplier_name="   ")


def test_equality_by_id() -> None:
    rm1 = RawMaterial(id="same", name="A")
    rm2 = RawMaterial(id="same", name="B")
    assert rm1 == rm2
    assert hash(rm1) == hash(rm2)
