"""Recipe / experiment factories used across qualification tests."""

from __future__ import annotations

from dataclasses import dataclass

from formulation_workbench.domain.entities.experiment import (
    BatchInfo,
    ExperimentRun,
    MeasuredValue,
)
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

from .ground_truth import LabMeasurements, measure

_CITATION = Citation(
    authors="Flick",
    title="Water-Based Paint Formulations",
    year=1995,
    publisher="Noyes Publications",
    isbn=Isbn("9780815513773"),
)

_COMPONENT_META = {
    "Water": {"cas_number": "7732-18-5", "function": "vehicle", "role": ComponentFunction.VEHICLE},
    "Acrylic": {"cas_number": "mixture", "function": "binder", "role": ComponentFunction.BINDER},
    "PU resin": {"cas_number": "mixture", "function": "binder", "role": ComponentFunction.BINDER},
    "TiO2": {"cas_number": "13463-67-7", "function": "pigment", "role": ComponentFunction.PIGMENT},
    "CaCO3": {
        "cas_number": "1317-65-3",
        "function": "extender",
        "role": ComponentFunction.EXTENDER,
    },
    "Talc": {
        "cas_number": "14807-96-6",
        "function": "extender",
        "role": ComponentFunction.EXTENDER,
    },
    "Texanol": {
        "cas_number": "25265-77-4",
        "function": "coalescent",
        "role": ComponentFunction.COALESCENT,
    },
    "Xylene": {"cas_number": "1330-20-7", "function": "solvent", "role": ComponentFunction.SOLVENT},
    "Rheo": {
        "cas_number": "proprietary",
        "function": "rheology_modifier",
        "role": ComponentFunction.RHEOLOGY_MODIFIER,
    },
    "PG": {"cas_number": "57-55-6", "function": "antifreeze", "role": ComponentFunction.ANTIFREEZE},
    "Kathon": {
        "cas_number": "26172-55-4",
        "function": "biocide",
        "role": ComponentFunction.IN_CAN_BIOCIDE,
    },
    "Dispex": {
        "cas_number": "9003-04-7",
        "function": "dispersant",
        "role": ComponentFunction.DISPERSANT,
    },
    "Foamex": {
        "cas_number": "63148-62-9",
        "function": "defoamer",
        "role": ComponentFunction.DEFOAMER,
    },
}


@dataclass(frozen=True, slots=True)
class RecipeSpec:
    """Convenience: named-component → mass %."""

    mass_percent: dict[str, float]
    category: str = "Краски"
    subcategory: str = "Водно-дисперсионные"
    binder_type: str = "Acrylic"
    product_class: ProductClass = ProductClass.STANDARD
    intended_use: str = "Test formulation"
    recipe_id: str | None = None


def build_recipe(spec: RecipeSpec) -> Recipe:
    """Turn a ``{name → mass %}`` dict into a fully-valid Recipe."""
    total = sum(spec.mass_percent.values())
    if abs(total - 100.0) > 0.5:
        raise ValueError(f"mass_percent must sum to 100 (±0.5), got {total:.2f}")

    components: list[Component] = []
    for name, mass in spec.mass_percent.items():
        meta = _COMPONENT_META.get(name)
        if meta is None:
            raise KeyError(f"unknown component {name!r}; extend _COMPONENT_META")
        components.append(
            Component(
                name=name,
                cas_number=meta["cas_number"],
                function=meta["function"],
                mass_percent=mass,
                functional_role=meta["role"],
            )
        )
    return Recipe(
        id=spec.recipe_id,
        category=spec.category,
        subcategory=spec.subcategory,
        binder_type=spec.binder_type,
        product_class=spec.product_class,
        intended_use=spec.intended_use,
        stages=(
            CompositionStage(
                stage_number=1,
                name="Mix",
                description="Auto-generated qualification recipe",
                components=tuple(components),
                process=ProcessParams(equipment="Disperser"),
            ),
        ),
        primary_source=_CITATION,
    )


def completed_experiment(
    recipe: Recipe,
    measurements: LabMeasurements,
    *,
    batch_number: str = "B-QUAL",
    version: int = 1,
) -> ExperimentRun:
    """A completed :class:`ExperimentRun` carrying the ground-truth values."""
    return (
        ExperimentRun(
            recipe_id=recipe.id,
            recipe_version=version,
            title="Qualification run",
            operator="benchmark",
        )
        .start()
        .complete(
            BatchInfo(batch_number=batch_number, target_mass_kg=5.0),
            (
                MeasuredValue(property_code="gloss_60", value=measurements.gloss_60),
                MeasuredValue(
                    property_code="hiding_power", value=measurements.hiding_power_m2_per_l
                ),
                MeasuredValue(
                    property_code="viscosity_mid_shear", value=measurements.viscosity_mid_shear
                ),
                MeasuredValue(property_code="voc_content", value=measurements.voc_content),
            ),
        )
    )


def measure_recipe(spec: RecipeSpec, *, seed: int | None = None) -> LabMeasurements:
    return measure(spec.mass_percent, seed=seed)


__all__ = ["RecipeSpec", "build_recipe", "completed_experiment", "measure_recipe"]
