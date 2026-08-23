"""Reactive-system stoichiometry for 2-K coatings.

Handles the three most common industrial cases:

- **Epoxy + amine** — matches OH-adducted or free epoxide equivalent
  weight (EEW) against amine hydrogen equivalent weight (AHEW).
- **Polyurethane** — matches NCO equivalents against OH equivalents on
  the polyol side.
- **Acid + epoxy** / carboxyl systems — same equivalent-weight logic
  reused with a ``ChemicalGroup.CARBOXYL`` label.

The public entry point is :func:`analyse` which returns a rich
:class:`StoichiometryReport` — matched groups, calculated mix ratio,
recommended ranges, and a list of :class:`Finding` objects with severity
levels so the assessment service can integrate them.

Equivalent weights are read from
:class:`PhysicalProperties.equivalent_weight_g_per_eq`, which was added
in v1.2 precisely for this purpose.  Components without a stored
equivalent weight fall back to :attr:`ComponentFunction`-based defaults
that cover the most frequent materials (see ``_DEFAULT_EW``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from ..value_objects.functions import ComponentFunction
from .flory import (
    AmineReactivityBreakdown,
    FloryAnalysis,
    amine_h_breakdown,
    analyse_flory,
)

if TYPE_CHECKING:
    from ..entities.recipe import Component, Recipe


# ---------------------------------------------------------------------------
# Chemical vocabulary
# ---------------------------------------------------------------------------
class ChemicalGroup(str, Enum):
    """Reactive groups tracked by the stoichiometry engine."""

    EPOXIDE = "epoxide"  # oxirane ring — Bakelite epoxies, glycidyl
    HYDROXYL = "hydroxyl"  # -OH  — polyols, hydroxyacrylics
    ISOCYANATE = "isocyanate"  # -N=C=O — polyisocyanates
    AMINE_HYDROGEN = "amine_h"  # -NHx (each active H)
    CARBOXYL = "carboxyl"  # -COOH
    NONE = "none"  # inert / carrier / additive


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class Finding:
    rule_id: str
    severity: Severity
    message: str
    reference: str = ""


@dataclass(frozen=True, slots=True)
class GroupContribution:
    """How many equivalents one component brings."""

    component_name: str
    group: ChemicalGroup
    mass_percent: float
    equivalent_weight_g_per_eq: float
    equivalents_per_100g: float

    def scale_to_batch(self, batch_mass_kg: float) -> float:
        """Return absolute number of equivalents in ``batch_mass_kg``."""
        return self.equivalents_per_100g * (batch_mass_kg * 10.0)  # 1 kg = 10 × 100 g


@dataclass(frozen=True, slots=True)
class ReactivePair:
    """A pair of reactive groups that should balance."""

    reactive_group: ChemicalGroup  # e.g. NCO
    co_reactive_group: ChemicalGroup  # e.g. OH
    label: str  # human-facing pair name


@dataclass(frozen=True, slots=True)
class StoichiometryReport:
    """Full report for one recipe."""

    detected_system: str  # e.g. "polyurethane"
    contributions: tuple[GroupContribution, ...]
    reactive_pair: ReactivePair | None
    reactive_equivalents: float  # e.g. NCO eq per 100 g
    co_reactive_equivalents: float  # e.g. OH  eq per 100 g
    ratio_reactive_to_co: float | None  # None when either side is 0
    recommended_ratio_low: float = 0.95  # 95 % index by default
    recommended_ratio_high: float = 1.10  # 110 % index
    findings: tuple[Finding, ...] = field(default_factory=tuple)
    # Extended analysis — populated whenever we could compute it.
    amine_breakdown: tuple[AmineReactivityBreakdown, ...] = field(default_factory=tuple)
    flory: FloryAnalysis | None = None

    @property
    def is_balanced(self) -> bool:
        if self.ratio_reactive_to_co is None:
            return False
        return (
            self.recommended_ratio_low <= self.ratio_reactive_to_co <= self.recommended_ratio_high
        )

    def summary(self) -> dict[str, str | float | int | bool | None]:
        return {
            "system": self.detected_system,
            "reactive_eq_per_100g": round(self.reactive_equivalents, 5),
            "co_reactive_eq_per_100g": round(self.co_reactive_equivalents, 5),
            "ratio": (
                round(self.ratio_reactive_to_co, 4)
                if self.ratio_reactive_to_co is not None
                else None
            ),
            "balanced": self.is_balanced,
            "warnings": sum(1 for f in self.findings if f.severity is Severity.WARNING),
            "errors": sum(1 for f in self.findings if f.severity is Severity.ERROR),
        }


# ---------------------------------------------------------------------------
# Defaults (used when no equivalent_weight is stored on the component)
# ---------------------------------------------------------------------------
# Rough industrial averages — good enough for a "does the ratio make
# sense at all?" sanity check.
_DEFAULT_EW: dict[tuple[ComponentFunction, ChemicalGroup], float] = {
    (
        ComponentFunction.HARDENER,
        ChemicalGroup.ISOCYANATE,
    ): 180.0,  # HDI trimer trimer / IPDI trimer
    (
        ComponentFunction.HARDENER,
        ChemicalGroup.AMINE_HYDROGEN,
    ): 60.0,  # generic aliphatic amine adduct
    (ComponentFunction.BINDER, ChemicalGroup.HYDROXYL): 600.0,  # OH-acrylic ~ 500-800
    (ComponentFunction.BINDER, ChemicalGroup.EPOXIDE): 190.0,  # bisphenol-A epoxy (EEW ~185)
    (ComponentFunction.BINDER, ChemicalGroup.CARBOXYL): 800.0,
}


# ---------------------------------------------------------------------------
# Group detection
# ---------------------------------------------------------------------------
def _detect_group(component: Component) -> ChemicalGroup:
    """Guess the reactive group carried by ``component``."""
    name = (component.name or "").lower()
    inci = (component.inci_name or "").lower()
    notes = (component.notes or "").lower()
    haystack = f"{name} {inci} {notes}"

    if any(k in haystack for k in ("isocyanate", "hdi", "ipdi", "tdi", "mdi", "polyisocyanate")):
        return ChemicalGroup.ISOCYANATE
    if any(
        k in haystack for k in ("amine", "amino", "polyamide", "adduct", "polyoxypropylene diamine")
    ):
        return ChemicalGroup.AMINE_HYDROGEN
    if any(k in haystack for k in ("epoxy", "epoxide", "glycidyl", "bisphenol", "eew")):
        return ChemicalGroup.EPOXIDE
    if any(k in haystack for k in ("polyol", "hydroxyl", "hydroxy", " oh ", "oh-acrylic")):
        return ChemicalGroup.HYDROXYL
    if any(k in haystack for k in ("acid", "acrylic acid", "carboxyl", "carboxylic")):
        return ChemicalGroup.CARBOXYL
    return ChemicalGroup.NONE


def _equivalent_weight(component: Component, group: ChemicalGroup) -> float | None:
    """Resolve equivalent weight from properties, else fall back to defaults."""
    if component.properties is not None:
        ew = component.properties.equivalent_weight_g_per_eq
        if ew is not None and ew > 0:
            return ew
    return _DEFAULT_EW.get((component.functional_role, group))


def _contribution(component: Component) -> GroupContribution | None:
    group = _detect_group(component)
    if group is ChemicalGroup.NONE:
        return None
    ew = _equivalent_weight(component, group)
    if ew is None or ew <= 0:
        return None
    # Equivalents per 100 g of finished recipe:
    #   (mass_percent g of component / EW g/eq) = eq
    eq_per_100g = component.mass_percent / ew
    return GroupContribution(
        component_name=component.name,
        group=group,
        mass_percent=component.mass_percent,
        equivalent_weight_g_per_eq=ew,
        equivalents_per_100g=eq_per_100g,
    )


# ---------------------------------------------------------------------------
# System heuristics
# ---------------------------------------------------------------------------
def _pick_reactive_pair(present: set[ChemicalGroup]) -> ReactivePair | None:
    """Choose the dominant reactive pair from what's present in the recipe."""
    # Order matters — we favour the more "opinionated" chemistries first.
    if {ChemicalGroup.ISOCYANATE, ChemicalGroup.HYDROXYL}.issubset(present):
        return ReactivePair(ChemicalGroup.ISOCYANATE, ChemicalGroup.HYDROXYL, "polyurethane")
    if {ChemicalGroup.EPOXIDE, ChemicalGroup.AMINE_HYDROGEN}.issubset(present):
        return ReactivePair(ChemicalGroup.AMINE_HYDROGEN, ChemicalGroup.EPOXIDE, "epoxy_amine")
    if {ChemicalGroup.EPOXIDE, ChemicalGroup.CARBOXYL}.issubset(present):
        return ReactivePair(ChemicalGroup.CARBOXYL, ChemicalGroup.EPOXIDE, "epoxy_carboxyl")
    return None


def _sum_equivalents(contribs: tuple[GroupContribution, ...], group: ChemicalGroup) -> float:
    return sum(c.equivalents_per_100g for c in contribs if c.group is group)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def analyse(
    recipe: Recipe,
    *,
    ratio_low: float = 0.95,
    ratio_high: float = 1.10,
) -> StoichiometryReport:
    """Return a :class:`StoichiometryReport` for ``recipe``."""
    contribs: list[GroupContribution] = []
    for component in recipe.all_components:
        contrib = _contribution(component)
        if contrib is not None:
            contribs.append(contrib)

    contribs_t = tuple(contribs)
    groups_present = {c.group for c in contribs_t}
    pair = _pick_reactive_pair(groups_present)

    findings: list[Finding] = []

    # Detect suspicious cases before we run the pair analysis.
    if ComponentFunction.HARDENER in {c.functional_role for c in recipe.all_components}:
        if pair is None:
            findings.append(
                Finding(
                    rule_id="S1",
                    severity=Severity.WARNING,
                    message=(
                        "Recipe declares a HARDENER but no matching reactive group "
                        "was detected on the binder side (OH / epoxide / carboxyl)."
                    ),
                )
            )

    if pair is None:
        return StoichiometryReport(
            detected_system="none",
            contributions=contribs_t,
            reactive_pair=None,
            reactive_equivalents=0.0,
            co_reactive_equivalents=0.0,
            ratio_reactive_to_co=None,
            recommended_ratio_low=ratio_low,
            recommended_ratio_high=ratio_high,
            findings=tuple(findings),
        )

    # If the reactive side is an amine, refine equivalents using primary /
    # secondary NH breakdown when the component carries the extra metadata.
    amine_breakdown: list[AmineReactivityBreakdown] = []
    if pair.reactive_group is ChemicalGroup.AMINE_HYDROGEN:
        for component in recipe.all_components:
            if _detect_group(component) is not ChemicalGroup.AMINE_HYDROGEN:
                continue
            detail = amine_h_breakdown(component)
            if detail is not None:
                amine_breakdown.append(detail)

    reactive_eq = _sum_equivalents(contribs_t, pair.reactive_group)
    coreactive_eq = _sum_equivalents(contribs_t, pair.co_reactive_group)

    # Effective equivalents override the raw sum only when we managed
    # to compute *at least one* breakdown — otherwise stick with the
    # simple AHEW value (backwards compatible).
    if amine_breakdown:
        eff_total = sum(b.effective_ah_equivalents_per_100g for b in amine_breakdown)
        # Only replace if the effective total is strictly positive; a
        # component with no primary + no secondary should never lower
        # reactive_eq to zero.
        if eff_total > 0:
            reactive_eq = eff_total

    ratio: float | None
    ratio = reactive_eq / coreactive_eq if coreactive_eq > 0 else None

    if ratio is None:
        findings.append(
            Finding(
                rule_id="S2",
                severity=Severity.ERROR,
                message=(
                    f"{pair.label}: co-reactive group ({pair.co_reactive_group.value}) "
                    "carries zero equivalents — recipe cannot cure."
                ),
            )
        )
    elif ratio < ratio_low:
        findings.append(
            Finding(
                rule_id="S3",
                severity=Severity.WARNING,
                message=(
                    f"{pair.label}: reactive/co-reactive equivalents ratio "
                    f"{ratio:.3f} is below recommended minimum {ratio_low:.2f} "
                    "— expect an under-cured film with a soft surface."
                ),
                reference="Wicks §12; Vincentz ECH §11",
            )
        )
    elif ratio > ratio_high:
        findings.append(
            Finding(
                rule_id="S4",
                severity=Severity.WARNING,
                message=(
                    f"{pair.label}: reactive/co-reactive ratio {ratio:.3f} exceeds "
                    f"recommended maximum {ratio_high:.2f} — over-crosslinking, "
                    "brittleness and residual reactive groups are likely."
                ),
                reference="Wicks §12; Vincentz ECH §11",
            )
        )
    else:
        findings.append(
            Finding(
                rule_id="S0",
                severity=Severity.INFO,
                message=(
                    f"{pair.label}: reactive/co-reactive ratio {ratio:.3f} "
                    f"is within recommended [{ratio_low:.2f}, {ratio_high:.2f}]."
                ),
            )
        )

    # Functionality — number-averaged across contributors of each group.
    f_reactive = _average_functionality(contribs_t, pair.reactive_group, recipe)
    f_coreactive = _average_functionality(contribs_t, pair.co_reactive_group, recipe)
    flory = analyse_flory(
        equivalents_a=coreactive_eq,
        equivalents_b=reactive_eq,
        functionality_a=f_coreactive,
        functionality_b=f_reactive,
    )

    return StoichiometryReport(
        detected_system=pair.label,
        contributions=contribs_t,
        reactive_pair=pair,
        reactive_equivalents=reactive_eq,
        co_reactive_equivalents=coreactive_eq,
        ratio_reactive_to_co=ratio,
        recommended_ratio_low=ratio_low,
        recommended_ratio_high=ratio_high,
        findings=tuple(findings),
        amine_breakdown=tuple(amine_breakdown),
        flory=flory,
    )


def _average_functionality(
    contribs: tuple[GroupContribution, ...],
    group: ChemicalGroup,
    recipe: Recipe,
) -> float | None:
    """Mass-weighted average functionality across ``group`` contributors."""
    lookup = {c.name: c for c in recipe.all_components}
    numerator = 0.0
    denominator = 0.0
    for contrib in contribs:
        if contrib.group is not group:
            continue
        component = lookup.get(contrib.component_name)
        if component is None or component.properties is None:
            continue
        f = component.properties.functionality
        if f is None or f <= 0:
            continue
        numerator += f * contrib.mass_percent
        denominator += contrib.mass_percent
    if denominator == 0:
        return None
    return numerator / denominator


def batch_mix_ratio(report: StoichiometryReport) -> tuple[float, float] | None:
    """Return the ideal component-A : component-B mass ratio for one batch.

    Only meaningful when the report has a reactive pair whose sides come
    from *distinct* single components (which is the typical 2K case).
    Returns ``(A_parts, B_parts)`` in mass, normalised so that A = 100.
    """
    if report.reactive_pair is None:
        return None
    a_side = [c for c in report.contributions if c.group is report.reactive_pair.co_reactive_group]
    b_side = [c for c in report.contributions if c.group is report.reactive_pair.reactive_group]
    if len(a_side) != 1 or len(b_side) != 1:
        return None
    a_mass = a_side[0].mass_percent
    b_mass = b_side[0].mass_percent
    if a_mass <= 0:
        return None
    return (100.0, b_mass * 100.0 / a_mass)


__all__ = [
    "ChemicalGroup",
    "Finding",
    "GroupContribution",
    "ReactivePair",
    "Severity",
    "StoichiometryReport",
    "analyse",
    "batch_mix_ratio",
]
