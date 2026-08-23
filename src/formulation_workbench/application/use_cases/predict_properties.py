"""Predict properties use case.

Wraps the ML predictor with domain logic, always returning
advisory-marked results.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ...domain.entities.recipe import Recipe
from ...infrastructure.ml.property_predictor import (
    PREDICTABLE_PROPERTIES,
    PredictionResult,
    PropertyPredictor,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PredictPropertiesQuery:
    """Query to predict properties for a recipe."""

    recipe: Recipe
    properties: tuple[str, ...] = PREDICTABLE_PROPERTIES


@dataclass(frozen=True, slots=True)
class PredictPropertiesResult:
    """Result of property prediction."""

    recipe_id: str
    predictions: tuple[PredictionResult, ...]
    skipped: tuple[str, ...] = ()  # properties without trained model


class PredictPropertiesUseCase:
    """Use case to predict properties for a recipe using ML-advisory model."""

    def __init__(self, predictor: PropertyPredictor) -> None:
        self._predictor = predictor

    async def execute(self, query: PredictPropertiesQuery) -> PredictPropertiesResult:
        """Execute the prediction."""
        predictions: list[PredictionResult] = []
        skipped: list[str] = []

        for prop_name in query.properties:
            try:
                result = self._predictor.predict(query.recipe, prop_name)
                if result is None:
                    skipped.append(prop_name)
                else:
                    predictions.append(result)
            except Exception:
                logger.exception("Prediction failed for %s", prop_name)
                skipped.append(prop_name)

        return PredictPropertiesResult(
            recipe_id=query.recipe.id,
            predictions=tuple(predictions),
            skipped=tuple(skipped),
        )
