"""Bulk regulatory rescan over the whole catalog.

Use case for compliance officers: given the current SVHC / Annex XVII
snapshot the server has loaded, iterate over every recipe and report
those with *any* regulatory finding.  Optionally filters by minimum
severity (``warning`` / ``error``) so tooling can page only on the
serious hits.

This is a batch operation — it does **not** produce alerts itself.
The webhook alert path lives on the drift side; a regulatory alert
would be a separate policy (which we can plug in via the same
``AlertNotifier`` when the volume of findings warrants it).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ...infrastructure.observability._helpers import observed

if TYPE_CHECKING:
    from ...domain.services.regulatory import RegulatoryComplianceChecker
    from ..ports.recipe_repository import RecipeRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RegulatoryScanQuery:
    limit: int = 500
    category: str | None = None
    # "warning" or "error" — only hits at or above this severity are
    # returned.  Default "warning" returns everything.
    min_severity: str = "warning"


@dataclass(frozen=True, slots=True)
class RegulatoryScanFinding:
    """One row of the scan report — one recipe + its aggregated findings."""

    recipe_id: str
    category: str
    subcategory: str
    status: str
    total_findings: int
    errors: int
    warnings: int
    # Top-3 offending substances (by severity + name), so a Slack
    # summary can quote them without unfolding the whole list.
    top_substances: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class RegulatoryScanResult:
    n_scanned: int
    n_offending: int
    findings: tuple[RegulatoryScanFinding, ...]


class RegulatoryScanUseCase:
    """Run the current REACH checker over every recipe in the catalog."""

    def __init__(
        self,
        recipe_repo: RecipeRepository,
        regulatory_checker: RegulatoryComplianceChecker | None,
    ) -> None:
        self._recipes = recipe_repo
        self._checker = regulatory_checker

    @observed("regulatory_scan")
    async def execute(self, query: RegulatoryScanQuery) -> RegulatoryScanResult:
        if self._checker is None:
            # No CSV data loaded — return an empty scan rather than
            # blow up.  The UI already surfaces this state.
            return RegulatoryScanResult(n_scanned=0, n_offending=0, findings=())

        wanted = 0 if query.min_severity == "warning" else 1
        severity_rank = {"info": -1, "warning": 0, "error": 1}

        recipes = await self._recipes.find_by_criteria(
            category=query.category,
            limit=query.limit,
            offset=0,
        )

        rows: list[RegulatoryScanFinding] = []
        for recipe in recipes:
            findings = self._checker.check(recipe)
            if not findings:
                continue
            errors = sum(1 for f in findings if f.severity == "error")
            warnings = sum(1 for f in findings if f.severity == "warning")
            if errors == 0 and wanted >= 1:
                # min_severity=error but nothing serious found → skip.
                continue
            # Sort by severity descending, then name for stable output.
            ordered = sorted(
                findings,
                key=lambda f: (severity_rank.get(f.severity, 0), f.substance),
                reverse=True,
            )
            top = tuple(f"{f.substance} ({f.severity})" for f in ordered[:3])
            rows.append(
                RegulatoryScanFinding(
                    recipe_id=recipe.id,
                    category=recipe.category,
                    subcategory=recipe.subcategory,
                    status=recipe.status.state.value,
                    total_findings=len(findings),
                    errors=errors,
                    warnings=warnings,
                    top_substances=top,
                )
            )

        # Errors first, then more-findings first.
        rows.sort(key=lambda r: (r.errors, r.total_findings), reverse=True)

        return RegulatoryScanResult(
            n_scanned=len(recipes),
            n_offending=len(rows),
            findings=tuple(rows),
        )


__all__ = [
    "RegulatoryScanFinding",
    "RegulatoryScanQuery",
    "RegulatoryScanResult",
    "RegulatoryScanUseCase",
]
