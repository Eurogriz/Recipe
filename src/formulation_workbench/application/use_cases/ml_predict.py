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
    explain_top_k: int | None = None


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

        codes = list(query.property_codes)
        if not codes:
            codes = [m.property_code for m in self._regressor.list_models()]

        predictions = []
        for code in codes:
            pred = self._regressor.predict(recipe, code, explain_top_k=query.explain_top_k)
            if pred is not None:
                predictions.append(pred)
        logger.info(
            "ml_predict_done",
            extra={
                "recipe_id": query.recipe_id,
                "n_predictions": len(predictions),
                "requested_codes": codes,
                "explain_top_k": query.explain_top_k,
            },
        )
        return predictions


__all__ = ["PredictPropertiesUseCase", "PredictPropertyQuery"]
