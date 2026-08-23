"""Create Recipe use case.

Handles the creation of a new recipe with proper validation,
verification rules enforcement, and audit logging.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ...domain.entities.recipe import Recipe
from ...domain.events import RecipeCreated
from ...domain.services.verification_rules import VerificationRules

if TYPE_CHECKING:
    from ..ports.audit_logger import AuditLogger
    from ..ports.recipe_repository import RecipeRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CreateRecipeCommand:
    """Command to create a new recipe."""

    recipe: Recipe
    actor: str  # user_id or system identifier


class CreateRecipeUseCase:
    """Use case for creating a new recipe.

    Responsibilities:
    - Validate recipe invariants (already done by Recipe.__init__)
    - Verify verification rules (R1-R5)
    - Persist via repository port
    - Log to audit log
    - Emit domain event (handled by application layer)
    """

    def __init__(
        self,
        recipe_repo: RecipeRepository,
        audit_logger: AuditLogger,
    ) -> None:
        self._recipe_repo = recipe_repo
        self._audit_logger = audit_logger

    async def execute(self, command: CreateRecipeCommand) -> Recipe:
        """Execute the use case. Returns the persisted recipe."""
        recipe = command.recipe
        actor = command.actor

        logger.info(
            "Creating recipe: id=%s, category=%s, class=%s",
            recipe.id,
            recipe.category,
            recipe.product_class.value,
        )

        # Domain invariants already enforced by Recipe.__init__
        # Verify verification rules (best-effort for Draft state)
        is_valid, violations = VerificationRules.can_be_verified(recipe)
        if not is_valid:
            logger.warning(
                "Recipe %s has %d verification rule violations (acceptable for Draft): %s",
                recipe.id,
                len(violations),
                [v.rule for v in violations],
            )

        # Persist
        await self._recipe_repo.save(recipe)

        # Audit log
        await self._audit_logger.log(
            action="Created",
            aggregate_id=recipe.id,
            actor=actor,
            metadata={
                "category": recipe.category,
                "subcategory": recipe.subcategory,
                "product_class": recipe.product_class.value,
                "status": recipe.status.state.value,
            },
        )

        # Emit domain event (in real app, would dispatch via event bus)
        event = RecipeCreated(
            aggregate_id=recipe.id,
            actor=actor,
            recipe_category=recipe.category,
            recipe_subcategory=recipe.subcategory,
            product_class=recipe.product_class.value,
        )
        logger.debug("Domain event emitted: %s", event)

        return recipe
