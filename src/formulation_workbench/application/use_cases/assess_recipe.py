"""Assess a recipe against the full technological rule set."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ...domain.services.recipe_assessment import RecipeAssessment, RecipeAssessmentService
from ...infrastructure.observability._helpers import observed

if TYPE_CHECKING:
    from ...domain.services.regulatory import RegulatoryComplianceChecker
    from ..ports.recipe_repository import RecipeRepository


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AssessRecipeQuery:
    recipe_id: str
    consumer_use: bool = True


class AssessRecipeUseCase:
    """Load a recipe and produce a :class:`RecipeAssessment`."""

    def __init__(
        self,
        recipe_repo: RecipeRepository,
        regulatory_checker: RegulatoryComplianceChecker | None = None,
    ) -> None:
        self._recipe_repo = recipe_repo
        self._regulatory_checker = regulatory_checker

    @observed("assess_recipe")
    async def execute(self, query: AssessRecipeQuery) -> RecipeAssessment | None:
        recipe = await self._recipe_repo.get_by_id(query.recipe_id)
        if recipe is None:
            return None
        assessment = RecipeAssessmentService.assess(
            recipe,
            regulatory_checker=self._regulatory_checker,
            consumer_use=query.consumer_use,
        )
        logger.info(
            "recipe_assessed",
            extra={"recipe_id": query.recipe_id, **assessment.summary()},
        )
        return assessment


__all__ = ["AssessRecipeQuery", "AssessRecipeUseCase"]
