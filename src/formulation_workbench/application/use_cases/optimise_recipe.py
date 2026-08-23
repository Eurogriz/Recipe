"""Optimise a recipe against a set of property targets."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ...infrastructure.observability._helpers import observed

if TYPE_CHECKING:
    from ...infrastructure.ml.optimiser import (
        ComponentBounds,
        OptimisationResult,
        PropertyTarget,
    )
    from ...infrastructure.ml.property_regressor import PropertyRegressor
    from ..ports.recipe_repository import RecipeRepository


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OptimiseRecipeCommand:
    recipe_id: str
    targets: tuple[PropertyTarget, ...]
    bounds: tuple[ComponentBounds, ...] = field(default_factory=tuple)
    max_iterations: int = 30
    population_size: int = 15
    seed: int | None = 42


class RecipeNotFoundError(LookupError):
    """Raised when the caller referenced a recipe that no longer exists."""


class OptimiseRecipeUseCase:
    def __init__(
        self,
        recipe_repo: RecipeRepository,
        regressor: PropertyRegressor,
    ) -> None:
        self._recipes = recipe_repo
        self._regressor = regressor

    @observed("optimise_recipe")
    async def execute(self, command: OptimiseRecipeCommand) -> OptimisationResult:
        from ...infrastructure.ml.optimiser import (
            OptimisationRequest,
            RecipeOptimiser,
        )

        recipe = await self._recipes.get_by_id(command.recipe_id)
        if recipe is None:
            raise RecipeNotFoundError(f"Recipe not found: {command.recipe_id}")

        # Regressor is not async; wrap it in a closure the optimiser expects.
        def _predict(candidate, property_code):  # type: ignore[no-untyped-def]
            prediction = self._regressor.predict(candidate, property_code, alpha=None)
            return prediction.predicted_value if prediction else None

        optimiser = RecipeOptimiser(predictor=_predict)
        result = optimiser.optimise(
            recipe,
            OptimisationRequest(
                base_recipe_id=recipe.id,
                targets=command.targets,
                bounds=command.bounds,
                max_iterations=command.max_iterations,
                population_size=command.population_size,
                seed=command.seed,
            ),
        )
        logger.info(
            "recipe_optimised",
            extra={
                "recipe_id": command.recipe_id,
                "converged": result.converged,
                "iterations_used": result.iterations_used,
                "final_loss": round(result.final_loss, 6),
            },
        )
        return result


__all__ = ["OptimiseRecipeCommand", "OptimiseRecipeUseCase", "RecipeNotFoundError"]
