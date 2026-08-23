"""Get recipe by ID use case."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ...domain.entities.recipe import Recipe

if TYPE_CHECKING:
    from ..ports.recipe_repository import RecipeRepository


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class GetRecipeByIdQuery:
    """Query to retrieve a recipe by ID."""

    recipe_id: str
    include_all_versions: bool = False


class GetRecipeByIdUseCase:
    """Use case to retrieve a recipe by its ID."""

    def __init__(self, recipe_repo: RecipeRepository) -> None:
        self._recipe_repo = recipe_repo

    async def execute(self, query: GetRecipeByIdQuery) -> Recipe | None:
        """Execute the query. Returns None if recipe not found."""
        recipe = await self._recipe_repo.get_by_id(query.recipe_id)
        if recipe is None:
            logger.warning("Recipe not found: %s", query.recipe_id)
        return recipe


@dataclass(frozen=True, slots=True)
class GetAllVersionsQuery:
    """Query to retrieve all versions of a recipe."""

    recipe_id: str


class GetAllRecipeVersionsUseCase:
    """Use case to get version history of a recipe."""

    def __init__(self, recipe_repo: RecipeRepository) -> None:
        self._recipe_repo = recipe_repo

    async def execute(self, query: GetAllVersionsQuery) -> list[Recipe]:
        """Execute the query. Returns list of versions (latest first)."""
        return await self._recipe_repo.get_all_versions(query.recipe_id)
