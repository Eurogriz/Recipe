"""Aggregated recipe quality assessment.

Turns the collection of verification rules, technological rules, and
calculator outputs into a single :class:`RecipeAssessment` value with a
numeric score (0-100), a maturity label, and a full findings log.

Deliberately kept in the *domain* layer even though it consumes what
looks like "infrastructure" data — the calculators are pure functions of
the entities, so calling them from a domain service does not violate the
dependency rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from .technological_rules import RuleFinding, Severity
from .technological_rules import evaluate as evaluate_tech
from .verification_rules import VerificationRules, VerificationRuleViolation

if TYPE_CHECKING:
    from ..entities.recipe import Recipe


class Maturity(str, Enum):
    """Human-facing maturity label."""

    DEFECTIVE = "defective"  # score < 40
    DRAFT = "draft"  # 40..64
    LAB_READY = "lab_ready"  # 65..79
    PRODUCTION_READY = "production_ready"  # 80..92
    REFERENCE = "reference"  # >= 93


@dataclass(frozen=True, slots=True)
class RecipeAssessment:
    score: float
    maturity: Maturity
    findings: tuple[RuleFinding, ...]
    verification_violations: tuple[VerificationRuleViolation, ...] = field(default_factory=tuple)

    @property
    def has_errors(self) -> bool:
        return any(f.severity is Severity.ERROR for f in self.findings)

    @property
    def has_warnings(self) -> bool:
        return any(f.severity is Severity.WARNING for f in self.findings)

    def summary(self) -> dict[str, int | float | str]:
        """Compact dict useful for logging / metrics / API responses."""
        return {
            "score": self.score,
            "maturity": self.maturity.value,
            "errors": sum(1 for f in self.findings if f.severity is Severity.ERROR),
            "warnings": sum(1 for f in self.findings if f.severity is Severity.WARNING),
            "info": sum(1 for f in self.findings if f.severity is Severity.INFO),
            "verification_violations": len(self.verification_violations),
        }


class RecipeAssessmentService:
    """Compute a :class:`RecipeAssessment` for a recipe."""

    # Penalty table — kept small and explicit so the score is auditable.
    _PENALTY_ERROR = 25.0
    _PENALTY_WARNING = 6.0
    _PENALTY_INFO = 1.0
    _PENALTY_VERIFICATION = 8.0

    @classmethod
    def assess(cls, recipe: Recipe) -> RecipeAssessment:
        tech_findings = evaluate_tech(recipe)
        _, verif_violations = VerificationRules.can_be_verified(recipe)

        score = 100.0
        for finding in tech_findings:
            if finding.severity is Severity.ERROR:
                score -= cls._PENALTY_ERROR
            elif finding.severity is Severity.WARNING:
                score -= cls._PENALTY_WARNING
            else:
                score -= cls._PENALTY_INFO
        # Verification violations always subtract, but never double-punish
        # rules that are effectively duplicates (CAS format).
        for _ in verif_violations:
            score -= cls._PENALTY_VERIFICATION

        score = max(0.0, min(100.0, score))
        maturity = cls._maturity(
            score, has_errors=any(f.severity is Severity.ERROR for f in tech_findings)
        )

        return RecipeAssessment(
            score=round(score, 2),
            maturity=maturity,
            findings=tuple(tech_findings),
            verification_violations=tuple(verif_violations),
        )

    @staticmethod
    def _maturity(score: float, *, has_errors: bool) -> Maturity:
        if has_errors:
            # A recipe with a hard error can never be labelled as
            # production-ready, regardless of score.
            if score < 40:
                return Maturity.DEFECTIVE
            return Maturity.DRAFT
        if score < 40:
            return Maturity.DEFECTIVE
        if score < 65:
            return Maturity.DRAFT
        if score < 80:
            return Maturity.LAB_READY
        if score < 93:
            return Maturity.PRODUCTION_READY
        return Maturity.REFERENCE


__all__ = ["Maturity", "RecipeAssessment", "RecipeAssessmentService"]
