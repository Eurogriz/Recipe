"""Compute the cost of a recipe using a caller-supplied price catalog."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ...domain.services.cost_calculator import RecipeCost, RecipeCostCalculator
from ...domain.value_objects.cost import Price
from ...infrastructure.observability._helpers import observed

if TYPE_CHECKING:
    from ..ports.recipe_repository import RecipeRepository


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CalculateRecipeCostCommand:
    recipe_id: str
    prices: dict[str, Price] = field(default_factory=dict)


class CalculateRecipeCostUseCase:
    def __init__(self, recipe_repo: RecipeRepository) -> None:
        self._recipe_repo = recipe_repo

    @observed("calculate_recipe_cost")
    async def execute(self, command: CalculateRecipeCostCommand) -> RecipeCost | None:
        recipe = await self._recipe_repo.get_by_id(command.recipe_id)
        if recipe is None:
            return None
        cost = RecipeCostCalculator.calculate(recipe, command.prices)
        logger.info(
            "recipe_cost_calculated",
            extra={"recipe_id": command.recipe_id, **cost.summary()},
        )
        return cost


__all__ = ["CalculateRecipeCostCommand", "CalculateRecipeCostUseCase"]
