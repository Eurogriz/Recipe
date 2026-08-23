"""Train per-property regressors from the current experiment corpus."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ...infrastructure.observability._helpers import observed

if TYPE_CHECKING:
    from ...infrastructure.ml.property_regressor import PropertyRegressor, TrainingResult
    from ..ports.experiment_repository import ExperimentRepository
    from ..ports.recipe_repository import RecipeRepository


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TrainPropertyModelsCommand:
    """Optional filters make it easy to retrain against a subset."""

    recipe_ids: tuple[str, ...] = field(default_factory=tuple)
    property_codes: tuple[str, ...] = field(default_factory=tuple)


class TrainPropertyModelsUseCase:
    def __init__(
        self,
        experiment_repo: ExperimentRepository,
        recipe_repo: RecipeRepository,
        regressor: PropertyRegressor,
    ) -> None:
        self._exp = experiment_repo
        self._recipes = recipe_repo
        self._regressor = regressor

    @observed("ml_train")
    async def execute(self, command: TrainPropertyModelsCommand) -> TrainingResult:
        from ...infrastructure.ml.property_regressor import (
            build_training_samples,
        )

        # Collect experiments — either for the given recipes only, or every
        # completed run in the store (via the recipe catalogue).
        # The recipe repository does not (yet) expose "list all", so
        # cross-recipe training requires the caller to enumerate ids.
        recipe_ids: list[str] = list(command.recipe_ids) if command.recipe_ids else []

        experiments = []
        recipes: dict[str, object] = {}

        if recipe_ids:
            for rid in recipe_ids:
                runs = await self._exp.list_for_recipe(rid)
                experiments.extend(runs)
                if runs:
                    recipe = await self._recipes.get_by_id(rid)
                    if recipe is not None:
                        recipes[rid] = recipe
        else:
            # Fallback: cross-recipe training is only possible if the
            # caller supplies recipe_ids.  We still try — some deployments
            # may extend the port later.
            logger.info(
                "ml_train_without_recipe_ids",
                extra={"note": "supply recipe_ids for cross-recipe training"},
            )

        samples = build_training_samples(experiments, recipes)  # type: ignore[arg-type]

        if command.property_codes:
            wanted = set(command.property_codes)
            samples = [s for s in samples if s.property_code in wanted]

        result = self._regressor.train(samples)
        logger.info(
            "ml_train_completed",
            extra={
                "n_experiments": len(experiments),
                "n_samples": len(samples),
                "trained": [m.property_code for m in result.trained],
                "skipped": list(result.skipped.keys()),
            },
        )
        return result


__all__ = ["TrainPropertyModelsCommand", "TrainPropertyModelsUseCase"]
