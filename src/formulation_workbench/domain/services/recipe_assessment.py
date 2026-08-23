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

from .regulatory import RegulatoryComplianceChecker, RegulatoryFinding
from .regulatory import Severity as _RegSeverity
from .stoichiometry import Severity as _StoichSeverity
from .stoichiometry import StoichiometryReport
from .stoichiometry import analyse as analyse_stoich
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
    regulatory_findings: tuple[RegulatoryFinding, ...] = field(default_factory=tuple)
    stoichiometry: StoichiometryReport | None = None

    @property
    def has_errors(self) -> bool:
        if any(f.severity is Severity.ERROR for f in self.findings):
            return True
        return any(f.severity is _RegSeverity.ERROR for f in self.regulatory_findings)

    @property
    def has_warnings(self) -> bool:
        if any(f.severity is Severity.WARNING for f in self.findings):
            return True
        return any(f.severity is _RegSeverity.WARNING for f in self.regulatory_findings)

    def summary(self) -> dict[str, int | float | str | bool | None]:
        """Compact dict useful for logging / metrics / API responses."""
        reg_err = sum(1 for f in self.regulatory_findings if f.severity is _RegSeverity.ERROR)
        reg_warn = sum(1 for f in self.regulatory_findings if f.severity is _RegSeverity.WARNING)
        stoich_err = sum(
            1
            for f in (self.stoichiometry.findings if self.stoichiometry else ())
            if f.severity is _StoichSeverity.ERROR
        )
        stoich_warn = sum(
            1
            for f in (self.stoichiometry.findings if self.stoichiometry else ())
            if f.severity is _StoichSeverity.WARNING
        )
        return {
            "score": self.score,
            "maturity": self.maturity.value,
            "errors": (
                sum(1 for f in self.findings if f.severity is Severity.ERROR) + reg_err + stoich_err
            ),
            "warnings": (
                sum(1 for f in self.findings if f.severity is Severity.WARNING)
                + reg_warn
                + stoich_warn
            ),
            "info": sum(1 for f in self.findings if f.severity is Severity.INFO),
            "verification_violations": len(self.verification_violations),
            "regulatory_errors": reg_err,
            "regulatory_warnings": reg_warn,
            "stoichiometry_system": (
                self.stoichiometry.detected_system if self.stoichiometry else "none"
            ),
            "stoichiometry_balanced": (
                self.stoichiometry.is_balanced if self.stoichiometry else None
            ),
        }


class RecipeAssessmentService:
    """Compute a :class:`RecipeAssessment` for a recipe."""

    # Penalty table — kept small and explicit so the score is auditable.
    _PENALTY_ERROR = 25.0
    _PENALTY_WARNING = 6.0
    _PENALTY_INFO = 1.0
    _PENALTY_VERIFICATION = 8.0
    _PENALTY_REGULATORY_ERROR = 30.0  # regulatory violations are the harshest
    _PENALTY_REGULATORY_WARNING = 5.0
    _PENALTY_STOICHIOMETRY_ERROR = 20.0
    _PENALTY_STOICHIOMETRY_WARNING = 4.0

    @classmethod
    def assess(
        cls,
        recipe: Recipe,
        *,
        regulatory_checker: RegulatoryComplianceChecker | None = None,
        consumer_use: bool = True,
    ) -> RecipeAssessment:
        tech_findings = evaluate_tech(recipe)
        _, verif_violations = VerificationRules.can_be_verified(recipe)
        reg_checker = regulatory_checker or RegulatoryComplianceChecker()
        reg_findings = reg_checker.check(recipe, consumer_use=consumer_use)
        stoich = analyse_stoich(recipe)

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
        # Regulatory violations are the harshest — non-compliance blocks sale.
        for reg in reg_findings:
            if reg.severity is _RegSeverity.ERROR:
                score -= cls._PENALTY_REGULATORY_ERROR
            elif reg.severity is _RegSeverity.WARNING:
                score -= cls._PENALTY_REGULATORY_WARNING
        for sf in stoich.findings:
            if sf.severity is _StoichSeverity.ERROR:
                score -= cls._PENALTY_STOICHIOMETRY_ERROR
            elif sf.severity is _StoichSeverity.WARNING:
                score -= cls._PENALTY_STOICHIOMETRY_WARNING

        score = max(0.0, min(100.0, score))
        has_errors = (
            any(f.severity is Severity.ERROR for f in tech_findings)
            or any(r.severity is _RegSeverity.ERROR for r in reg_findings)
            or any(sf.severity is _StoichSeverity.ERROR for sf in stoich.findings)
        )
        maturity = cls._maturity(score, has_errors=has_errors)

        return RecipeAssessment(
            score=round(score, 2),
            maturity=maturity,
            regulatory_findings=tuple(reg_findings),
            findings=tuple(tech_findings),
            verification_violations=tuple(verif_violations),
            stoichiometry=stoich,
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
