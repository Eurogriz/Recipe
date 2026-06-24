"""Update recipe use case."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ...domain.entities.recipe import Recipe
from ...domain.events import RecipeUpdated
from ...domain.exceptions import RecipeInvariantViolation
from ...domain.services.verification_rules import VerificationRules

if TYPE_CHECKING:
    from ..ports.recipe_repository import RecipeRepository
    from ..ports.audit_logger import AuditLogger


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class UpdateRecipeCommand:
    """Command to update an existing recipe."""

    recipe: Recipe
    actor: str
    changes_summary: str = ""


class UpdateRecipeUseCase:
    """Use case for updating an existing recipe.

    Critical rules:
    - Verified recipes cannot be updated directly — must create a new version
    - Draft and Rejected recipes can be updated freely
    - PendingReview recipes can be updated (resets to Draft for re-review)
    """

    def __init__(
        self,
        recipe_repo: RecipeRepository,
        audit_logger: AuditLogger,
    ) -> None:
        self._recipe_repo = recipe_repo
        self._audit_logger = audit_logger

    async def execute(self, command: UpdateRecipeCommand) -> Recipe:
        """Execute the update.

        Raises:
            ValueError: If recipe is Verified (must create new version).
            RecipeInvariantViolation: If new state violates invariants.
        """
        new_recipe = command.recipe

        # Check if this is an attempt to modify a Verified recipe
        existing = await self._recipe_repo.get_by_id(new_recipe.id)
        if existing is not None and existing.status.is_verified:
            if existing.version == new_recipe.version:
                raise ValueError(
                    f"Cannot update Verified recipe {existing.id} directly. "
                    f"Use CreateNewVersionUseCase instead."
                )

        logger.info(
            "Updating recipe: id=%s, version=%d, status=%s",
            new_recipe.id,
            new_recipe.version,
            new_recipe.status.state.value,
        )

        # Validate invariants (Recipe.__init__ already did this)
        # For Verified status, ensure verification rules pass
        if new_recipe.status.is_verified:
            try:
                VerificationRules.enforce_verification(new_recipe)
            except Exception as e:
                raise RecipeInvariantViolation(
                    f"Cannot save Verified recipe that fails verification rules: {e}"
                ) from e

        # Persist
        await self._recipe_repo.save(new_recipe)

        # Audit log
        await self._audit_logger.log(
            action="Updated",
            aggregate_id=new_recipe.id,
            actor=command.actor,
            changes={"summary": command.changes_summary},
            metadata={
                "version": new_recipe.version,
                "status": new_recipe.status.state.value,
            },
        )

        # Emit event
        event = RecipeUpdated(
            aggregate_id=new_recipe.id,
            actor=command.actor,
            changes_summary=command.changes_summary,
        )
        logger.debug("Domain event emitted: %s", event)

        return new_recipe
