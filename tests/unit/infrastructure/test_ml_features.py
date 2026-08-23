"""Unit tests for the ML feature extractor."""

from __future__ import annotations

from formulation_workbench.domain.entities.recipe import (
    Component,
    CompositionStage,
    ProcessParams,
    ProductClass,
    Recipe,
)
from formulation_workbench.domain.value_objects.citation import Citation
from formulation_workbench.domain.value_objects.functions import ComponentFunction
from formulation_workbench.domain.value_objects.isbn import Isbn
from formulation_workbench.domain.value_objects.physical_properties import PhysicalProperties
from formulation_workbench.infrastructure.ml.features import (
    FEATURE_NAMES,
    extract_features,
    to_vector,
)


def _cite() -> Citation:
    return Citation(
        authors="Flick",
        title="WBPF",
        year=1995,
        publisher="Noyes Publications",
        isbn=Isbn("9780815513773"),
    )


def _recipe(components: list[Component]) -> Recipe:
    return Recipe(
        category="Краски",
        subcategory="Водно-дисперсионные",
        binder_type="Acrylic",
        product_class=ProductClass.STANDARD,
        intended_use="Test",
        stages=(
            CompositionStage(
                stage_number=1,
                name="Mix",
                description="",
                components=tuple(components),
                process=ProcessParams(equipment="Disperser"),
            ),
        ),
        primary_source=_cite(),
    )


def _c(name, role, mass, *, density=None, tg=None, voc=None, cas="mixture"):  # type: ignore[no-untyped-def]
    props = None
    if any(x is not None for x in (density, tg, voc)):
        props = PhysicalProperties(
            density_g_per_cm3=density,
            glass_transition_c=tg,
            voc_fraction=voc,
        )
    return Component(
        name=name,
        cas_number=cas,
        function=role.value,
        mass_percent=mass,
        functional_role=role,
        properties=props,
    )


def test_feature_names_are_stable_and_deterministic() -> None:
    assert len(FEATURE_NAMES) == len(set(FEATURE_NAMES))
    for expected in (
        "mass_percent_binder",
        "mass_percent_pigment",
        "sum_pigment_percent",
        "weighted_density",
        "weighted_tg",
        "voc_component_fraction",
        "stage_count",
        "component_count",
    ):
        assert expected in FEATURE_NAMES


def test_extract_simple_recipe() -> None:
    recipe = _recipe(
        [
            _c("Water", ComponentFunction.VEHICLE, 50.0, density=1.0, cas="7732-18-5"),
            _c("Acrylic", ComponentFunction.BINDER, 40.0, density=1.05, tg=15.0),
            _c("TiO2", ComponentFunction.PIGMENT, 10.0, density=4.23, cas="13463-67-7"),
        ]
    )
    features = extract_features(recipe)
    assert features["mass_percent_vehicle"] == 50.0
    assert features["mass_percent_binder"] == 40.0
    assert features["mass_percent_pigment"] == 10.0
    assert features["sum_pigment_percent"] == 10.0
    # weighted_density = 0.5*1 + 0.4*1.05 + 0.1*4.23 = 1.343
    assert 1.34 <= features["weighted_density"] <= 1.35
    # weighted_tg — binder only, so 15.0
    assert features["weighted_tg"] == 15.0
    assert features["stage_count"] == 1.0
    assert features["component_count"] == 3.0


def test_missing_properties_default_to_zero() -> None:
    recipe = _recipe(
        [
            _c("Water", ComponentFunction.VEHICLE, 50.0, cas="7732-18-5"),
            _c("Acrylic", ComponentFunction.BINDER, 50.0),
        ]
    )
    features = extract_features(recipe)
    assert features["weighted_density"] == 0.0
    assert features["weighted_tg"] == 0.0
    assert features["voc_component_fraction"] == 0.0


def test_to_vector_shape() -> None:
    recipe = _recipe(
        [
            _c("Water", ComponentFunction.VEHICLE, 60.0, cas="7732-18-5"),
            _c("Acrylic", ComponentFunction.BINDER, 40.0),
        ]
    )
    vec = to_vector(recipe)
    assert len(vec) == len(FEATURE_NAMES)
    assert all(isinstance(v, float) for v in vec)
