"""Session-scoped adapters for the recipe repository and audit logger.

The concrete SQLAlchemy repositories accept an already-open
:class:`AsyncSession`. In application code we usually want
"session-per-operation": these adapters wrap the repositories with a
fresh session (committed on success, rolled back on error) for every
method call. This is the wiring used by :mod:`formulation_workbench.infrastructure.di`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ....application.ports.audit_logger import AuditLogger
from ....application.ports.recipe_repository import RecipeRepository
from ....domain.entities.recipe import Recipe
from ....domain.value_objects.verification_status import VerificationState
from .sqlalchemy_audit_logger import SqlAlchemyAuditLogger
from .sqlalchemy_recipe_repository import SqlAlchemyRecipeRepository

if TYPE_CHECKING:
    from ..connection import Database


class ScopedRecipeRepository(RecipeRepository):
    """Recipe repository that opens a fresh session for every operation."""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def get_by_id(self, recipe_id: str) -> Recipe | None:
        async with self._db.session() as session:
            return await SqlAlchemyRecipeRepository(session).get_by_id(recipe_id)

    async def save(self, recipe: Recipe) -> None:
        async with self._db.session() as session:
            await SqlAlchemyRecipeRepository(session).save(recipe)
            await session.commit()

    async def delete(self, recipe_id: str) -> None:
        async with self._db.session() as session:
            await SqlAlchemyRecipeRepository(session).delete(recipe_id)
            await session.commit()

    async def search_by_text(self, query: str, limit: int = 50) -> list[Recipe]:
        async with self._db.session() as session:
            return await SqlAlchemyRecipeRepository(session).search_by_text(query, limit=limit)

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
        async with self._db.session() as session:
            return await SqlAlchemyRecipeRepository(session).find_by_criteria(
                category=category,
                subcategory=subcategory,
                product_class=product_class,
                status=status,
                tags=tags,
                limit=limit,
                offset=offset,
            )

    async def count_by_status(self) -> dict[VerificationState, int]:
        async with self._db.session() as session:
            return await SqlAlchemyRecipeRepository(session).count_by_status()

    async def get_all_versions(self, recipe_id: str) -> list[Recipe]:
        async with self._db.session() as session:
            return await SqlAlchemyRecipeRepository(session).get_all_versions(recipe_id)


class ScopedAuditLogger(AuditLogger):
    """Audit logger that opens a fresh session per log entry."""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def log(
        self,
        action: str,
        aggregate_id: str,
        actor: str,
        changes: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        async with self._db.session() as session:
            await SqlAlchemyAuditLogger(session).log(
                action=action,
                aggregate_id=aggregate_id,
                actor=actor,
                changes=changes,
                metadata=metadata,
            )
            await session.commit()


__all__ = ["ScopedAuditLogger", "ScopedRecipeRepository"]
