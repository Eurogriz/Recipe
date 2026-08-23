"""``formulation-verify-catalog`` — bulk-drive recipes through the review workflow.

Meant for two scenarios:

1. **Post-seed bootstrap.** ``formulation-import-seed`` loads recipes
   in ``Draft`` state (rightly — they haven't been reviewed).  On a
   demo / dev instance where the whole workflow gate is out of scope
   the operator wants every seeded row to sit in ``Verified`` so the
   dashboard doesn't look like nothing has been signed off.

2. **Bulk sign-off after an author change.** Occasionally a QA
   process is run externally and the operator needs to record the
   confirmations in one go rather than clicking each recipe.

The command walks each matching recipe through **Submit → Verify ×
required** and stops at whichever transition fails (so that a partially
processed recipe can still be inspected).  Every action is written to
the audit log with the same ``actor`` label the operator supplied.

Reads settings from the environment exactly like the server, so
pointing it at production or staging is a matter of
``FW_DATABASE_URL=...`` before the call.

Flags
-----

    --actor NAME        (required)  Audit-log actor label.
    --category NAME     (repeat)    Restrict to these categories.
    --status STATE                  Only recipes currently in this state
                                    (default: any non-Verified).
    --limit N                       Process at most N recipes.
    --dry-run                       Show what would happen without touching
                                    the DB.
    --json                          Machine-readable report on stdout.

Exit codes
    0 — every matching recipe reached ``Verified``.
    1 — user error (bad flag, missing --actor, bad category).
    2 — no recipes matched the filter (nothing to do).
    3 — at least one recipe failed to advance.  Others still committed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass

from ...application.use_cases.get_recipe import GetRecipeByIdQuery
from ...application.use_cases.verification_workflow import (
    SubmitRecipeForReviewCommand,
    VerifyRecipeCommand,
)
from ...domain.value_objects.verification_status import VerificationState
from ...infrastructure.config import get_settings
from ...infrastructure.di import Container
from ...infrastructure.logging.setup import setup_logging

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RecipeOutcome:
    """One row of the report — what happened to a specific recipe."""

    recipe_id: str
    category: str
    subcategory: str
    initial_state: str
    final_state: str
    verifications_added: int
    error: str | None = None


# --------------------------------------------------------------------------- action


async def _drive_recipe(
    container: Container,
    recipe_id: str,
    actor: str,
) -> RecipeOutcome:
    """Walk one recipe through the whole submit → verify × required chain."""
    recipe = await container.get_recipe.execute(GetRecipeByIdQuery(recipe_id=recipe_id))
    if recipe is None:  # pragma: no cover — race with concurrent delete
        return RecipeOutcome(
            recipe_id=recipe_id,
            category="?",
            subcategory="?",
            initial_state="?",
            final_state="?",
            verifications_added=0,
            error="recipe disappeared mid-run",
        )

    initial = recipe.status.state.value
    added = 0

    try:
        # Step 1: Submit if we're still in DRAFT.  Verified/Rejected
        # rows are skipped without error — treat as "already done".
        if recipe.status.state is VerificationState.DRAFT:
            await container.submit_for_review.execute(
                SubmitRecipeForReviewCommand(
                    recipe_id=recipe.id,
                    actor=actor,
                    comment="bulk verify: submit",
                )
            )
            recipe = await container.get_recipe.execute(GetRecipeByIdQuery(recipe_id=recipe_id))
            if recipe is None:
                raise RuntimeError("recipe vanished after submit")

        # Step 2: Verify N times to reach the threshold.  Each verify
        # counts as a distinct reviewer — we synthesise reviewer ids
        # like ``bulk:actor:1``, ``bulk:actor:2`` etc.  A recipe with
        # ``required_verifications=3`` needs three calls to land in
        # VERIFIED.
        while (
            recipe.status.state is VerificationState.PENDING_REVIEW
            and not recipe.status.is_verified
        ):
            added += 1
            await container.verify_recipe.execute(
                VerifyRecipeCommand(
                    recipe_id=recipe.id,
                    verifier=f"bulk:{actor}:{added}",
                    # Citation id is stored only in the audit log; the
                    # domain layer doesn't dereference it.  We label
                    # the confirmation with the recipe's primary
                    # source's short form so an auditor reviewing the
                    # log sees which book was signed off against.
                    source_citation_id=recipe.primary_source.short_form
                    if recipe.primary_source
                    else "primary",
                    comment=f"bulk verify #{added}",
                )
            )
            recipe = await container.get_recipe.execute(GetRecipeByIdQuery(recipe_id=recipe_id))
            if recipe is None:  # pragma: no cover
                raise RuntimeError("recipe vanished mid-verify")
            # Safety belt so a mis-configured ``required_verifications``
            # (say the caller set it to 100) doesn't spin forever.
            if added > 32:
                raise RuntimeError(
                    "verify loop exceeded 32 iterations — check "
                    "required_verifications on this recipe"
                )
    except Exception as exc:
        return RecipeOutcome(
            recipe_id=recipe_id,
            category=recipe.category if recipe else "?",
            subcategory=recipe.subcategory if recipe else "?",
            initial_state=initial,
            final_state=recipe.status.state.value if recipe else "?",
            verifications_added=added,
            error=str(exc),
        )

    return RecipeOutcome(
        recipe_id=recipe_id,
        category=recipe.category,
        subcategory=recipe.subcategory,
        initial_state=initial,
        final_state=recipe.status.state.value,
        verifications_added=added,
    )


# --------------------------------------------------------------------------- ids selection


async def _select_recipe_ids(
    container: Container,
    *,
    categories: tuple[str, ...],
    status: VerificationState | None,
    limit: int | None,
) -> list[str]:
    """Return every recipe id matching the filters, up to ``limit``."""
    if not categories and status is None:
        return await container.recipe_repository.list_all_ids(limit=limit)

    # For narrow filters we walk find_by_criteria — it's the same
    # code that serves the /recipes endpoint, so behaviour is
    # deterministic.
    if categories:
        all_ids: list[str] = []
        for cat in categories:
            batch = await container.recipe_repository.find_by_criteria(
                category=cat,
                status=status,
                limit=limit or 10_000,
            )
            all_ids.extend(r.id for r in batch)
        # de-duplicate while preserving order (Python 3.7+ dict-order).
        seen: dict[str, None] = {}
        for rid in all_ids:
            seen[rid] = None
        return list(seen.keys())[: (limit or None)]

    # status filter without a category → find_by_criteria with no
    # category limit; still capped so a slip in --limit doesn't scan
    # the whole DB.
    batch = await container.recipe_repository.find_by_criteria(status=status, limit=limit or 10_000)
    return [r.id for r in batch]


# --------------------------------------------------------------------------- report


def _print_human_summary(outcomes: list[RecipeOutcome]) -> None:
    verified = sum(1 for o in outcomes if o.final_state == "Verified")
    failed = [o for o in outcomes if o.error]
    skipped = sum(
        1 for o in outcomes if o.final_state == o.initial_state and o.verifications_added == 0
    )
    added_total = sum(o.verifications_added for o in outcomes)
    print(
        f"processed={len(outcomes)}  verified={verified}  "
        f"failed={len(failed)}  skipped={skipped}  "
        f"total_verifications_added={added_total}"
    )
    if failed:
        print()
        print("Failed:")
        for o in failed:
            short = o.recipe_id[:8] + "…"
            print(
                f"  {short} ({o.category[:20]:20}) initial={o.initial_state} → "
                f"{o.final_state}  reason: {o.error}"
            )


def _emit_json_report(outcomes: list[RecipeOutcome]) -> None:
    payload = {
        "processed": len(outcomes),
        "verified": sum(1 for o in outcomes if o.final_state == "Verified"),
        "failed": [
            {
                "recipe_id": o.recipe_id,
                "category": o.category,
                "subcategory": o.subcategory,
                "initial_state": o.initial_state,
                "final_state": o.final_state,
                "error": o.error,
            }
            for o in outcomes
            if o.error
        ],
        "outcomes": [
            {
                "recipe_id": o.recipe_id,
                "category": o.category,
                "subcategory": o.subcategory,
                "initial_state": o.initial_state,
                "final_state": o.final_state,
                "verifications_added": o.verifications_added,
                "error": o.error,
            }
            for o in outcomes
        ],
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))


# --------------------------------------------------------------------------- CLI


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="formulation-verify-catalog",
        description=(
            "Bulk-drive recipes through the review workflow (Submit → "
            "Verify × required).  Meant for post-seed bootstrap or "
            "recording an externally-run QA process."
        ),
    )
    parser.add_argument(
        "--actor",
        required=True,
        help=(
            "Audit-log actor label.  Every submit/verify emitted by "
            "this run is attributed to ``bulk:<actor>:<n>``."
        ),
    )
    parser.add_argument(
        "--category",
        dest="categories",
        action="append",
        default=[],
        metavar="NAME",
        help="Restrict to these categories (repeat for multiple).",
    )
    parser.add_argument(
        "--status",
        choices=[s.value for s in VerificationState],
        default=None,
        help=(
            "Only pick recipes currently in this state.  Default: no "
            "status filter (Verified rows are skipped by the driver "
            "anyway)."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N recipes (default: no limit).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would happen without writing to the database.",
    )
    parser.add_argument(
        "--json",
        dest="emit_json",
        action="store_true",
        help="Emit a JSON report on stdout instead of the human summary.",
    )
    return parser


async def _main_async(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if args.limit is not None and args.limit <= 0:
        logger.error("--limit must be a positive integer")
        return 1
    if not args.actor.strip():
        logger.error("--actor must not be empty")
        return 1

    status = VerificationState(args.status) if args.status else None

    settings = get_settings()
    setup_logging(log_level=settings.log_level, json_logs=False)

    try:
        container = await Container.build(settings)
    except Exception as exc:  # pragma: no cover — depends on env
        logger.error("failed to bootstrap container: %s", exc)
        return 1

    outcomes: list[RecipeOutcome] = []
    try:
        ids = await _select_recipe_ids(
            container,
            categories=tuple(args.categories),
            status=status,
            limit=args.limit,
        )
        if not ids:
            logger.error(
                "no recipes matched the filter (categories=%s status=%s limit=%s)",
                args.categories or "*",
                args.status or "*",
                args.limit,
            )
            return 2

        logger.info(
            "verify_catalog_start",
            extra={
                "n_selected": len(ids),
                "categories": list(args.categories),
                "status": args.status,
                "dry_run": args.dry_run,
            },
        )

        if args.dry_run:
            # Fabricate one no-op outcome per id so the report tells
            # the operator what would have happened.
            for rid in ids:
                recipe = await container.get_recipe.execute(GetRecipeByIdQuery(recipe_id=rid))
                if recipe is None:  # pragma: no cover
                    continue
                outcomes.append(
                    RecipeOutcome(
                        recipe_id=rid,
                        category=recipe.category,
                        subcategory=recipe.subcategory,
                        initial_state=recipe.status.state.value,
                        final_state="(dry-run)",
                        verifications_added=0,
                    )
                )
        else:
            for rid in ids:
                outcome = await _drive_recipe(container, rid, args.actor)
                outcomes.append(outcome)
    finally:
        await container.close()

    if args.emit_json:
        _emit_json_report(outcomes)
    else:
        _print_human_summary(outcomes)

    failed = [o for o in outcomes if o.error]
    if failed and not args.dry_run:
        return 3
    return 0


def main(argv: list[str] | None = None) -> int:
    """Sync entry point for the console script."""
    return asyncio.run(_main_async(argv))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["RecipeOutcome", "_main_async", "main"]
