"""Catalogue-wide health / data-quality snapshot.

Answers the operator's question "which R-rules are hurting me most,
and where do I start fixing?" without a manual SQL walk.  Powers the
``/dashboard/data-quality`` endpoint and its UI page.

Runs :meth:`VerificationRules.can_be_verified` over every recipe in
the catalogue, groups the results by rule + category, and returns
counts + a small sample of offenders per bucket so a technologist can
click straight through to a broken row.
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ...domain.services.verification_rules import VerificationRules
from ...domain.value_objects.verification_status import VerificationState
from ...infrastructure.observability._helpers import observed

if TYPE_CHECKING:
    from ..ports.recipe_repository import RecipeRepository


logger = logging.getLogger(__name__)


# Human-readable descriptions per R-rule.  Keeping them close to the
# aggregation lets the API contract stay stable even if the rule code
# renames a rule internally.  Every code in
# :class:`VerificationRules` must have an entry here — the API tests
# assert exhaustiveness.
_RULE_TITLES: dict[str, str] = {
    "R1": "Primary source must have ISBN, DOI, or URL for verifiable citation.",
    "R2": "Verified recipes require enough independent verifications.",
    "R3": "Every component must have a CAS number (or 'mixture' / 'proprietary').",
    "R4": "Source references must come from approved publishers/standards.",
    "R5": "Rejected recipes cannot skip the pending-review state.",
}


@dataclass(frozen=True, slots=True)
class RuleBreakdown:
    """One row of the "R-rule × count" summary."""

    rule: str
    title: str
    n_recipes: int
    by_category: dict[str, int]
    # Small sample so the UI can render clickable links without
    # streaming the full offender list.  Capped at ``sample_size``
    # (default 10 in :class:`DataQualityQuery`).
    sample_recipe_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class CategoryBreakdown:
    """Per-category health: how many recipes, how many are clean."""

    category: str
    n_total: int
    n_clean: int
    n_with_violations: int
    n_verified: int
    n_draft: int
    top_rules: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class DataQualityReport:
    """Whole-catalogue snapshot returned by the use case."""

    total_recipes: int
    n_clean: int
    n_with_violations: int
    verified_share: float  # in [0, 1]
    by_rule: list[RuleBreakdown]
    by_category: list[CategoryBreakdown]
    by_status: dict[str, int]


@dataclass(frozen=True, slots=True)
class DataQualityQuery:
    """Filter options for the health scan."""

    sample_size: int = 10  # offenders returned per rule bucket
    # Enumeration cap so a runaway call cannot pin the DB.  ``None``
    # means "walk the whole catalogue".
    max_recipes: int | None = None


class DataQualityUseCase:
    """Aggregate every rule violation across the catalogue."""

    def __init__(self, recipe_repo: RecipeRepository) -> None:
        self._recipe_repo = recipe_repo

    @observed("data_quality_scan")
    async def execute(self, query: DataQualityQuery) -> DataQualityReport:
        """Walk the catalogue and produce the health summary."""
        ids = await self._recipe_repo.list_all_ids(limit=query.max_recipes)
        total = len(ids)

        # Aggregators
        rule_counts: Counter[str] = Counter()
        rule_by_cat: dict[str, Counter[str]] = defaultdict(Counter)
        rule_samples: dict[str, list[str]] = defaultdict(list)
        cat_total: Counter[str] = Counter()
        cat_clean: Counter[str] = Counter()
        cat_verified: Counter[str] = Counter()
        cat_draft: Counter[str] = Counter()
        cat_rules: dict[str, Counter[str]] = defaultdict(Counter)
        status_counts: Counter[str] = Counter()
        n_clean = 0

        for rid in ids:
            recipe = await self._recipe_repo.get_by_id(rid)
            if recipe is None:
                # Deletion race — very rare, but a scan must not
                # crash because a row disappeared mid-walk.
                continue
            cat = recipe.category
            cat_total[cat] += 1
            state = recipe.status.state
            status_counts[state.value] += 1
            if state is VerificationState.VERIFIED:
                cat_verified[cat] += 1
            elif state is VerificationState.DRAFT:
                cat_draft[cat] += 1

            _, violations = VerificationRules.can_be_verified(recipe)
            if not violations:
                n_clean += 1
                cat_clean[cat] += 1
                continue

            seen_rules_for_recipe: set[str] = set()
            for v in violations:
                if v.rule in seen_rules_for_recipe:
                    continue
                seen_rules_for_recipe.add(v.rule)
                rule_counts[v.rule] += 1
                rule_by_cat[v.rule][cat] += 1
                cat_rules[cat][v.rule] += 1
                if len(rule_samples[v.rule]) < max(1, query.sample_size):
                    rule_samples[v.rule].append(recipe.id)

        # Materialise the by_rule table sorted descending by count so
        # the operator sees the most-hurting rule first.
        by_rule = [
            RuleBreakdown(
                rule=rule,
                title=_RULE_TITLES.get(rule, ""),
                n_recipes=n,
                by_category=dict(rule_by_cat[rule]),
                sample_recipe_ids=list(rule_samples[rule]),
            )
            for rule, n in rule_counts.most_common()
        ]

        by_category = [
            CategoryBreakdown(
                category=cat,
                n_total=cat_total[cat],
                n_clean=cat_clean[cat],
                n_with_violations=cat_total[cat] - cat_clean[cat],
                n_verified=cat_verified[cat],
                n_draft=cat_draft[cat],
                top_rules=[r for r, _ in cat_rules[cat].most_common(3)],
            )
            for cat in sorted(cat_total.keys())
        ]

        verified_share = (
            status_counts.get(VerificationState.VERIFIED.value, 0) / total if total else 0.0
        )

        return DataQualityReport(
            total_recipes=total,
            n_clean=n_clean,
            n_with_violations=total - n_clean,
            verified_share=verified_share,
            by_rule=by_rule,
            by_category=by_category,
            by_status=dict(status_counts),
        )


__all__ = [
    "CategoryBreakdown",
    "DataQualityQuery",
    "DataQualityReport",
    "DataQualityUseCase",
    "RuleBreakdown",
]
