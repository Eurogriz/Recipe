"""Predict one or more property values for a stored recipe."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ...infrastructure.observability._helpers import observed

if TYPE_CHECKING:
    from ...infrastructure.ml.property_regressor import (
        PropertyPrediction,
        PropertyRegressor,
    )
    from ..ports.recipe_repository import RecipeRepository


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PredictPropertyQuery:
    recipe_id: str
    property_codes: tuple[str, ...] = field(default_factory=tuple)


class PredictPropertiesUseCase:
    def __init__(
        self,
        recipe_repo: RecipeRepository,
        regressor: PropertyRegressor,
    ) -> None:
        self._recipes = recipe_repo
        self._regressor = regressor

    @observed("ml_predict")
    async def execute(self, query: PredictPropertyQuery) -> list[PropertyPrediction] | None:
        recipe = await self._recipes.get_by_id(query.recipe_id)
        if recipe is None:
            return None

        # If no explicit property codes were requested, predict for every
        # code that has a trained model available.
        codes = list(query.property_codes)
        if not codes:
            codes = [m.property_code for m in self._regressor.list_models()]

        predictions = []
        for code in codes:
            pred = self._regressor.predict(recipe, code)
            if pred is not None:
                predictions.append(pred)
        logger.info(
            "ml_predict_done",
            extra={
                "recipe_id": query.recipe_id,
                "n_predictions": len(predictions),
                "requested_codes": codes,
            },
        )
        return predictions


__all__ = ["PredictPropertiesUseCase", "PredictPropertyQuery"]
