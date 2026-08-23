"""Clone a recipe into a brand-new Draft — independent of version chain.

``CreateNewVersionUseCase`` requires the source recipe to be
``Verified`` and links the clone via ``previous_version_id`` — that's
the right workflow for a controlled evolution of one master recipe.

But formulators also want cheap experimentation: "take this recipe
that's close to what I need, drop it into a new pristine Draft I can
edit freely, don't bother with the version chain".  This use case
does exactly that:

* Any source status is accepted (Verified, Draft, PendingReview,
  Rejected — all get cloned into a fresh Draft).
* The new recipe has a brand-new ``id``, no ``previous_version_id``
  (it is not part of the source's version tree), and ``version=1``.
* Metadata is copied verbatim except for ``created_by`` which is set
  to the calling actor.
* The audit log records both the clone action and the source id, so
  a traceability chain still exists — just outside the domain's
  version link.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ...infrastructure.observability._helpers import observed

if TYPE_CHECKING:
    from ...domain.entities.recipe import Recipe
    from ..ports.audit_logger import AuditLogger
    from ..ports.recipe_repository import RecipeRepository

logger = logging.getLogger(__name__)


class RecipeNotFoundError(Exception):
    """Raised when the source recipe id does not exist."""


@dataclass(frozen=True, slots=True)
class CloneRecipeCommand:
    source_recipe_id: str
    actor: str = ""
    new_id: str | None = None  # let callers pin a specific id (tests)


class CloneRecipeUseCase:
    def __init__(self, recipe_repo: RecipeRepository, audit_logger: AuditLogger) -> None:
        self._recipes = recipe_repo
        self._audit = audit_logger

    @observed("clone_recipe")
    async def execute(self, command: CloneRecipeCommand) -> Recipe:
        from ...domain.entities.recipe import Recipe

        source = await self._recipes.get_by_id(command.source_recipe_id)
        if source is None:
            raise RecipeNotFoundError(f"source recipe not found: {command.source_recipe_id}")

        new_id = command.new_id or uuid.uuid4().hex
        clone = Recipe(
            id=new_id,
            category=source.category,
            subcategory=source.subcategory,
            binder_type=source.binder_type,
            product_class=source.product_class,
            intended_use=source.intended_use,
            stages=source.stages,  # tuples are immutable; safe to share
            primary_source=source.primary_source,
            cross_references=source.cross_references,
            created_by=command.actor or "clone",
            version=1,
            previous_version_id=None,  # unlinked from the source's version tree
            tags=source.tags,
            finish=source.finish,
            color=source.color,
        )
        await self._recipes.save(clone)

        await self._audit.log(
            action="Cloned",
            aggregate_id=clone.id,
            actor=command.actor or "clone",
            changes={"source_recipe_id": source.id},
            metadata={"source_status": source.status.state.value},
        )
        logger.info(
            "recipe cloned",
            extra={"source_id": source.id, "new_id": clone.id, "actor": command.actor},
        )
        return clone


__all__ = ["CloneRecipeCommand", "CloneRecipeUseCase", "RecipeNotFoundError"]
