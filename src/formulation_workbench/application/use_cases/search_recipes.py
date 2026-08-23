"""Search and filter recipes use case."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ...domain.entities.recipe import Recipe
from ...domain.value_objects.verification_status import VerificationState
from ...infrastructure.observability._helpers import observed
from ...infrastructure.observability.metrics import (
    get_catalog_size,
    get_catalog_size_by_status,
    get_recipe_search_results,
)

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

    @observed("search_recipes")
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

        # Total count matching the filter, without pagination — asked
        # of the repository so a UI's "Showing 200 of N" line reports
        # the real N and not the size of the current page.  FTS-first
        # queries fall back to len(recipes) because we can't easily
        # count text-match hits in one query.
        if filter_.text_query:
            total_count = len(recipes) + (1 if has_more else 0)
        else:
            category = filter_.categories[0] if filter_.categories else None
            subcategory = filter_.subcategories[0] if filter_.subcategories else None
            product_class = filter_.product_classes[0] if filter_.product_classes else None
            total_count = await self._recipe_repo.count_by_criteria(
                category=category,
                subcategory=subcategory,
                product_class=product_class,
                status=filter_.status,
                tags=list(filter_.tags) if filter_.tags else None,
            )

        get_recipe_search_results().observe(len(recipes))

        return SearchResult(
            recipes=tuple(recipes),
            total_count=total_count,
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

    @observed("catalog_stats")
    async def execute(self, query: GetCatalogStatisticsQuery) -> CatalogStatistics:
        """Compute statistics."""
        by_status = await self._recipe_repo.count_by_status()
        total = sum(by_status.values())
        # Full category and product-class breakdowns since v1.19 —
        # used by /catalog/facets to power the UI's filter dropdowns.
        by_category = await self._recipe_repo.count_by_category()
        by_product_class = await self._recipe_repo.count_by_product_class()

        get_catalog_size().set(total)
        gauge = get_catalog_size_by_status()
        for state, count in by_status.items():
            gauge.labels(state=state.value).set(count)

        return CatalogStatistics(
            by_status=by_status,
            by_category=by_category,
            by_product_class=by_product_class,
            total=total,
        )


@dataclass(frozen=True, slots=True)
class GetCatalogFacetsQuery:
    """Ask for every value the UI needs to build filter dropdowns."""


@dataclass(frozen=True, slots=True)
class CatalogFacets:
    """Full facet snapshot of the catalogue.

    Every dictionary is keyed by the actual stored value (so a URL
    filter built from it is exact-match ready) and holds the count
    of matching recipes.  Empty categories/classes never appear —
    the UI only needs values that would return >0 results.
    """

    total: int
    by_category: dict[str, int]
    by_subcategory: dict[str, dict[str, int]]
    by_product_class: dict[str, int]
    by_status: dict[str, int]


class GetCatalogFacetsUseCase:
    """Use case for ``/catalog/facets``.

    Exists as a separate use case (rather than folded into
    ``GetCatalogStatisticsUseCase``) because facets are a much larger
    payload — pulling them on every dashboard render would waste
    bandwidth.  The UI hits this once when it renders the recipes
    list, then caches the result until the user navigates away.
    """

    def __init__(self, recipe_repo: RecipeRepository) -> None:
        self._recipe_repo = recipe_repo

    @observed("catalog_facets")
    async def execute(self, query: GetCatalogFacetsQuery) -> CatalogFacets:
        by_category = await self._recipe_repo.count_by_category()
        by_subcategory_flat = await self._recipe_repo.count_by_subcategory()
        by_product_class = await self._recipe_repo.count_by_product_class()
        by_status_state = await self._recipe_repo.count_by_status()

        # Reshape (cat, sub) → nested {cat: {sub: n}} so the UI can
        # render subcategory dropdowns scoped to the chosen category
        # without a second request.
        by_subcategory: dict[str, dict[str, int]] = {}
        for (cat, sub), n in by_subcategory_flat.items():
            by_subcategory.setdefault(cat, {})[sub] = n

        total = sum(by_category.values())
        return CatalogFacets(
            total=total,
            by_category=by_category,
            by_subcategory=by_subcategory,
            by_product_class=by_product_class,
            by_status={s.value: n for s, n in by_status_state.items()},
        )
