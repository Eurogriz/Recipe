"""Search and filter recipes use case."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ...domain.entities.recipe import Recipe
from ...domain.value_objects.verification_status import VerificationState

if TYPE_CHECKING:
    from ..ports.recipe_repository import RecipeRepository


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SearchFilter:
    """Filter criteria for recipe search."""

    text_query: str = ""
    categories: tuple[str, ...] = ()
    subcategories: tuple[str, ...] = ()
    product_classes: tuple[str, ...] = ()
    binder_types: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    status: VerificationState | None = None
    limit: int = 100
    offset: int = 0


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Search result with metadata."""

    recipes: tuple[Recipe, ...]
    total_count: int
    limit: int
    offset: int
    has_more: bool


class SearchRecipesUseCase:
    """Use case for searching and filtering recipes.

    Uses SQLite FTS5 for full-text search (if available) and
    SQL LIKE for fallback. Filters by category, class, status, tags.
    """

    def __init__(self, recipe_repo: RecipeRepository) -> None:
        self._recipe_repo = recipe_repo

    async def execute(self, filter_: SearchFilter) -> SearchResult:
        """Execute search with filter."""
        logger.debug(
            "Search: text='%s', categories=%s, classes=%s, status=%s",
            filter_.text_query,
            filter_.categories,
            filter_.product_classes,
            filter_.status.value if filter_.status else None,
        )

        # Full-text search first
        if filter_.text_query:
            recipes = await self._recipe_repo.search_by_text(
                filter_.text_query, limit=filter_.limit + 1
            )
        else:
            recipes = []

        # If no FTS results or no text query, use filtered query
        if not recipes:
            # Use first category if specified, else no filter
            category = filter_.categories[0] if filter_.categories else None
            subcategory = filter_.subcategories[0] if filter_.subcategories else None
            product_class = filter_.product_classes[0] if filter_.product_classes else None

            recipes = await self._recipe_repo.find_by_criteria(
                category=category,
                subcategory=subcategory,
                product_class=product_class,
                status=filter_.status,
                tags=list(filter_.tags) if filter_.tags else None,
                limit=filter_.limit + 1,
                offset=filter_.offset,
            )

        # In-memory filtering for multi-value criteria
        if len(filter_.categories) > 1:
            recipes = [r for r in recipes if r.category in filter_.categories]
        if len(filter_.product_classes) > 1:
            recipes = [r for r in recipes if r.product_class.value in filter_.product_classes]
        if len(filter_.binder_types) > 1:
            recipes = [r for r in recipes if r.binder_type in filter_.binder_types]
        if filter_.tags:
            tag_set = set(filter_.tags)
            recipes = [r for r in recipes if tag_set.intersection(set(r.tags))]

        # Pagination
        has_more = len(recipes) > filter_.limit
        recipes = recipes[: filter_.limit]

        return SearchResult(
            recipes=tuple(recipes),
            total_count=len(recipes),
            limit=filter_.limit,
            offset=filter_.offset,
            has_more=has_more,
        )


@dataclass(frozen=True, slots=True)
class GetCatalogStatisticsQuery:
    """Query to get catalog statistics for dashboard."""


@dataclass(frozen=True, slots=True)
class CatalogStatistics:
    """Statistics about the recipe catalog."""

    by_status: dict[VerificationState, int]
    by_category: dict[str, int]
    by_product_class: dict[str, int]
    total: int


class GetCatalogStatisticsUseCase:
    """Use case to compute catalog statistics."""

    def __init__(self, recipe_repo: RecipeRepository) -> None:
        self._recipe_repo = recipe_repo

    async def execute(self, query: GetCatalogStatisticsQuery) -> CatalogStatistics:
        """Compute statistics."""
        by_status = await self._recipe_repo.count_by_status()
        total = sum(by_status.values())

        # Category and class breakdowns require additional queries
        # For MVP, return partial stats
        return CatalogStatistics(
            by_status=by_status,
            by_category={},  # TODO: add count_by_category to repo
            by_product_class={},  # TODO: add count_by_product_class to repo
            total=total,
        )
