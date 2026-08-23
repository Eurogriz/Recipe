"""Catalogue of target properties, test methods, and acceptance criteria.

A recipe is only complete once we've captured *what it must achieve*
in the lab.  This module gives that surface first-class status:

- :class:`PropertyCategory` groups the 40+ properties into optical /
  mechanical / rheological / … buckets.
- :class:`TestMethod` records the standard (ГОСТ / ASTM / ISO / DIN)
  under which a property is measured, plus the reporting unit.
- :class:`TargetSpecification` is what a customer / QC actually cares
  about — a target value with a tolerance and a test method.

A recipe carries a tuple of :class:`TargetSpecification` values; the
verification-rules layer refuses to promote a Verified recipe unless
each target has a corresponding predicted or measured value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class PropertyCategory(str, Enum):
    OPTICAL = "optical"
    MECHANICAL = "mechanical"
    CHEMICAL = "chemical"
    RHEOLOGICAL = "rheological"
    APPLICATION = "application"
    STABILITY = "stability"
    SAFETY = "safety"
    REGULATORY = "regulatory"


class ToleranceMode(str, Enum):
    ABSOLUTE = "absolute"  # target ± tolerance in the same unit
    PERCENT = "percent"  # target ± (tolerance % of target)
    MIN = "min"  # value >= target
    MAX = "max"  # value <= target
    RANGE = "range"  # min <= value <= max (target is min, tolerance is max)


@dataclass(frozen=True, slots=True)
class TestMethod:
    """A published test method used to measure a property."""

    standard: str  # e.g. "ISO 2813", "ГОСТ 896-69"
    title: str = ""
    unit: str = ""  # canonical SI-ish unit, e.g. "%", "N/mm²"
    remarks: str = ""

    def __post_init__(self) -> None:
        if not self.standard or not self.standard.strip():
            raise ValueError("TestMethod.standard must be non-empty")


@dataclass(frozen=True, slots=True)
class PropertyDefinition:
    """Static metadata describing what a property is and how to measure it."""

    code: str  # short id, e.g. "gloss_60"
    display_name: str
    category: PropertyCategory
    default_unit: str
    description: str = ""
    default_test_methods: tuple[TestMethod, ...] = field(default_factory=tuple)
    higher_is_better: bool | None = None  # None if not applicable

    def __post_init__(self) -> None:
        if not re.match(r"^[a-z][a-z0-9_]{1,60}$", self.code):
            raise ValueError(f"Property code must be snake_case: {self.code!r}")


@dataclass(frozen=True, slots=True)
class TargetSpecification:
    """A concrete target for one recipe.

    Combines a :class:`PropertyDefinition`, a target value, a tolerance
    interpretation, and (optionally) a specific test method that
    overrides the property's defaults.
    """

    property_code: str
    target_value: float
    tolerance: float = 0.0
    tolerance_mode: ToleranceMode = ToleranceMode.ABSOLUTE
    unit: str = ""
    method: TestMethod | None = None
    notes: str = ""

    def is_satisfied_by(self, measured_value: float) -> bool:
        """Return True if ``measured_value`` satisfies the spec."""
        if self.tolerance_mode is ToleranceMode.MIN:
            return measured_value >= self.target_value
        if self.tolerance_mode is ToleranceMode.MAX:
            return measured_value <= self.target_value
        if self.tolerance_mode is ToleranceMode.RANGE:
            return self.target_value <= measured_value <= self.tolerance
        if self.tolerance_mode is ToleranceMode.PERCENT:
            delta = abs(self.target_value) * (self.tolerance / 100.0)
        else:  # ABSOLUTE
            delta = self.tolerance
        return abs(measured_value - self.target_value) <= delta


# ==============================================================================
# Curated property catalogue — 40+ properties across every category.
# Sources:
#   * ГОСТ Р ISO / ISO / ASTM standards as cited.
#   * European Coatings Handbook (Vincentz, 2nd ed.) — nomenclature & units.
#   * Manufacturers' technical bulletins (Evonik, BASF, Byk-Chemie).
# ==============================================================================


def _m(standard: str, title: str, unit: str = "", remarks: str = "") -> TestMethod:
    return TestMethod(standard=standard, title=title, unit=unit, remarks=remarks)


_PROPERTIES: tuple[PropertyDefinition, ...] = (
    # -------- OPTICAL --------
    PropertyDefinition(
        code="gloss_20",
        display_name="Gloss at 20°",
        category=PropertyCategory.OPTICAL,
        default_unit="GU",
        default_test_methods=(_m("ISO 2813", "Determination of gloss", "GU"),),
        higher_is_better=True,
    ),
    PropertyDefinition(
        code="gloss_60",
        display_name="Gloss at 60°",
        category=PropertyCategory.OPTICAL,
        default_unit="GU",
        default_test_methods=(
            _m("ISO 2813", "Determination of gloss", "GU"),
            _m("ГОСТ 896-69", "Определение блеска"),
        ),
        higher_is_better=True,
    ),
    PropertyDefinition(
        code="gloss_85",
        display_name="Gloss at 85°",
        category=PropertyCategory.OPTICAL,
        default_unit="GU",
        default_test_methods=(_m("ISO 2813", "Determination of gloss"),),
    ),
    PropertyDefinition(
        code="hiding_power",
        display_name="Hiding power (opacity)",
        category=PropertyCategory.OPTICAL,
        default_unit="m²/L",
        default_test_methods=(_m("ISO 6504-3", "Contrast ratio at fixed spread rate"),),
        higher_is_better=True,
    ),
    PropertyDefinition(
        code="contrast_ratio",
        display_name="Contrast ratio",
        category=PropertyCategory.OPTICAL,
        default_unit="ratio",
        default_test_methods=(_m("ISO 6504-3", "Contrast ratio"),),
        higher_is_better=True,
    ),
    PropertyDefinition(
        code="whiteness_cielab_l",
        display_name="Whiteness L* (CIELAB)",
        category=PropertyCategory.OPTICAL,
        default_unit="L*",
        default_test_methods=(_m("ISO 11664-4", "Colorimetry — CIELAB"),),
    ),
    PropertyDefinition(
        code="delta_e_cielab",
        display_name="Colour deviation ΔE (CIELAB)",
        category=PropertyCategory.OPTICAL,
        default_unit="ΔE",
        default_test_methods=(
            _m("ASTM D2244", "Calculation of colour tolerances and colour differences"),
        ),
        higher_is_better=False,
    ),
    PropertyDefinition(
        code="yellowness_index",
        display_name="Yellowness index",
        category=PropertyCategory.OPTICAL,
        default_unit="YI",
        default_test_methods=(_m("ASTM E313", "Yellowness index from spectral reflectance"),),
        higher_is_better=False,
    ),
    # -------- MECHANICAL --------
    PropertyDefinition(
        code="pendulum_hardness_persoz",
        display_name="Pendulum hardness (Persoz)",
        category=PropertyCategory.MECHANICAL,
        default_unit="s",
        default_test_methods=(_m("ISO 1522", "Pendulum damping test — Persoz"),),
        higher_is_better=True,
    ),
    PropertyDefinition(
        code="pendulum_hardness_konig",
        display_name="Pendulum hardness (König)",
        category=PropertyCategory.MECHANICAL,
        default_unit="s",
        default_test_methods=(_m("ISO 1522", "Pendulum damping test — König"),),
        higher_is_better=True,
    ),
    PropertyDefinition(
        code="pencil_hardness",
        display_name="Pencil hardness",
        category=PropertyCategory.MECHANICAL,
        default_unit="grade",
        default_test_methods=(_m("ISO 15184", "Pencil hardness"),),
    ),
    PropertyDefinition(
        code="impact_resistance",
        display_name="Impact resistance",
        category=PropertyCategory.MECHANICAL,
        default_unit="N·m",
        default_test_methods=(_m("ISO 6272-1", "Falling-weight impact"),),
        higher_is_better=True,
    ),
    PropertyDefinition(
        code="flexibility_erichsen",
        display_name="Flexibility (Erichsen indentation)",
        category=PropertyCategory.MECHANICAL,
        default_unit="mm",
        default_test_methods=(_m("ISO 1520", "Erichsen cupping test"),),
        higher_is_better=True,
    ),
    PropertyDefinition(
        code="adhesion_crosscut",
        display_name="Adhesion — cross-cut",
        category=PropertyCategory.MECHANICAL,
        default_unit="class",
        default_test_methods=(_m("ISO 2409", "Cross-cut test"),),
        higher_is_better=False,  # class 0 is best
    ),
    PropertyDefinition(
        code="adhesion_pull_off",
        display_name="Adhesion — pull-off",
        category=PropertyCategory.MECHANICAL,
        default_unit="MPa",
        default_test_methods=(_m("ISO 4624", "Pull-off test for adhesion"),),
        higher_is_better=True,
    ),
    PropertyDefinition(
        code="abrasion_taber",
        display_name="Abrasion resistance (Taber)",
        category=PropertyCategory.MECHANICAL,
        default_unit="mg/1000 cycles",
        default_test_methods=(_m("ISO 7784-2", "Abrasion resistance — Taber"),),
        higher_is_better=False,
    ),
    PropertyDefinition(
        code="scrub_resistance",
        display_name="Scrub resistance",
        category=PropertyCategory.MECHANICAL,
        default_unit="cycles",
        default_test_methods=(_m("ISO 11998", "Wet scrub resistance"),),
        higher_is_better=True,
    ),
    # -------- CHEMICAL --------
    PropertyDefinition(
        code="water_resistance",
        display_name="Water resistance",
        category=PropertyCategory.CHEMICAL,
        default_unit="h",
        default_test_methods=(_m("ISO 2812-1", "Immersion in liquid"),),
        higher_is_better=True,
    ),
    PropertyDefinition(
        code="chemical_resistance",
        display_name="Chemical resistance",
        category=PropertyCategory.CHEMICAL,
        default_unit="rating",
        default_test_methods=(_m("ISO 2812-1", "Immersion in liquid"),),
    ),
    PropertyDefinition(
        code="salt_spray_resistance",
        display_name="Salt spray resistance",
        category=PropertyCategory.CHEMICAL,
        default_unit="h",
        default_test_methods=(_m("ISO 9227", "Salt spray tests"),),
        higher_is_better=True,
    ),
    PropertyDefinition(
        code="humidity_resistance",
        display_name="Humidity resistance",
        category=PropertyCategory.CHEMICAL,
        default_unit="h",
        default_test_methods=(_m("ISO 6270-2", "Determination of resistance to humidity"),),
        higher_is_better=True,
    ),
    PropertyDefinition(
        code="weathering_qu_v",
        display_name="Accelerated weathering (QUV)",
        category=PropertyCategory.CHEMICAL,
        default_unit="h",
        default_test_methods=(_m("ISO 16474-3", "Accelerated ageing — fluorescent UV lamps"),),
        higher_is_better=True,
    ),
    # -------- RHEOLOGICAL --------
    PropertyDefinition(
        code="viscosity_low_shear",
        display_name="Viscosity (low shear, 0.1 s⁻¹)",
        category=PropertyCategory.RHEOLOGICAL,
        default_unit="mPa·s",
        default_test_methods=(_m("ISO 2555", "Brookfield viscometer"),),
    ),
    PropertyDefinition(
        code="viscosity_mid_shear",
        display_name="Viscosity (mid shear, 10 s⁻¹)",
        category=PropertyCategory.RHEOLOGICAL,
        default_unit="mPa·s",
        default_test_methods=(_m("ISO 3219", "Cone-and-plate viscometer"),),
    ),
    PropertyDefinition(
        code="viscosity_high_shear",
        display_name="Viscosity (high shear, 10 000 s⁻¹, ICI)",
        category=PropertyCategory.RHEOLOGICAL,
        default_unit="P",
        default_test_methods=(_m("ISO 2884-1", "Cone-plate for coatings"),),
    ),
    PropertyDefinition(
        code="thixotropy_index",
        display_name="Thixotropy index",
        category=PropertyCategory.RHEOLOGICAL,
        default_unit="ratio",
    ),
    PropertyDefinition(
        code="ku_stormer",
        display_name="Stormer viscosity (KU)",
        category=PropertyCategory.RHEOLOGICAL,
        default_unit="KU",
        default_test_methods=(_m("ASTM D562", "Stormer-type viscometer"),),
    ),
    PropertyDefinition(
        code="flow_cup_din4",
        display_name="Flow cup DIN 4 mm",
        category=PropertyCategory.RHEOLOGICAL,
        default_unit="s",
        default_test_methods=(_m("ISO 2431", "Flow cup determination"),),
    ),
    # -------- APPLICATION --------
    PropertyDefinition(
        code="drying_time_touch",
        display_name="Drying time — touch",
        category=PropertyCategory.APPLICATION,
        default_unit="min",
        default_test_methods=(_m("ISO 9117-5", "Surface-dry test — cotton ball"),),
        higher_is_better=False,
    ),
    PropertyDefinition(
        code="drying_time_through",
        display_name="Drying time — through",
        category=PropertyCategory.APPLICATION,
        default_unit="h",
        default_test_methods=(_m("ISO 9117-1", "Through-dry — mechanical method"),),
        higher_is_better=False,
    ),
    PropertyDefinition(
        code="minimum_film_forming_temperature",
        display_name="Minimum film forming temperature",
        category=PropertyCategory.APPLICATION,
        default_unit="°C",
        default_test_methods=(_m("ISO 2115", "MFFT determination"),),
    ),
    PropertyDefinition(
        code="dry_film_thickness",
        display_name="Dry film thickness",
        category=PropertyCategory.APPLICATION,
        default_unit="µm",
        default_test_methods=(_m("ISO 2808", "Determination of film thickness"),),
    ),
    PropertyDefinition(
        code="theoretical_coverage",
        display_name="Theoretical coverage",
        category=PropertyCategory.APPLICATION,
        default_unit="m²/L",
        higher_is_better=True,
    ),
    PropertyDefinition(
        code="volume_solids",
        display_name="Volume solids",
        category=PropertyCategory.APPLICATION,
        default_unit="%",
        default_test_methods=(_m("ISO 3233-1", "Volume solids — density method"),),
        higher_is_better=True,
    ),
    PropertyDefinition(
        code="mass_solids",
        display_name="Non-volatile matter (mass %)",
        category=PropertyCategory.APPLICATION,
        default_unit="%",
        default_test_methods=(_m("ISO 3251", "Non-volatile matter"),),
        higher_is_better=True,
    ),
    # -------- STABILITY --------
    PropertyDefinition(
        code="freeze_thaw_cycles",
        display_name="Freeze-thaw stability",
        category=PropertyCategory.STABILITY,
        default_unit="cycles",
        default_test_methods=(_m("ASTM D2243", "Freeze-thaw stability"),),
        higher_is_better=True,
    ),
    PropertyDefinition(
        code="heat_stability_50c_28d",
        display_name="Heat stability (50 °C / 28 d)",
        category=PropertyCategory.STABILITY,
        default_unit="pass/fail",
        default_test_methods=(_m("ISO 7141", "Storage stability at elevated temperature"),),
    ),
    PropertyDefinition(
        code="sedimentation_index",
        display_name="Sedimentation index",
        category=PropertyCategory.STABILITY,
        default_unit="mm",
        higher_is_better=False,
    ),
    PropertyDefinition(
        code="shelf_life_months",
        display_name="Declared shelf life",
        category=PropertyCategory.STABILITY,
        default_unit="months",
        higher_is_better=True,
    ),
    # -------- SAFETY / REGULATORY --------
    PropertyDefinition(
        code="voc_content",
        display_name="VOC content",
        category=PropertyCategory.REGULATORY,
        default_unit="g/L",
        default_test_methods=(_m("ISO 11890-2", "Determination of VOC — GC method"),),
        higher_is_better=False,
    ),
    PropertyDefinition(
        code="flash_point",
        display_name="Flash point",
        category=PropertyCategory.SAFETY,
        default_unit="°C",
        default_test_methods=(_m("ISO 3679", "Closed cup — rapid equilibrium"),),
        higher_is_better=True,
    ),
    PropertyDefinition(
        code="density_paint",
        display_name="Density (finished paint)",
        category=PropertyCategory.APPLICATION,
        default_unit="g/cm³",
        default_test_methods=(_m("ISO 2811-1", "Pyknometer method"),),
    ),
    PropertyDefinition(
        code="ph",
        display_name="pH (water-based only)",
        category=PropertyCategory.APPLICATION,
        default_unit="pH",
        default_test_methods=(_m("ISO 976", "Determination of pH value"),),
    ),
    PropertyDefinition(
        code="reach_compliant",
        display_name="REACH compliance",
        category=PropertyCategory.REGULATORY,
        default_unit="pass/fail",
    ),
    PropertyDefinition(
        code="clp_hazard_class",
        display_name="CLP hazard class",
        category=PropertyCategory.SAFETY,
        default_unit="class",
    ),
)


_BY_CODE: dict[str, PropertyDefinition] = {p.code: p for p in _PROPERTIES}


def property_by_code(code: str) -> PropertyDefinition | None:
    return _BY_CODE.get(code)


def all_properties() -> tuple[PropertyDefinition, ...]:
    return _PROPERTIES


__all__ = [
    "PropertyCategory",
    "PropertyDefinition",
    "TargetSpecification",
    "TestMethod",
    "ToleranceMode",
    "all_properties",
    "property_by_code",
]
