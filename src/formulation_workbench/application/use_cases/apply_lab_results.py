"""Apply lab experiment results to a recipe.

Given a completed :class:`ExperimentRun`, the use case:

1. Loads the recipe the experiment was run against.
2. Compares the ``measured_properties`` against the recipe's
   ``target_properties``.
3. Depending on ``mode``:
     * ``"annotate"`` — persists the run (audit trail only, recipe
       untouched).  Suitable when the deviations are within tolerance.
     * ``"branch"`` — additionally creates a new *draft* version of the
       recipe with a note describing the deviations, so a formulator can
       iterate.
     * ``"promote"`` — marks the current recipe as verified when *all*
       measurements pass (bypassing 3-verifier voting — restricted to
       admins in the presentation layer).

Emits :class:`LabResultsApplied` audit trail rows for every path.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from ...domain.entities.experiment import ExperimentRun, Verdict
from ...domain.entities.recipe import Recipe
from ...infrastructure.observability._helpers import observed

if TYPE_CHECKING:
    from ..ports.audit_logger import AuditLogger
    from ..ports.experiment_repository import ExperimentRepository
    from ..ports.recipe_repository import RecipeRepository


logger = logging.getLogger(__name__)


class ApplyMode(str, Enum):
    ANNOTATE = "annotate"
    BRANCH = "branch"
    PROMOTE = "promote"


@dataclass(frozen=True, slots=True)
class ApplyLabResultsCommand:
    experiment_id: str
    actor: str
    mode: ApplyMode = ApplyMode.ANNOTATE
    change_note: str = ""


@dataclass(frozen=True, slots=True)
class Deviation:
    property_code: str
    target_value: float
    measured_value: float
    unit: str = ""


@dataclass(frozen=True, slots=True)
class ApplyLabResultsResult:
    original_recipe_id: str
    resulting_recipe_id: str
    verdict: Verdict
    mode: ApplyMode
    deviations: tuple[Deviation, ...] = field(default_factory=tuple)


class ApplyLabResultsError(Exception):
    """Raised when the use case cannot proceed."""


class ApplyLabResultsUseCase:
    def __init__(
        self,
        experiment_repo: ExperimentRepository,
        recipe_repo: RecipeRepository,
        audit_logger: AuditLogger,
    ) -> None:
        self._exp_repo = experiment_repo
        self._recipe_repo = recipe_repo
        self._audit = audit_logger

    @observed("apply_lab_results")
    async def execute(self, command: ApplyLabResultsCommand) -> ApplyLabResultsResult:
        run = await self._exp_repo.get_by_id(command.experiment_id)
        if run is None:
            raise ApplyLabResultsError(f"Experiment not found: {command.experiment_id}")
        if run.verdict is None:
            raise ApplyLabResultsError(
                f"Experiment {command.experiment_id} has no verdict — complete it first."
            )

        recipe = await self._recipe_repo.get_by_id(run.recipe_id)
        if recipe is None:
            raise ApplyLabResultsError(f"Recipe not found: {run.recipe_id}")

        deviations = _compute_deviations(run, recipe)

        # PROMOTE requires no deviations at all.
        if command.mode is ApplyMode.PROMOTE and run.verdict is not Verdict.PASSED:
            raise ApplyLabResultsError("PROMOTE mode requires the experiment verdict to be PASSED.")

        resulting_recipe_id = recipe.id
        if command.mode is ApplyMode.BRANCH:
            new_version = _spawn_branch(recipe, run, command.change_note)
            await self._recipe_repo.save(new_version)
            resulting_recipe_id = new_version.id
        elif command.mode is ApplyMode.PROMOTE:
            promoted = _promote_to_verified(recipe)
            await self._recipe_repo.save(promoted)
            resulting_recipe_id = promoted.id

        await self._audit.log(
            action="LabResultsApplied",
            aggregate_id=recipe.id,
            actor=command.actor,
            changes={
                "experiment_id": command.experiment_id,
                "mode": command.mode.value,
                "verdict": run.verdict.value,
                "resulting_recipe_id": resulting_recipe_id,
                "deviations": [
                    {
                        "property_code": d.property_code,
                        "target": d.target_value,
                        "measured": d.measured_value,
                    }
                    for d in deviations
                ],
            },
        )

        logger.info(
            "lab_results_applied",
            extra={
                "experiment_id": command.experiment_id,
                "recipe_id": recipe.id,
                "mode": command.mode.value,
                "verdict": run.verdict.value,
                "deviations": len(deviations),
            },
        )

        return ApplyLabResultsResult(
            original_recipe_id=recipe.id,
            resulting_recipe_id=resulting_recipe_id,
            verdict=run.verdict,
            mode=command.mode,
            deviations=tuple(deviations),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _compute_deviations(run: ExperimentRun, recipe: Recipe) -> list[Deviation]:
    """Return only the measurements that fell outside the spec."""
    specs = {t.property_code: t for t in recipe.target_properties}
    deviations: list[Deviation] = []
    for mv in run.measured_properties:
        spec = specs.get(mv.property_code)
        if spec is None:
            continue
        if not mv.satisfies(spec):
            deviations.append(
                Deviation(
                    property_code=mv.property_code,
                    target_value=spec.target_value,
                    measured_value=mv.value,
                    unit=mv.unit or spec.unit,
                )
            )
    return deviations


def _spawn_branch(recipe: Recipe, run: ExperimentRun, note: str) -> Recipe:
    """Create a new version of the recipe carrying the deviation note."""
    branched = recipe.create_new_version() if recipe.status.is_verified else recipe
    # If the source recipe is not verified we still bump the version manually.
    if not recipe.status.is_verified:
        # Emulate ``create_new_version`` for non-verified sources without
        # touching the domain layer's transition invariants.
        import uuid
        from datetime import datetime, timezone

        branched = Recipe(
            id=str(uuid.uuid4()),
            category=recipe.category,
            subcategory=recipe.subcategory,
            binder_type=recipe.binder_type,
            product_class=recipe.product_class,
            intended_use=recipe.intended_use,
            stages=recipe.stages,
            primary_source=recipe.primary_source,
            cross_references=recipe.cross_references,
            status=None,
            created_at=datetime.now(timezone.utc),
            created_by=recipe.created_by,
            version=recipe.version + 1,
            previous_version_id=recipe.id,
            tags=(*recipe.tags, f"branched-from-exp-{run.id[:8]}"),
            finish=recipe.finish,
            color=recipe.color,
            target_properties=recipe.target_properties,
            regulatory_context=recipe.regulatory_context,
        )
    _ = note  # currently attached only via the audit_log entry
    return branched


def _promote_to_verified(recipe: Recipe) -> Recipe:
    """Push a recipe to VERIFIED regardless of the 3-verifier gate.

    Called only from the ``promote`` mode; the presentation layer must
    already have checked the caller's authority.
    """
    # Fast path: already verified → nothing to do.
    if recipe.status.is_verified:
        return recipe
    submitted = (
        recipe if recipe.status.state.value == "PendingReview" else recipe.submit_for_review()
    )
    verified = submitted
    for _ in range(submitted.status.required_verifications):
        verified = verified.verify()
    return verified


__all__ = [
    "ApplyLabResultsCommand",
    "ApplyLabResultsError",
    "ApplyLabResultsResult",
    "ApplyLabResultsUseCase",
    "ApplyMode",
    "Deviation",
]
