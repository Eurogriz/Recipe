"""Verification workflow use cases.

Handles the Draft → PendingReview → Verified state transitions with
proper audit logging.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ...domain.entities.recipe import Recipe
from ...domain.events import RecipeRejected, RecipeSubmittedForReview, RecipeVerified
from ...domain.services.verification_rules import VerificationRules
from ...domain.value_objects.verification_status import VerificationState

if TYPE_CHECKING:
    from ..ports.recipe_repository import RecipeRepository
    from ..ports.audit_logger import AuditLogger


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SubmitRecipeForReviewCommand:
    """Command to submit a recipe for verification."""

    recipe_id: str
    actor: str
    comment: str = ""


class SubmitRecipeForReviewUseCase:
    """Use case to submit a recipe for peer review."""

    def __init__(
        self,
        recipe_repo: RecipeRepository,
        audit_logger: AuditLogger,
    ) -> None:
        self._recipe_repo = recipe_repo
        self._audit_logger = audit_logger

    async def execute(self, command: SubmitRecipeForReviewCommand) -> Recipe:
        """Submit recipe for review.

        Validates: recipe must have primary source.
        """
        existing = await self._recipe_repo.get_by_id(command.recipe_id)
        if existing is None:
            raise ValueError(f"Recipe not found: {command.recipe_id}")

        # Pre-submission validation
        is_valid, violations = VerificationRules.can_be_verified(existing)
        critical_violations = [v for v in violations if v.rule in ("R1", "R3")]
        if critical_violations:
            raise ValueError(
                f"Recipe has critical violations preventing submission: "
                f"{[v.rule + ': ' + v.message for v in critical_violations]}"
            )

        new_recipe = existing.submit_for_review()
        await self._recipe_repo.save(new_recipe)

        await self._audit_logger.log(
            action="SubmittedForReview",
            aggregate_id=command.recipe_id,
            actor=command.actor,
            changes={"comment": command.comment},
        )

        event = RecipeSubmittedForReview(
            aggregate_id=command.recipe_id,
            actor=command.actor,
        )
        logger.debug("Domain event: %s", event)

        return new_recipe


@dataclass(frozen=True, slots=True)
class VerifyRecipeCommand:
    """Command to add a verification (peer review confirmation)."""

    recipe_id: str
    verifier: str  # User ID
    source_citation_id: str  # Citation being verified
    comment: str = ""


class VerifyRecipeUseCase:
    """Use case to add a verification to a recipe.

    Each call increments verification_count by 1.
    When count reaches required_verifications (default 3), recipe
    auto-transitions to VERIFIED state.
    """

    def __init__(
        self,
        recipe_repo: RecipeRepository,
        audit_logger: AuditLogger,
    ) -> None:
        self._recipe_repo = recipe_repo
        self._audit_logger = audit_logger

    async def execute(self, command: VerifyRecipeCommand) -> Recipe:
        """Add verification."""
        existing = await self._recipe_repo.get_by_id(command.recipe_id)
        if existing is None:
            raise ValueError(f"Recipe not found: {command.recipe_id}")

        if existing.status.state != VerificationState.PENDING_REVIEW:
            raise ValueError(
                f"Cannot verify recipe in state {existing.status.state.value}. "
                f"Recipe must be in PendingReview state."
            )

        # Check that the same verifier hasn't already verified this recipe
        # (TODO: implement in repository or via audit log query)

        new_recipe = existing.verify()

        # If this verification brought it to VERIFIED, enforce rules
        if new_recipe.status.is_verified:
            try:
                VerificationRules.enforce_verification(new_recipe)
            except Exception as e:
                # Roll back — don't allow VERIFIED state if rules fail
                logger.error(
                    "Cannot transition to VERIFIED due to rule violations: %s", e
                )
                raise ValueError(
                    f"Verification rules not satisfied: {e}"
                ) from e

        await self._recipe_repo.save(new_recipe)

        await self._audit_logger.log(
            action="Verified",
            aggregate_id=command.recipe_id,
            actor=command.verifier,
            changes={
                "citation_id": command.source_citation_id,
                "comment": command.comment,
                "verification_count": new_recipe.status.verification_count,
            },
            metadata={
                "reached_verified": new_recipe.status.is_verified,
            },
        )

        event = RecipeVerified(
            aggregate_id=command.recipe_id,
            actor=command.verifier,
            verification_count=new_recipe.status.verification_count,
            required_verifications=new_recipe.status.required_verifications,
            reached_threshold=new_recipe.status.is_verified,
        )
        logger.debug("Domain event: %s", event)

        return new_recipe


@dataclass(frozen=True, slots=True)
class RejectRecipeCommand:
    """Command to reject a recipe."""

    recipe_id: str
    actor: str
    reason: str


class RejectRecipeUseCase:
    """Use case to reject a recipe (Admin/Auditor only)."""

    def __init__(
        self,
        recipe_repo: RecipeRepository,
        audit_logger: AuditLogger,
    ) -> None:
        self._recipe_repo = recipe_repo
        self._audit_logger = audit_logger

    async def execute(self, command: RejectRecipeCommand) -> Recipe:
        """Reject recipe."""
        existing = await self._recipe_repo.get_by_id(command.recipe_id)
        if existing is None:
            raise ValueError(f"Recipe not found: {command.recipe_id}")

        new_recipe = existing.reject()
        await self._recipe_repo.save(new_recipe)

        await self._audit_logger.log(
            action="Rejected",
            aggregate_id=command.recipe_id,
            actor=command.actor,
            changes={"reason": command.reason},
        )

        event = RecipeRejected(
            aggregate_id=command.recipe_id,
            actor=command.actor,
            reason=command.reason,
        )
        logger.debug("Domain event: %s", event)

        return new_recipe


@dataclass(frozen=True, slots=True)
class CreateNewVersionCommand:
    """Command to create a new version of a Verified recipe."""

    recipe_id: str
    actor: str
    change_summary: str = ""


class CreateNewVersionUseCase:
    """Use case to create a new version of a Verified recipe.

    The old version remains in VERIFIED state (immutable).
    The new version starts in DRAFT state with previous_version_id set.
    """

    def __init__(
        self,
        recipe_repo: RecipeRepository,
        audit_logger: AuditLogger,
    ) -> None:
        self._recipe_repo = recipe_repo
        self._audit_logger = audit_logger

    async def execute(self, command: CreateNewVersionCommand) -> Recipe:
        """Create new version."""
        existing = await self._recipe_repo.get_by_id(command.recipe_id)
        if existing is None:
            raise ValueError(f"Recipe not found: {command.recipe_id}")

        if not existing.status.is_verified:
            raise ValueError(
                f"Can only create new version of VERIFIED recipe. "
                f"Current state: {existing.status.state.value}"
            )

        new_recipe = existing.create_new_version()
        await self._recipe_repo.save(new_recipe)

        await self._audit_logger.log(
            action="VersionCreated",
            aggregate_id=new_recipe.id,
            actor=command.actor,
            changes={
                "previous_version_id": existing.id,
                "new_version": new_recipe.version,
                "change_summary": command.change_summary,
            },
        )

        logger.info(
            "Created new version %d for recipe %s (previous: %s)",
            new_recipe.version,
            existing.id,
            command.change_summary,
        )

        return new_recipe
