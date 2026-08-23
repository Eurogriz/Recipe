"""Reverse composition search — «find every recipe containing this CAS».

Answers the industrial-search question that plain full-text can't:
«what recipes have TiO2 above 5%», «where is DEHP used»,
«give me every product with PDMS in the binder».  The UI wires it to
the component search page (v1.25).

The use case walks the ``component`` table, filters on CAS + mass-
percent range, groups results per recipe (a recipe may mention the
same CAS in several stages — we sum the mass-percent), and returns
one row per matching recipe.  Sorting is by summed mass-percent
descending — the operator's first question is always «who uses most
of it».
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ...infrastructure.observability._helpers import observed

if TYPE_CHECKING:
    from ..ports.recipe_repository import RecipeRepository


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SearchByComponentQuery:
    """Filter for the reverse-composition search."""

    cas_number: str
    min_mass_percent: float = 0.0
    max_mass_percent: float = 100.0
    # Optional: narrow to a single category before scanning
    # everything.  Speeds up UI for narrow drilldowns.
    category: str | None = None
    limit: int = 100


@dataclass(frozen=True, slots=True)
class ComponentMatch:
    """One recipe hit — how much of the CAS it contains + where."""

    recipe_id: str
    recipe_category: str
    recipe_subcategory: str
    recipe_status: str
    total_mass_percent: float
    # Names as declared in each stage — humans need this because the
    # same CAS can appear under different trade names (e.g. TiO2 as
    # «TiO2», «Titanium dioxide», «Kronos 2310»).
    stage_names: tuple[str, ...] = field(default_factory=tuple)
    n_stages: int = 1


@dataclass(frozen=True, slots=True)
class SearchByComponentResult:
    """Everything the caller needs to render the match list."""

    cas_number: str
    n_recipes: int
    matches: tuple[ComponentMatch, ...]


class SearchByComponentUseCase:
    """Reverse-composition search: CAS → list of recipes."""

    def __init__(self, recipe_repo: RecipeRepository) -> None:
        self._recipe_repo = recipe_repo

    @observed("search_by_component")
    async def execute(self, query: SearchByComponentQuery) -> SearchByComponentResult:
        # Validation: normalise CAS, clamp mass-percent.
        cas = (query.cas_number or "").strip()
        if not cas:
            return SearchByComponentResult(cas_number="", n_recipes=0, matches=())
        low = max(0.0, min(100.0, query.min_mass_percent))
        high = max(low, min(100.0, query.max_mass_percent))
        limit = max(1, min(int(query.limit), 500))

        matches = await self._recipe_repo.find_by_component_cas(
            cas_number=cas,
            min_mass_percent=low,
            max_mass_percent=high,
            category=query.category,
            limit=limit,
        )
        return SearchByComponentResult(
            cas_number=cas,
            n_recipes=len(matches),
            matches=tuple(matches),
        )


__all__ = [
    "ComponentMatch",
    "SearchByComponentQuery",
    "SearchByComponentResult",
    "SearchByComponentUseCase",
]
