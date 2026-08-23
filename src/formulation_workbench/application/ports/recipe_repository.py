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
    async def get_all_versions(self, recipe_id: str) -> list[Recipe]:
        """Get all versions of a recipe (latest first), including the given ID."""
