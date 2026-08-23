"""Find recipes most similar to a target by their feature vector.

Uses cosine similarity on the same 37-column feature vector that ML
regressors are trained on (see ``infrastructure.ml.features``).  That
keeps «similar recipes» consistent with «recipes the models see as
similar» — a formulator looking at two recipes flagged as neighbours
should also expect similar predicted properties.

Cosine similarity is preferred over Euclidean here because the raw
``mass_percent_<function>`` axes are all on the same scale but
scattered across a 37-dim space where most components are zero:
Euclidean would treat two recipes as far apart just because they use
different (but interchangeable) additives, cosine focuses on the
*direction* of the composition profile.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ...infrastructure.observability._helpers import observed

if TYPE_CHECKING:
    from ..ports.recipe_repository import RecipeRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FindSimilarQuery:
    recipe_id: str
    top_k: int = 5
    # Category filter: if truthy, only consider candidates in the same
    # top-level category as the reference recipe.  Prevents matching a
    # paint against a sealant just because their VOC / viscosity axes
    # happen to align.
    same_category_only: bool = True
    # Minimum cosine similarity to accept (0..1).  Defaults to 0 =
    # return top_k unconditionally; set higher to gate quality.
    min_similarity: float = 0.0


@dataclass(frozen=True, slots=True)
class SimilarRecipeMatch:
    recipe_id: str
    category: str
    subcategory: str
    binder_type: str
    product_class: str
    similarity: float  # cosine, in [-1, 1] — usually [0, 1] for compositions


class FindSimilarRecipesUseCase:
    """List recipes closest to a reference by composition-feature cosine."""

    # Cap to keep this snappy even on large catalogs; caller can raise
    # via config later if needed.
    MAX_CANDIDATES = 2000

    def __init__(self, recipe_repo: RecipeRepository) -> None:
        self._recipes = recipe_repo

    @observed("similar_recipes")
    async def execute(self, query: FindSimilarQuery) -> list[SimilarRecipeMatch] | None:
        from ...infrastructure.ml.features import to_vector

        reference = await self._recipes.get_by_id(query.recipe_id)
        if reference is None:
            return None
        ref_vec = to_vector(reference)
        ref_norm = math.sqrt(sum(x * x for x in ref_vec))
        if ref_norm == 0.0:
            # Degenerate reference — nothing to compare.
            return []

        # Enumerate candidates via the repository port with a category
        # prefilter (when the reference has one) to keep the pool tight.
        category = reference.category if query.same_category_only and reference.category else None
        candidates = await self._recipes.find_by_criteria(
            category=category,
            limit=self.MAX_CANDIDATES,
            offset=0,
        )

        scored: list[SimilarRecipeMatch] = []
        for candidate in candidates:
            if candidate.id == reference.id:
                continue
            vec = to_vector(candidate)
            norm = math.sqrt(sum(x * x for x in vec))
            if norm == 0.0:
                continue
            dot = sum(a * b for a, b in zip(ref_vec, vec, strict=False))
            sim = dot / (ref_norm * norm)
            if sim < query.min_similarity:
                continue
            scored.append(
                SimilarRecipeMatch(
                    recipe_id=candidate.id,
                    category=candidate.category,
                    subcategory=candidate.subcategory,
                    binder_type=candidate.binder_type,
                    product_class=candidate.product_class.value,
                    similarity=sim,
                )
            )

        scored.sort(key=lambda m: m.similarity, reverse=True)
        return scored[: max(1, query.top_k)]


__all__ = [
    "FindSimilarQuery",
    "FindSimilarRecipesUseCase",
    "SimilarRecipeMatch",
]
