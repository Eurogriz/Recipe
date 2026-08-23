"""Feature extraction: :class:`Recipe` → numeric vector.

The features are chosen so the same model can train across categories
without leaking category-specific dummies (which would inflate the
feature space beyond usefulness given typical dataset sizes of 10^2
runs).

For every function in :class:`ComponentFunction` the extractor emits
``mass_percent_<function>``.  It further emits:

- ``sum_pigment_percent``, ``sum_extender_percent`` — pigment/extender
  totals that drive PVC.
- ``weighted_density`` — Σ(w_i × ρ_i) / 100 when the density is known
  for enough components; NaN handled as 0.
- ``weighted_tg`` — Σ(w_i × Tg_i) restricted to binders that carry a Tg.
- ``voc_component_fraction`` — declared VOC-carrying mass fraction.
- ``stage_count`` — process complexity signal.

Feature names are declarative on the module (:data:`FEATURE_NAMES`) so
scoring code and stored model metadata agree by construction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...domain.value_objects.functions import ComponentFunction

if TYPE_CHECKING:
    from ...domain.entities.recipe import Recipe


_FUNCTION_ORDER: tuple[ComponentFunction, ...] = tuple(ComponentFunction)


FEATURE_NAMES: tuple[str, ...] = (
    *tuple(f"mass_percent_{fn.value}" for fn in _FUNCTION_ORDER),
    "sum_pigment_percent",
    "sum_extender_percent",
    "weighted_density",
    "weighted_tg",
    "voc_component_fraction",
    "stage_count",
    "component_count",
)


def _safe(value: float | None) -> float:
    if value is None:
        return 0.0
    import math

    if math.isnan(value):
        return 0.0
    return float(value)


def extract_features(recipe: Recipe) -> dict[str, float]:
    """Return the ``FEATURE_NAMES``-keyed vector for ``recipe``."""
    per_function: dict[ComponentFunction, float] = dict.fromkeys(_FUNCTION_ORDER, 0.0)
    weighted_density = 0.0
    weighted_tg_num = 0.0
    weighted_tg_den = 0.0
    voc_fraction = 0.0

    components = list(recipe.all_components)
    for component in components:
        per_function[component.functional_role] = (
            per_function.get(component.functional_role, 0.0) + component.mass_percent
        )
        props = component.properties
        if props is None:
            continue
        density = _safe(props.density_g_per_cm3)
        if density > 0:
            weighted_density += density * (component.mass_percent / 100.0)
        # Tg is only meaningful for the binder side.
        if (
            component.functional_role is ComponentFunction.BINDER
            and props.glass_transition_c is not None
        ):
            weighted_tg_num += props.glass_transition_c * component.mass_percent
            weighted_tg_den += component.mass_percent
        if props.voc_fraction is not None:
            voc_fraction += props.voc_fraction * (component.mass_percent / 100.0)

    features: dict[str, float] = {
        f"mass_percent_{fn.value}": per_function.get(fn, 0.0) for fn in _FUNCTION_ORDER
    }
    features["sum_pigment_percent"] = per_function.get(ComponentFunction.PIGMENT, 0.0)
    features["sum_extender_percent"] = per_function.get(ComponentFunction.EXTENDER, 0.0)
    features["weighted_density"] = weighted_density
    features["weighted_tg"] = weighted_tg_num / weighted_tg_den if weighted_tg_den else 0.0
    features["voc_component_fraction"] = voc_fraction
    features["stage_count"] = float(len(recipe.stages))
    features["component_count"] = float(len(components))
    return features


def to_vector(recipe: Recipe) -> list[float]:
    """Convenience wrapper — returns features aligned with ``FEATURE_NAMES``."""
    f = extract_features(recipe)
    return [f[name] for name in FEATURE_NAMES]


__all__ = ["FEATURE_NAMES", "extract_features", "to_vector"]
