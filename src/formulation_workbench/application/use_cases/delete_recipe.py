"""Delete recipe use case."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ...infrastructure.observability._helpers import observed

if TYPE_CHECKING:
    from ..ports.audit_logger import AuditLogger
    from ..ports.recipe_repository import RecipeRepository


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DeleteRecipeCommand:
    """Command to delete a recipe."""

    recipe_id: str
    actor: str
    hard_delete: bool = False  # If False, soft-delete (set status=Rejected)


class DeleteRecipeUseCase:
    """Use case for deleting (or soft-deleting) a recipe.

    Default behavior: soft-delete (set status to Rejected, preserve audit trail).
    Use hard_delete=True to physically remove from DB (Admin only).
    """

    def __init__(
        self,
        recipe_repo: RecipeRepository,
        audit_logger: AuditLogger,
    ) -> None:
        self._recipe_repo = recipe_repo
        self._audit_logger = audit_logger

    @observed("delete_recipe")
    async def execute(self, command: DeleteRecipeCommand) -> None:
        """Execute the delete."""
        existing = await self._recipe_repo.get_by_id(command.recipe_id)
        if existing is None:
            logger.warning("Attempted to delete non-existent recipe: %s", command.recipe_id)
            return

        if command.hard_delete:
            await self._recipe_repo.delete(command.recipe_id)
            await self._audit_logger.log(
                action="Deleted",
                aggregate_id=command.recipe_id,
                actor=command.actor,
                metadata={"hard_delete": True},
            )
            logger.warning(
                "HARD DELETE performed on recipe %s by %s",
                command.recipe_id,
                command.actor,
            )
        else:
            # Soft-delete: transition to Rejected
            rejected = existing.reject()
            await self._recipe_repo.save(rejected)
            await self._audit_logger.log(
                action="Rejected",
                aggregate_id=command.recipe_id,
                actor=command.actor,
                metadata={"soft_delete": True},
            )
            logger.info(
                "Soft-deleted (Rejected) recipe %s by %s",
                command.recipe_id,
                command.actor,
            )
