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

        # Collect experiments.  When the caller supplies ``recipe_ids``
        # we walk only those; otherwise the recipe repository is asked
        # to enumerate every id in the catalogue (added in v1.19).
        # This matters because pre-v1.19 a bare ``formulation-workbench
        # train`` call collected zero samples and silently did nothing.
        recipe_ids: list[str] = list(command.recipe_ids) if command.recipe_ids else []
        if not recipe_ids:
            recipe_ids = await self._recipes.list_all_ids()
            logger.info(
                "ml_train_full_catalogue",
                extra={"n_recipes": len(recipe_ids)},
            )

        experiments = []
        recipes: dict[str, object] = {}

        for rid in recipe_ids:
            runs = await self._exp.list_for_recipe(rid)
            if not runs:
                continue
            experiments.extend(runs)
            recipe = await self._recipes.get_by_id(rid)
            if recipe is not None:
                recipes[rid] = recipe

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
