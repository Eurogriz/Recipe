"""What-if sensitivity analysis for a single component in a recipe.

Sweeps the mass_percent of one target component over a user-supplied
range in ``steps`` values.  For each step it produces a rebalanced
recipe (other components scaled pro-rata so the total stays at 100 %)
and asks every trained ML model for a prediction.  The result is a
set of curves — «if I move TiO2 from 15 % to 25 %, how does gloss /
hiding power / viscosity move?» — that a formulator can eyeball to
find the sweet spot before running a real batch.

Design notes
------------

*   We only touch a *copy* of the recipe; the persisted entity is
    never mutated.  Everything runs at ``execute()`` time and returns
    plain dataclasses.
*   Pro-rata rebalancing keeps the same component ordering and the
    same set of components — no components appear or disappear as we
    slide the target's mass fraction, so the ML feature vector stays
    dimensionally consistent across steps.
*   If a step produces a rebalanced value ≤ 0 for any component
    (i.e. the target consumes more mass than everything else can
    concede), that step is skipped rather than failing the whole
    request — the caller can still see the valid portion of the curve.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ...infrastructure.observability._helpers import observed

if TYPE_CHECKING:
    from ...domain.entities.recipe import Recipe
    from ...infrastructure.ml.property_regressor import PropertyRegressor
    from ..ports.recipe_repository import RecipeRepository


logger = logging.getLogger(__name__)


class ComponentNotInRecipeError(Exception):
    """Raised when the requested component_name is not in the recipe."""


@dataclass(frozen=True, slots=True)
class SensitivityQuery:
    recipe_id: str
    component_name: str
    min_percent: float
    max_percent: float
    steps: int = 11  # inclusive endpoints → default gives a nice 10-interval sweep
    property_codes: tuple[str, ...] = ()  # empty = all trained models


@dataclass(frozen=True, slots=True)
class SensitivityPoint:
    """One point on every property curve at a given target mass %.

    ``predictions`` maps property_code → predicted value (may be None
    if the model does not exist or the prediction failed).  Skipped
    steps (see module docstring) are surfaced with ``skipped=True``
    and no predictions.
    """

    target_percent: float
    predictions: dict[str, float | None] = field(default_factory=dict)
    skipped: bool = False
    skip_reason: str = ""


@dataclass(frozen=True, slots=True)
class SensitivityResult:
    recipe_id: str
    component_name: str
    baseline_percent: float
    min_percent: float
    max_percent: float
    steps: int
    property_codes: tuple[str, ...]
    points: tuple[SensitivityPoint, ...]


class SensitivityAnalysisUseCase:
    """Sweep one component's mass % and ask the ML models what happens."""

    # Guard against pathological inputs.
    MAX_STEPS = 41  # 40 intervals is plenty of resolution for a UI curve
    MIN_STEPS = 3

    def __init__(
        self,
        recipe_repo: RecipeRepository,
        regressor: PropertyRegressor,
    ) -> None:
        self._recipes = recipe_repo
        self._regressor = regressor

    @observed("sensitivity_analysis")
    async def execute(self, query: SensitivityQuery) -> SensitivityResult | None:
        recipe = await self._recipes.get_by_id(query.recipe_id)
        if recipe is None:
            return None

        # Baseline of the target component (find first match; component
        # names are effectively unique within a recipe).
        target_baseline: float | None = None
        for comp in recipe.all_components:
            if comp.name == query.component_name:
                target_baseline = comp.mass_percent
                break
        if target_baseline is None:
            raise ComponentNotInRecipeError(
                f"Component {query.component_name!r} not found in recipe {recipe.id!r}"
            )

        if query.steps < self.MIN_STEPS:
            raise ValueError(f"steps must be >= {self.MIN_STEPS}")
        steps = min(query.steps, self.MAX_STEPS)
        if query.max_percent <= query.min_percent:
            raise ValueError("max_percent must be > min_percent")

        # Determine which property codes to predict.  Empty = all
        # currently trained models, in a stable order.
        property_codes = tuple(query.property_codes)
        if not property_codes:
            property_codes = tuple(sorted(m.property_code for m in self._regressor.list_models()))

        # Generate ``steps`` uniformly spaced target percents (endpoints
        # inclusive).  Using a small helper here to avoid depending on
        # numpy at this layer.
        pcts = _linspace(query.min_percent, query.max_percent, steps)

        points: list[SensitivityPoint] = []
        for pct in pcts:
            try:
                perturbed = _rebalance_around(recipe, query.component_name, pct)
            except ValueError as exc:
                points.append(
                    SensitivityPoint(
                        target_percent=pct,
                        predictions={},
                        skipped=True,
                        skip_reason=str(exc),
                    )
                )
                continue

            preds: dict[str, float | None] = {}
            for code in property_codes:
                try:
                    prediction = self._regressor.predict(perturbed, code, alpha=None)
                except Exception:
                    logger.exception("sensitivity_predict_failed", extra={"code": code})
                    prediction = None
                preds[code] = prediction.predicted_value if prediction else None
            points.append(SensitivityPoint(target_percent=pct, predictions=preds))

        return SensitivityResult(
            recipe_id=recipe.id,
            component_name=query.component_name,
            baseline_percent=target_baseline,
            min_percent=query.min_percent,
            max_percent=query.max_percent,
            steps=steps,
            property_codes=property_codes,
            points=tuple(points),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _linspace(lo: float, hi: float, n: int) -> list[float]:
    if n < 2:
        return [lo]
    step = (hi - lo) / (n - 1)
    return [round(lo + step * i, 6) for i in range(n)]


def _rebalance_around(recipe: Recipe, target_name: str, new_pct: float) -> Recipe:
    """Return a copy of ``recipe`` where ``target_name`` is set to
    ``new_pct`` and everything else is scaled pro-rata so the total
    stays at 100 %.

    Raises ``ValueError`` when the perturbation would drive any other
    component to ≤ 0 (no free mass left).
    """
    from ...domain.entities.recipe import (  # local import — heavy module
        CompositionStage,
    )
    from ...domain.entities.recipe import (
        Recipe as _Recipe,
    )

    original_target = 0.0
    for stage in recipe.stages:
        for comp in stage.components:
            if comp.name == target_name:
                original_target += comp.mass_percent

    if original_target <= 0.0:
        raise ValueError("baseline mass_percent of target component is zero")

    other_total = 100.0 - original_target
    remaining_after = 100.0 - new_pct
    if remaining_after <= 0.0 or other_total <= 0.0:
        raise ValueError(f"new_pct={new_pct:.3f}% leaves no mass budget for other components")

    scale = remaining_after / other_total

    new_stages: list[CompositionStage] = []
    for stage in recipe.stages:
        new_components = tuple(
            _replace_component(
                comp,
                new_mass=(new_pct if comp.name == target_name else comp.mass_percent * scale),
            )
            for comp in stage.components
        )
        for comp in new_components:
            if comp.mass_percent <= 0.0:
                raise ValueError(f"rebalanced {comp.name!r} would drop to {comp.mass_percent:.3f}%")
        new_stages.append(
            CompositionStage(
                stage_number=stage.stage_number,
                name=stage.name,
                description=stage.description,
                components=new_components,
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
    "ComponentNotInRecipeError",
    "SensitivityAnalysisUseCase",
    "SensitivityPoint",
    "SensitivityQuery",
    "SensitivityResult",
]
