"""2D what-if heatmap for a pair of components in a recipe.

Sweeps ``component_a`` × ``component_b`` on a rectangular grid,
rebalances the other components pro-rata for every cell, and asks
one ML model for a prediction.  The result is an ``N × M`` matrix of
predicted values ready to render as a heatmap.

The heavy lifting (pro-rata rebalancing + validation) is delegated to
``_rebalance_around`` from :mod:`.sensitivity_analysis` — this module
just wraps it in a double loop and adds a two-component variant that
edits both target percents in one pass so intermediate states never
sum to more than 100 %.

Design constraints
------------------

*   Grid cells that would drive any other component ≤ 0 are marked as
    ``NaN`` in the output (not omitted, so the UI keeps a stable
    rectangular shape and can render them as blanks).
*   Cell count is capped at ``MAX_CELLS`` (default 400) so an over-
    eager UI request doesn't spawn hundreds of predictor calls.
*   Only one ``property_code`` per request: 2D scans are for narrow
    "what if I tune these two knobs" questions; if a user wants
    multiple properties they can issue N requests in parallel.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ...infrastructure.observability._helpers import observed
from .sensitivity_analysis import (
    ComponentNotInRecipeError,
    _linspace,
)

if TYPE_CHECKING:
    from ...domain.entities.recipe import Recipe
    from ...infrastructure.ml.property_regressor import PropertyRegressor
    from ..ports.recipe_repository import RecipeRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HeatmapQuery:
    recipe_id: str
    component_a: str
    component_b: str
    property_code: str
    a_min: float
    a_max: float
    b_min: float
    b_max: float
    steps_a: int = 11
    steps_b: int = 11


@dataclass(frozen=True, slots=True)
class HeatmapResult:
    recipe_id: str
    component_a: str
    component_b: str
    property_code: str
    baseline_a: float
    baseline_b: float
    a_values: tuple[float, ...]  # length = steps_a
    b_values: tuple[float, ...]  # length = steps_b
    # values[i][j] = predicted property when a=a_values[i], b=b_values[j]
    # None cells were infeasible (no mass budget for the other components).
    values: tuple[tuple[float | None, ...], ...]
    baseline_value: float | None  # prediction at (baseline_a, baseline_b)
    z_min: float | None  # min over non-None cells (for chart colour scale)
    z_max: float | None


class SensitivityHeatmapUseCase:
    """Two-axis what-if analysis producing a rectangular heatmap."""

    MAX_STEPS_PER_AXIS = 25
    MAX_CELLS = 400  # steps_a × steps_b upper bound

    def __init__(
        self,
        recipe_repo: RecipeRepository,
        regressor: PropertyRegressor,
    ) -> None:
        self._recipes = recipe_repo
        self._regressor = regressor

    @observed("sensitivity_heatmap")
    async def execute(self, query: HeatmapQuery) -> HeatmapResult | None:
        recipe = await self._recipes.get_by_id(query.recipe_id)
        if recipe is None:
            return None

        if query.component_a == query.component_b:
            raise ValueError("component_a and component_b must differ")
        if query.a_max <= query.a_min:
            raise ValueError("a_max must be > a_min")
        if query.b_max <= query.b_min:
            raise ValueError("b_max must be > b_min")

        baseline_a = _find_mass(recipe, query.component_a)
        baseline_b = _find_mass(recipe, query.component_b)

        steps_a = min(max(2, query.steps_a), self.MAX_STEPS_PER_AXIS)
        steps_b = min(max(2, query.steps_b), self.MAX_STEPS_PER_AXIS)
        if steps_a * steps_b > self.MAX_CELLS:
            raise ValueError(
                f"steps_a × steps_b = {steps_a * steps_b} exceeds cap {self.MAX_CELLS}"
            )

        a_values = _linspace(query.a_min, query.a_max, steps_a)
        b_values = _linspace(query.b_min, query.b_max, steps_b)

        rows: list[tuple[float | None, ...]] = []
        z_lo = math.inf
        z_hi = -math.inf
        for a in a_values:
            row: list[float | None] = []
            for b in b_values:
                try:
                    perturbed = _rebalance_pair(recipe, query.component_a, a, query.component_b, b)
                except ValueError:
                    row.append(None)
                    continue
                try:
                    prediction = self._regressor.predict(perturbed, query.property_code, alpha=None)
                except Exception:
                    logger.exception(
                        "heatmap_predict_failed",
                        extra={"property_code": query.property_code},
                    )
                    row.append(None)
                    continue
                value = prediction.predicted_value if prediction else None
                if value is not None:
                    z_lo = min(z_lo, value)
                    z_hi = max(z_hi, value)
                row.append(value)
            rows.append(tuple(row))

        # Baseline prediction (best-effort, may fail if baseline is
        # outside the rebalancing feasibility region — unusual).
        baseline_value: float | None = None
        try:
            base_perturbed = _rebalance_pair(
                recipe,
                query.component_a,
                baseline_a,
                query.component_b,
                baseline_b,
            )
            pred = self._regressor.predict(base_perturbed, query.property_code, alpha=None)
            baseline_value = pred.predicted_value if pred else None
        except Exception:
            logger.debug("heatmap_baseline_predict_failed", exc_info=True)

        return HeatmapResult(
            recipe_id=recipe.id,
            component_a=query.component_a,
            component_b=query.component_b,
            property_code=query.property_code,
            baseline_a=baseline_a,
            baseline_b=baseline_b,
            a_values=tuple(a_values),
            b_values=tuple(b_values),
            values=tuple(rows),
            baseline_value=baseline_value,
            z_min=(z_lo if math.isfinite(z_lo) else None),
            z_max=(z_hi if math.isfinite(z_hi) else None),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _find_mass(recipe: Recipe, name: str) -> float:
    for comp in recipe.all_components:
        if comp.name == name:
            return comp.mass_percent
    raise ComponentNotInRecipeError(f"Component {name!r} not found in recipe {recipe.id!r}")


def _rebalance_pair(
    recipe: Recipe,
    name_a: str,
    new_a: float,
    name_b: str,
    new_b: float,
) -> Recipe:
    """Set both target components at once, scale others pro-rata.

    Analogous to ``_rebalance_around`` but for two components in one
    step, so we never build an intermediate recipe whose totals
    exceed 100 %.
    """
    from ...domain.entities.recipe import CompositionStage
    from ...domain.entities.recipe import Recipe as _Recipe

    original_a = 0.0
    original_b = 0.0
    for comp in recipe.all_components:
        if comp.name == name_a:
            original_a += comp.mass_percent
        elif comp.name == name_b:
            original_b += comp.mass_percent

    if original_a <= 0.0:
        raise ValueError(f"baseline mass_percent of {name_a!r} is zero")
    if original_b <= 0.0:
        raise ValueError(f"baseline mass_percent of {name_b!r} is zero")

    other_total = 100.0 - original_a - original_b
    remaining = 100.0 - new_a - new_b
    if remaining <= 0.0 or other_total <= 0.0:
        raise ValueError(f"new_a={new_a:.3f}% + new_b={new_b:.3f}% leaves no mass budget")
    scale = remaining / other_total

    new_stages: list[CompositionStage] = []
    for stage in recipe.stages:
        new_components = []
        for comp in stage.components:
            if comp.name == name_a:
                new_mass = new_a
            elif comp.name == name_b:
                new_mass = new_b
            else:
                new_mass = comp.mass_percent * scale
            if new_mass <= 0.0:
                raise ValueError(f"rebalanced {comp.name!r} would drop to {new_mass:.3f}%")
            new_components.append(_replace_component(comp, new_mass))
        new_stages.append(
            CompositionStage(
                stage_number=stage.stage_number,
                name=stage.name,
                description=stage.description,
                components=tuple(new_components),
                process=stage.process,
            )
        )

    return _Recipe(
        id=recipe.id,
        category=recipe.category,
        subcategory=recipe.subcategory,
        binder_type=recipe.binder_type,
        product_class=recipe.product_class,
        intended_use=recipe.intended_use,
        stages=tuple(new_stages),
        primary_source=recipe.primary_source,
        cross_references=recipe.cross_references,
        created_by=recipe.created_by,
        version=recipe.version,
        tags=recipe.tags,
        finish=recipe.finish,
        color=recipe.color,
    )


def _replace_component(comp, new_mass: float):  # type: ignore[no-untyped-def]
    from ...domain.entities.recipe import Component

    return Component(
        name=comp.name,
        cas_number=comp.cas_number,
        function=comp.function,
        mass_percent=round(new_mass, 4),
        tolerance_percent=comp.tolerance_percent,
        inci_name=comp.inci_name,
        manufacturer_reference=comp.manufacturer_reference,
        notes=comp.notes,
    )


__all__ = [
    "HeatmapQuery",
    "HeatmapResult",
    "SensitivityHeatmapUseCase",
]
