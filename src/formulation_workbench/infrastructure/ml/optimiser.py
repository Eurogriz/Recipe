"""Recipe optimisation — inverse problem via SciPy `differential_evolution`.

Given a base recipe and a set of desired property values, the optimiser
searches over the mass percents of the components to minimise a weighted
loss between predictions and targets while respecting hard constraints:

- Every component mass stays within a user-supplied
  ``(min_percent, max_percent)`` envelope; defaults keep the mass within
  ±20 % of the original value.
- Total mass sums to 100 % (soft penalty).
- Regulatory hard limits (REACH Annex XVII) act as hard constraints —
  any candidate exceeding them is discarded.

The optimiser is deliberately independent from the training pipeline: it
only needs a callable ``predict(candidate_recipe, property_code) →
value``.  This keeps it testable against a trivial linear stub without
sklearn in the loop.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...domain.entities.recipe import Component, Recipe


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# I/O types
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class PropertyTarget:
    """One goal for the optimiser."""

    property_code: str
    target_value: float
    tolerance: float = 0.0  # 0 = strict match
    direction: str = "match"  # "match" | "minimise" | "maximise"
    weight: float = 1.0  # relative importance in the loss


@dataclass(frozen=True, slots=True)
class ComponentBounds:
    """Per-component search bounds (mass percent)."""

    component_name: str
    min_percent: float
    max_percent: float


@dataclass(frozen=True, slots=True)
class OptimisationRequest:
    base_recipe_id: str
    targets: tuple[PropertyTarget, ...]
    bounds: tuple[ComponentBounds, ...] = field(default_factory=tuple)
    max_iterations: int = 30
    population_size: int = 15
    seed: int | None = 42


@dataclass(frozen=True, slots=True)
class OptimisationResult:
    base_recipe_id: str
    optimised_mass_percent: dict[str, float]
    predicted_values: dict[str, float]
    final_loss: float
    converged: bool
    iterations_used: int
    notes: tuple[str, ...] = ()


PredictFn = Callable[["Recipe", str], float | None]


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
class RecipeOptimiser:
    """Inverse-problem solver for property targets."""

    _MASS_SUM_TARGET = 100.0
    _MASS_SUM_TOLERANCE = 0.5  # match Recipe.MASS_PERCENT_TOLERANCE

    def __init__(self, predictor: PredictFn) -> None:
        self._predict = predictor

    # ------------------------------------------------------------------ optimise
    def optimise(
        self,
        base_recipe: Recipe,
        request: OptimisationRequest,
    ) -> OptimisationResult:
        try:
            from scipy.optimize import differential_evolution
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "scipy is required for optimisation — install 'formulation-workbench[ml]'."
            ) from exc

        components = list(base_recipe.all_components)
        if not components:
            raise ValueError("Cannot optimise an empty recipe")

        bounds_map = {b.component_name: b for b in request.bounds}
        search_bounds: list[tuple[float, float]] = []
        for component in components:
            explicit = bounds_map.get(component.name)
            if explicit is not None:
                low, high = explicit.min_percent, explicit.max_percent
            else:
                # ±20 % of the current mass, floored to 0.
                delta = component.mass_percent * 0.2
                low = max(0.0, component.mass_percent - delta)
                high = min(100.0, component.mass_percent + delta)
            if high <= low:
                high = min(100.0, low + 0.5)
            search_bounds.append((low, high))

        def _loss(vec: list[float]) -> float:
            candidate = self._build_candidate(base_recipe, components, vec)
            if candidate is None:
                # Any structural violation → very large loss so DE
                # keeps searching.
                return 1e9
            mass_sum_penalty = self._mass_sum_penalty(vec)
            prediction_loss = 0.0
            for target in request.targets:
                predicted = self._predict(candidate, target.property_code)
                if predicted is None:
                    return 1e9  # missing model — reject solution
                prediction_loss += _single_loss(predicted, target)
            return prediction_loss + mass_sum_penalty

        result = differential_evolution(
            _loss,
            bounds=search_bounds,
            maxiter=request.max_iterations,
            popsize=request.population_size,
            seed=request.seed,
            polish=False,
            tol=1e-3,
        )
        final_vec = list(result.x)
        optimised = self._build_candidate(base_recipe, components, final_vec)
        notes: list[str] = []

        if optimised is None:
            # Fall back to the incoming recipe — safer than returning garbage.
            optimised = base_recipe
            notes.append(
                "Optimiser could not construct a valid candidate; "
                "returning the base recipe untouched."
            )

        predicted_values: dict[str, float] = {}
        for target in request.targets:
            predicted = self._predict(optimised, target.property_code)
            if predicted is not None:
                predicted_values[target.property_code] = predicted

        optimised_mass = {c.name: v for c, v in zip(components, final_vec, strict=True)}
        return OptimisationResult(
            base_recipe_id=base_recipe.id,
            optimised_mass_percent=optimised_mass,
            predicted_values=predicted_values,
            final_loss=float(result.fun),
            converged=bool(result.success),
            iterations_used=int(getattr(result, "nit", 0)),
            notes=tuple(notes),
        )

    # ------------------------------------------------------------------ helpers
    def _mass_sum_penalty(self, vec: list[float]) -> float:
        total = sum(vec)
        deviation = abs(total - self._MASS_SUM_TARGET)
        # Soft quadratic penalty; multiplier 20 keeps the sum-to-100
        # constraint dominant relative to typical prediction losses.
        if deviation <= self._MASS_SUM_TOLERANCE:
            return 0.0
        return 20.0 * (deviation - self._MASS_SUM_TOLERANCE) ** 2

    def _build_candidate(
        self,
        base_recipe: Recipe,
        components: list[Component],
        vec: list[float],
    ) -> Recipe | None:
        from ...domain.entities.recipe import (
            Component as _Component,
        )
        from ...domain.entities.recipe import (
            CompositionStage as _Stage,
        )
        from ...domain.entities.recipe import (
            InvalidRecipeError,
        )
        from ...domain.entities.recipe import (
            Recipe as _Recipe,
        )

        # 1. Rebuild components with new mass percents.
        new_components: list[_Component] = []
        for original, new_mass in zip(components, vec, strict=True):
            new_components.append(
                _Component(
                    name=original.name,
                    cas_number=original.cas_number,
                    function=original.function,
                    mass_percent=max(0.0, min(100.0, new_mass)),
                    tolerance_percent=original.tolerance_percent,
                    inci_name=original.inci_name,
                    manufacturer_reference=original.manufacturer_reference,
                    notes=original.notes,
                    functional_role=original.functional_role,
                    properties=original.properties,
                    raw_material_id=original.raw_material_id,
                )
            )

        # 2. Normalise the sum to 100 to keep Recipe.__init__ happy.
        total = sum(c.mass_percent for c in new_components)
        if total <= 0:
            return None
        scale = 100.0 / total
        normalised = tuple(
            _Component(
                name=c.name,
                cas_number=c.cas_number,
                function=c.function,
                mass_percent=c.mass_percent * scale,
                tolerance_percent=c.tolerance_percent,
                inci_name=c.inci_name,
                manufacturer_reference=c.manufacturer_reference,
                notes=c.notes,
                functional_role=c.functional_role,
                properties=c.properties,
                raw_material_id=c.raw_material_id,
            )
            for c in new_components
        )

        # 3. Rebuild every stage keeping the process metadata; distribute
        # the normalised components back to their original stage.
        original_index = {(c.name, c.cas_number): idx for idx, c in enumerate(components)}
        new_stages: list[_Stage] = []
        for stage in base_recipe.stages:
            stage_components: list[_Component] = []
            for c in stage.components:
                idx = original_index.get((c.name, c.cas_number))
                if idx is None:
                    continue
                stage_components.append(normalised[idx])
            if not stage_components:
                continue
            new_stages.append(
                _Stage(
                    stage_number=stage.stage_number,
                    name=stage.name,
                    description=stage.description,
                    components=tuple(stage_components),
                    process=stage.process,
                )
            )

        try:
            return _Recipe(
                category=base_recipe.category,
                subcategory=base_recipe.subcategory,
                binder_type=base_recipe.binder_type,
                product_class=base_recipe.product_class,
                intended_use=base_recipe.intended_use,
                stages=tuple(new_stages),
                primary_source=base_recipe.primary_source,
                cross_references=base_recipe.cross_references,
                created_by=base_recipe.created_by,
                tags=base_recipe.tags,
                finish=base_recipe.finish,
                color=base_recipe.color,
                target_properties=base_recipe.target_properties,
                regulatory_context=base_recipe.regulatory_context,
            )
        except InvalidRecipeError as exc:
            logger.debug("candidate rejected: %s", exc)
            return None


# ---------------------------------------------------------------------------
# Loss primitives
# ---------------------------------------------------------------------------
def _single_loss(predicted: float, target: PropertyTarget) -> float:
    if target.direction == "minimise":
        gap = max(0.0, predicted - target.target_value)
    elif target.direction == "maximise":
        gap = max(0.0, target.target_value - predicted)
    else:  # match
        gap = abs(predicted - target.target_value)
        if target.tolerance > 0 and gap <= target.tolerance:
            gap = 0.0
    return target.weight * gap * gap  # squared to emphasise big gaps


__all__ = [
    "ComponentBounds",
    "OptimisationRequest",
    "OptimisationResult",
    "PropertyTarget",
    "RecipeOptimiser",
]
