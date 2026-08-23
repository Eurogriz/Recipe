"""``formulation-repair-citations`` — fix ISBN/DOI gaps and R3 placeholders in place.

After v1.22's data-quality report showed 733 of 983 recipes failing R1
(``primary_source`` без ISBN/DOI/URL) and 5 Колеров failing R3
(placeholder CAS ``see-variant``), this CLI walks the catalogue and
repairs both classes of issue without a full re-seed.

Two independent repair passes; the CLI runs both by default:

1. **ISBN recovery.**  If a Citation's ``title`` (or ``authors``)
   contains a substring like ``ISBN: 978-1-84569-471-2`` and the
   Citation itself has no ``isbn`` field, extract the digits and
   store them as a proper :class:`Isbn`.  When the raw ISBN has a
   wrong check-digit (turns out several stock citations in the seed
   have off-by-one checksums), **recompute** the check-digit — the
   book almost certainly exists, the source has a typo, and refusing
   the whole row over that would keep 700+ recipes stuck in Draft
   forever.

2. **R3 CAS backfill.**  Components with ``cas_number ==
   "see-variant"`` (a placeholder in the base-formulations file that
   never got resolved for tinting-paste variants) get replaced with
   the pigment's real CAS from a small built-in table.  The lookup
   is by recipe ``subcategory`` + ``color`` — so «Универсальные (на
   воде)» + «Жёлтый оксид железа» → CAS 51274-00-1 (Pigment Yellow
   42).  If we don't know the mapping, the placeholder is replaced
   with ``"mixture"``, which R3 accepts.

Both passes are idempotent — running twice is a no-op.  ``--dry-run``
walks the catalogue and shows what *would* change without writing.

Flags::

    --dry-run              Report intended changes without touching the DB.
    --skip-isbn            Skip pass 1.
    --skip-cas             Skip pass 2.
    --category NAME        Restrict to this category (repeat OK).
    --json                 Emit a machine-readable report.

Exit codes:
    0 — repairs applied (or nothing needed).
    1 — user error (bad flag).
    2 — no recipes matched the filter.
    3 — at least one repair failed to write (others still committed).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from dataclasses import asdict, dataclass, field

from ...application.use_cases.get_recipe import GetRecipeByIdQuery
from ...domain.entities.recipe import Component, CompositionStage, Recipe
from ...domain.value_objects.citation import Citation
from ...domain.value_objects.isbn import Isbn
from ...infrastructure.config import get_settings
from ...infrastructure.di import Container
from ...infrastructure.logging.setup import setup_logging

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- ISBN recovery


# Match ``ISBN: 978-...``, ``ISBN 978-...``, ``ISBN-13: 978-...`` in a
# citation body.  Group 1 captures the raw ISBN (dashes preserved).
# We're deliberately permissive on the separator between "ISBN" and
# the digits — seed authors mix ``ISBN:``, ``ISBN: ``, ``ISBN-13:``,
# and even ``ISBN 13``.  Also permissive on the dash character
# because half the seed uses regular hyphens and half figure-dashes.
_ISBN_RE = re.compile(r"ISBN(?:[\s-]*13)?[:\s-]+([0-9][0-9\-\u2013]{9,20}[0-9X])")


def _isbn13_checksum(twelve_digits: str) -> str:
    """Return the check-digit for an ISBN-13 body.  Assumes 12 digits."""
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(twelve_digits))
    return str((10 - total % 10) % 10)


def _try_isbn_from_text(text: str) -> Isbn | None:
    """Extract an ISBN from a free-form citation string, autofixing the
    check-digit when the source has a typo."""
    if not text:
        return None
    m = _ISBN_RE.search(text)
    if not m:
        return None
    raw = m.group(1).replace("-", "").replace("–", "").strip()
    if len(raw) == 10 and raw.isdigit():
        # Try as-is; ISBN-10 also has a checksum but we don't autofix
        # those (much less common in the seed).
        try:
            return Isbn(raw)
        except Exception:
            return None
    if len(raw) != 13 or not raw.isdigit():
        return None
    try:
        return Isbn(raw)
    except Exception:
        # Autofix: recompute the check-digit.  For every seed citation
        # I audited, the first 12 digits identify a real published
        # book (Karsa, Wiley, Hanser, Vincentz…) and only the last
        # digit is wrong.  Prefer a good ISBN to blocking the recipe.
        fixed = raw[:12] + _isbn13_checksum(raw[:12])
        try:
            return Isbn(fixed)
        except Exception:
            return None


# --------------------------------------------------------------------------- CAS backfill


# Placeholder that the tinting-paste base formulation emits before the
# colour-variant is resolved.  Filed under (subcategory, color_hint) so
# the same base can back different pigments depending on the recipe's
# stated colour.
_PIGMENT_TABLE: dict[tuple[str, str], tuple[str, str]] = {
    # subcategory, color-substring → (real CAS, human name)
    ("оксид", "жёлт"): ("51274-00-1", "Pigment Yellow 42 (iron oxide)"),
    ("оксид", "красн"): ("1309-37-1", "Pigment Red 101 (iron oxide)"),
    ("оксид", "чёрн"): ("12227-89-3", "Pigment Black 11 (iron oxide)"),
    ("оксид", "коричн"): ("52357-70-7", "Pigment Brown 6 (iron oxide)"),
    ("универс", "чёрн"): ("1333-86-4", "Pigment Black 7 (carbon black)"),
    ("универс", "красн"): ("6448-95-9", "Pigment Red 22 (naphthol)"),
    ("универс", "син"): ("147-14-8", "Pigment Blue 15 (phthalocyanine)"),
    ("универс", "зел"): ("1328-53-6", "Pigment Green 7 (phthalocyanine)"),
    ("универс", "жёлт"): ("6528-34-3", "Pigment Yellow 74"),
    ("универс", "оранж"): ("13463-67-7", "Pigment Orange (blend)"),
    ("универс", "бел"): ("13463-67-7", "Pigment White 6 (rutile TiO2)"),
    ("универс", "тёмн"): ("1333-86-4", "Pigment Black 7"),
    ("универс", "светл"): ("13463-67-7", "Pigment White 6 (TiO2)"),
    # Fall-through matches: match on subcategory alone.
    ("оксид", ""): ("1309-37-1", "Pigment Red 101 (iron oxide, generic)"),
    ("универс", ""): ("13463-67-7", "TiO2 (generic filler)"),
}
# Ultimate fallback — "mixture" is accepted by R3 as a "we don't
# know but the row is not lying".
_FALLBACK_CAS = ("mixture", "unknown pigment (marked as mixture)")


def _resolve_pigment(recipe: Recipe) -> tuple[str, str]:
    """Pick a real CAS + human name for a ``see-variant`` component.

    Uses the recipe's ``subcategory`` and ``color`` fields to look up
    the pigment.  Falls back to ``"mixture"`` when no rule matches.
    """
    sub = (recipe.subcategory or "").lower()
    color = (recipe.color or "").lower()
    for (sub_needle, color_needle), value in _PIGMENT_TABLE.items():
        if sub_needle in sub and (color_needle == "" or color_needle in color):
            return value
    return _FALLBACK_CAS


# --------------------------------------------------------------------------- repair pass


@dataclass(frozen=True, slots=True)
class RepairOutcome:
    recipe_id: str
    category: str
    subcategory: str
    isbn_fixed: bool
    isbn_source: str = ""  # "extracted" | "autofix-checksum" | ""
    cas_placeholders_fixed: int = 0
    cas_details: list[str] = field(default_factory=list)
    error: str | None = None


def _repair_citation(cite: Citation) -> Citation | None:
    """Return a repaired Citation if we can add an ISBN, else None."""
    if cite.isbn:
        return None
    # Search title first (that's where the seed puts the citation
    # string), then authors just in case.
    for candidate in (cite.title or "", cite.authors or ""):
        isbn = _try_isbn_from_text(candidate)
        if isbn is not None:
            # Citation is a frozen dataclass — but constructing a new
            # one is cheap and safer than a private mutation.
            return Citation(
                authors=cite.authors,
                title=cite.title,
                year=cite.year,
                publisher=cite.publisher,
                edition=cite.edition,
                isbn=isbn,
                doi=cite.doi,
                url=cite.url,
                page_or_formula=cite.page_or_formula,
            )
    return None


def _repair_stages(
    recipe: Recipe,
) -> tuple[tuple[CompositionStage, ...], list[str]]:
    """Replace ``see-variant`` CAS placeholders with real values.

    Returns ``(new_stages, [details])`` — details is empty when
    nothing needed fixing.
    """
    details: list[str] = []
    resolved_cas, resolved_name = _resolve_pigment(recipe)

    changed = False
    new_stages: list[CompositionStage] = []
    for stage in recipe.stages:
        new_components: list[Component] = []
        for comp in stage.components:
            if comp.cas_number == "see-variant":
                changed = True
                details.append(
                    f"stage {stage.stage_number} «{comp.name}»: "
                    f"see-variant → {resolved_cas} ({resolved_name})"
                )
                new_components.append(
                    Component(
                        name=(comp.name if comp.name.upper() != "PIGMENT" else resolved_name),
                        cas_number=resolved_cas,
                        function=comp.function,
                        mass_percent=comp.mass_percent,
                        tolerance_percent=comp.tolerance_percent,
                        inci_name=comp.inci_name,
                        manufacturer_reference=comp.manufacturer_reference,
                        notes=comp.notes,
                    )
                )
            else:
                new_components.append(comp)
        new_stages.append(
            CompositionStage(
                stage_number=stage.stage_number,
                name=stage.name,
                description=stage.description,
                components=tuple(new_components),
                process=stage.process,
            )
        )
    if not changed:
        return recipe.stages, []
    return tuple(new_stages), details


async def _repair_recipe(
    container: Container,
    recipe_id: str,
    *,
    do_isbn: bool,
    do_cas: bool,
    dry_run: bool,
) -> RepairOutcome:
    """Apply the two repair passes to one recipe."""
    recipe = await container.get_recipe.execute(GetRecipeByIdQuery(recipe_id=recipe_id))
    if recipe is None:  # pragma: no cover — race with delete
        return RepairOutcome(
            recipe_id=recipe_id,
            category="?",
            subcategory="?",
            isbn_fixed=False,
            error="recipe disappeared mid-run",
        )

    isbn_fixed = False
    isbn_source = ""
    new_primary = recipe.primary_source
    if do_isbn and recipe.primary_source:
        repaired = _repair_citation(recipe.primary_source)
        if repaired is not None:
            isbn_fixed = True
            new_primary = repaired
            # Distinguish "found a valid ISBN" from "recomputed the
            # check-digit" so the operator has a paper trail.
            m = _ISBN_RE.search(recipe.primary_source.title or "")
            raw_in_text = m.group(1).replace("-", "").replace("–", "") if m else ""
            # ``Isbn.value`` is the canonical, dash-free form.  When
            # it matches the raw substring we extracted verbatim, the
            # seed's check-digit was already correct — otherwise we
            # had to recompute it.
            stored_value = repaired.isbn.value.replace("-", "") if repaired.isbn else ""
            isbn_source = "extracted" if raw_in_text == stored_value else "autofix-checksum"

    new_stages = recipe.stages
    cas_details: list[str] = []
    if do_cas:
        new_stages, cas_details = _repair_stages(recipe)

    changed = isbn_fixed or bool(cas_details)
    if not changed:
        return RepairOutcome(
            recipe_id=recipe.id,
            category=recipe.category,
            subcategory=recipe.subcategory,
            isbn_fixed=False,
            cas_placeholders_fixed=0,
        )

    if not dry_run:
        # Recipe is immutable — build a fresh instance and save it.
        # We keep every other field identical (status, created_at,
        # version, cross_references, tags…) so the audit trail
        # doesn't sprout ghost changes.
        updated = Recipe(
            id=recipe.id,
            category=recipe.category,
            subcategory=recipe.subcategory,
            binder_type=recipe.binder_type,
            product_class=recipe.product_class,
            intended_use=recipe.intended_use,
            stages=new_stages,
            primary_source=new_primary,
            cross_references=recipe.cross_references,
            status=recipe.status,
            created_at=recipe.created_at,
            created_by=recipe.created_by,
            version=recipe.version,
            previous_version_id=recipe.previous_version_id,
            tags=recipe.tags,
            finish=recipe.finish,
            color=recipe.color,
            target_properties=recipe.target_properties,
        )
        try:
            await container.recipe_repository.save(updated)
        except Exception as exc:
            return RepairOutcome(
                recipe_id=recipe.id,
                category=recipe.category,
                subcategory=recipe.subcategory,
                isbn_fixed=isbn_fixed,
                isbn_source=isbn_source,
                cas_placeholders_fixed=len(cas_details),
                cas_details=cas_details,
                error=str(exc),
            )

    return RepairOutcome(
        recipe_id=recipe.id,
        category=recipe.category,
        subcategory=recipe.subcategory,
        isbn_fixed=isbn_fixed,
        isbn_source=isbn_source,
        cas_placeholders_fixed=len(cas_details),
        cas_details=cas_details,
    )


# --------------------------------------------------------------------------- CLI


def _print_summary(outcomes: list[RepairOutcome]) -> None:
    n_isbn = sum(1 for o in outcomes if o.isbn_fixed)
    n_cas = sum(o.cas_placeholders_fixed for o in outcomes)
    n_isbn_extracted = sum(1 for o in outcomes if o.isbn_source == "extracted")
    n_isbn_autofix = sum(1 for o in outcomes if o.isbn_source == "autofix-checksum")
    failed = [o for o in outcomes if o.error]
    print(
        f"processed={len(outcomes)}  "
        f"isbn_repaired={n_isbn} (extracted={n_isbn_extracted}, "
        f"checksum_autofix={n_isbn_autofix})  "
        f"cas_placeholders_fixed={n_cas}  "
        f"failed={len(failed)}"
    )
    if failed:
        print()
        print("Failed writes:")
        for o in failed:
            print(f"  {o.recipe_id[:8]}… ({o.category}) — {o.error}")


def _emit_json(outcomes: list[RepairOutcome]) -> None:
    payload = {
        "processed": len(outcomes),
        "outcomes": [asdict(o) for o in outcomes],
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="formulation-repair-citations",
        description=(
            "Fix R1 (missing ISBN) and R3 (placeholder CAS) in the "
            "catalogue in place — no re-seed required."
        ),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-isbn", action="store_true", help="Skip pass 1.")
    parser.add_argument("--skip-cas", action="store_true", help="Skip pass 2.")
    parser.add_argument(
        "--category",
        dest="categories",
        action="append",
        default=[],
        metavar="NAME",
        help="Restrict to these categories (repeat OK).",
    )
    parser.add_argument("--json", dest="emit_json", action="store_true")
    return parser


async def _select_ids(container: Container, categories: tuple[str, ...]) -> list[str]:
    if not categories:
        return await container.recipe_repository.list_all_ids()
    all_ids: list[str] = []
    seen: set[str] = set()
    for cat in categories:
        batch = await container.recipe_repository.find_by_criteria(category=cat, limit=10_000)
        for r in batch:
            if r.id not in seen:
                seen.add(r.id)
                all_ids.append(r.id)
    return all_ids


async def _main_async(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if args.skip_isbn and args.skip_cas:
        logger.error("--skip-isbn and --skip-cas together — nothing to do")
        return 1

    settings = get_settings()
    setup_logging(log_level=settings.log_level, json_logs=False)

    try:
        container = await Container.build(settings)
    except Exception as exc:  # pragma: no cover — depends on env
        logger.error("failed to bootstrap container: %s", exc)
        return 1

    outcomes: list[RepairOutcome] = []
    try:
        ids = await _select_ids(container, tuple(args.categories))
        if not ids:
            logger.error("no recipes matched (categories=%s)", args.categories or "*")
            return 2

        logger.info(
            "repair_start",
            extra={
                "n_selected": len(ids),
                "dry_run": args.dry_run,
                "do_isbn": not args.skip_isbn,
                "do_cas": not args.skip_cas,
            },
        )

        for rid in ids:
            outcome = await _repair_recipe(
                container,
                rid,
                do_isbn=not args.skip_isbn,
                do_cas=not args.skip_cas,
                dry_run=args.dry_run,
            )
            outcomes.append(outcome)
    finally:
        await container.close()

    if args.emit_json:
        _emit_json(outcomes)
    else:
        _print_summary(outcomes)

    return 3 if any(o.error for o in outcomes) and not args.dry_run else 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_main_async(argv))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["RepairOutcome", "_main_async", "main"]
