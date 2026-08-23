"""Assess a recipe against the full technological rule set."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ...domain.services.recipe_assessment import RecipeAssessment, RecipeAssessmentService
from ...infrastructure.observability._helpers import observed

if TYPE_CHECKING:
    from ..ports.recipe_repository import RecipeRepository


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AssessRecipeQuery:
    recipe_id: str


class AssessRecipeUseCase:
    """Load a recipe and produce a :class:`RecipeAssessment`."""

    def __init__(self, recipe_repo: RecipeRepository) -> None:
        self._recipe_repo = recipe_repo

    @observed("assess_recipe")
    async def execute(self, query: AssessRecipeQuery) -> RecipeAssessment | None:
        recipe = await self._recipe_repo.get_by_id(query.recipe_id)
        if recipe is None:
            return None
        assessment = RecipeAssessmentService.assess(recipe)
        logger.info(
            "recipe_assessed",
            extra={
                "recipe_id": query.recipe_id,
                **assessment.summary(),
            },
        )
        return assessment


__all__ = ["AssessRecipeQuery", "AssessRecipeUseCase"]
