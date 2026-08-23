"""Recipe Repository port.

Defines the contract for recipe persistence. The infrastructure layer
provides the concrete implementation (SQLAlchemy-based).
"""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...domain.entities.recipe import Recipe
    from ...domain.value_objects.verification_status import VerificationState


class RecipeRepository(abc.ABC):
    """Abstract interface for recipe persistence.

    All methods are async because SQLAlchemy 2.0 uses async sessions.
    """

    @abc.abstractmethod
    async def get_by_id(self, recipe_id: str) -> Recipe | None:
        """Retrieve a recipe by its unique ID."""

    @abc.abstractmethod
    async def save(self, recipe: Recipe) -> None:
        """Save a new or existing recipe. Idempotent based on ID."""

    @abc.abstractmethod
    async def delete(self, recipe_id: str) -> None:
        """Delete a recipe by ID. Should also log to audit_log."""

    @abc.abstractmethod
    async def search_by_text(self, query: str, limit: int = 50) -> list[Recipe]:
        """Full-text search across recipe fields using FTS5."""

    @abc.abstractmethod
    async def find_by_criteria(
        self,
        category: str | None = None,
        subcategory: str | None = None,
        product_class: str | None = None,
        status: VerificationState | None = None,
        tags: list[str] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Recipe]:
        """Filter recipes by multiple criteria."""

    @abc.abstractmethod
    async def count_by_status(self) -> dict[VerificationState, int]:
        """Count recipes grouped by verification status (for statistics dashboard)."""

    @abc.abstractmethod
    async def count_by_category(self) -> dict[str, int]:
        """Return ``{category → n_recipes}`` for the whole catalogue.

        Powers the ``/catalog/facets`` endpoint that populates the UI's
        category dropdown.  Without this the UI historically built the
        list from a single search page, which meant that a user
        searching for anything other than the first two lexicographic
        categories saw a truncated list.
        """

    @abc.abstractmethod
    async def count_by_subcategory(self) -> dict[tuple[str, str], int]:
        """Return ``{(category, subcategory) → n_recipes}``.

        Uses a compound key so the UI can render subcategory filters
        that are scoped to a chosen category without a follow-up
        request.  Order is up to the concrete implementation but
        callers should not rely on it.
        """

    @abc.abstractmethod
    async def count_by_product_class(self) -> dict[str, int]:
        """Return ``{product_class → n_recipes}`` for the whole catalogue."""

    @abc.abstractmethod
    async def count_by_criteria(
        self,
        category: str | None = None,
        subcategory: str | None = None,
        product_class: str | None = None,
        status: VerificationState | None = None,
        tags: list[str] | None = None,
    ) -> int:
        """Total row count matching the same filter as ``find_by_criteria``.

        Search endpoints must report the total number of matches, not
        the size of the returned page — otherwise UI pagination is a
        lie.  This method exists so a single ``COUNT(*)`` runs in one
        round-trip alongside the paginated fetch.
        """

    @abc.abstractmethod
    async def list_all_ids(self, *, limit: int | None = None) -> list[str]:
        """Enumerate every recipe id in the catalogue.

        Introduced so that cross-recipe ML training does not require
        the caller to hand-craft a full id list.  ``limit=None`` means
        "no cap"; use a positive int to sample.
        """

    @abc.abstractmethod
    async def list_recent(self, *, limit: int = 10) -> list[Recipe]:
        """Return the N most-recently-created recipes.

        Sorted by ``created_at`` descending.  Used by the dashboard's
        "recent activity" widget.  Independent of status — a freshly
        submitted Draft matters as much as a freshly Verified one for
        an operator scanning the timeline.
        """

    @abc.abstractmethod
    async def get_all_versions(self, recipe_id: str) -> list[Recipe]:
        """Get all versions of a recipe (latest first), including the given ID."""
