"""Flory-Stockmayer network analysis for step-growth polymerisation.

Computes:

- the effective amine-hydrogen equivalent weight (AHEW) once the
  primary / secondary reactivity contrast is respected,
- the gel-point conversion :math:`p_c` of the reactive stoichiometric
  balance following Flory-Stockmayer,
- the theoretical maximum extent of reaction :math:`p_{\\max}` at the
  given equivalents ratio (Carothers-style limit),
- a gel-formation verdict + molecular-weight-buildup indicator.

The math is textbook (Flory 1953, Chapter IX; Odian 4ed. §2-10) and the
formulas below intentionally stay in the units used at the bench —
mass %, equivalents per 100 g, etc.

The engine is called from
:func:`formulation_workbench.domain.services.stoichiometry.analyse`
to enrich the report when both sides of a reactive pair carry a
:attr:`PhysicalProperties.functionality` value.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..entities.recipe import Component


@dataclass(frozen=True, slots=True)
class AmineReactivityBreakdown:
    """Effective vs raw amine-H equivalents for one component."""

    component_name: str
    raw_ah_equivalents_per_100g: float
    effective_ah_equivalents_per_100g: float
    primary_contribution: float
    secondary_contribution: float


@dataclass(frozen=True, slots=True)
class FloryAnalysis:
    """Result of the Flory-Stockmayer analysis for one 2K formulation."""

    # Number-average functionalities of the A/B sides (A = co-reactive,
    # B = reactive: canonical example — A=OH polyol (f_A=3),
    # B=isocyanate crosslinker (f_B=3)).
    functionality_a: float | None
    functionality_b: float | None
    # Equivalents ratio r = min(eq_A, eq_B) / max(eq_A, eq_B) — always in
    # [0, 1].  1.0 = perfectly stoichiometric.
    equivalents_ratio_r: float | None
    # Flory gel-point conversion p_c of the *minority* group:
    #   p_c = 1 / sqrt(r * (f_A - 1) * (f_B - 1))
    gel_point_conversion: float | None
    # Carothers-style theoretical max conversion at the given r,
    # constrained by the limiting reagent.  For the minority group,
    # p_max_minority = 1; for the majority group,
    # p_max_majority = r.
    max_conversion_minority: float
    max_conversion_majority: float
    # Does the system have enough branching to form a covalent network?
    # Flory: (f_A - 1)(f_B - 1) > 1  →  gelation possible.
    can_form_network: bool
    notes: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Amine-H detail
# ---------------------------------------------------------------------------
_DEFAULT_PRIMARY_REACTIVITY = 1.0
_DEFAULT_SECONDARY_REACTIVITY = 0.5


def amine_h_breakdown(component: Component) -> AmineReactivityBreakdown | None:
    """Return the effective amine-H equivalents for one HARDENER component.

    Returns ``None`` when the component doesn't carry any
    :attr:`PhysicalProperties.primary_amine_h_count` /
    :attr:`secondary_amine_h_count` — in that case the caller falls
    back to the aggregate AHEW read from ``equivalent_weight_g_per_eq``.
    """
    props = component.properties
    if props is None:
        return None
    p_count = props.primary_amine_h_count
    s_count = props.secondary_amine_h_count
    ew = props.equivalent_weight_g_per_eq
    if p_count is None and s_count is None:
        return None
    if ew is None or ew <= 0:
        return None

    p_count = p_count or 0
    s_count = s_count or 0
    total_h = p_count + s_count
    if total_h == 0:
        return None

    p_reactivity = (
        props.primary_amine_reactivity
        if props.primary_amine_reactivity is not None
        else _DEFAULT_PRIMARY_REACTIVITY
    )
    s_reactivity = (
        props.secondary_amine_reactivity
        if props.secondary_amine_reactivity is not None
        else _DEFAULT_SECONDARY_REACTIVITY
    )

    # Raw equivalents per 100 g of *component* (ignoring mass %).
    raw_eq_per_100g_component = 100.0 / ew

    # Split by primary vs secondary share.
    p_share = p_count / total_h
    s_share = s_count / total_h
    p_contrib = raw_eq_per_100g_component * p_share * p_reactivity
    s_contrib = raw_eq_per_100g_component * s_share * s_reactivity
    effective = p_contrib + s_contrib

    # Convert to per 100 g of *finished recipe* using mass %.
    scale = component.mass_percent / 100.0
    return AmineReactivityBreakdown(
        component_name=component.name,
        raw_ah_equivalents_per_100g=raw_eq_per_100g_component * scale,
        effective_ah_equivalents_per_100g=effective * scale,
        primary_contribution=p_contrib * scale,
        secondary_contribution=s_contrib * scale,
    )


# ---------------------------------------------------------------------------
# Flory-Stockmayer main entry
# ---------------------------------------------------------------------------
def analyse_flory(
    *,
    equivalents_a: float,
    equivalents_b: float,
    functionality_a: float | None,
    functionality_b: float | None,
) -> FloryAnalysis:
    """Compute the network analysis for one reactive pair.

    ``equivalents_a`` and ``equivalents_b`` are the totals of reactive
    groups in the recipe (mole-equivalents per 100 g).  The functionalities
    are the number-average number of reactive groups per molecule on each
    side; when either is unknown, the analysis reports what it can and
    leaves gel-point / can_form_network null.
    """
    if equivalents_a <= 0 or equivalents_b <= 0:
        return FloryAnalysis(
            functionality_a=functionality_a,
            functionality_b=functionality_b,
            equivalents_ratio_r=None,
            gel_point_conversion=None,
            max_conversion_minority=0.0,
            max_conversion_majority=0.0,
            can_form_network=False,
            notes=("A or B side carries zero equivalents — no network possible.",),
        )

    minority = min(equivalents_a, equivalents_b)
    majority = max(equivalents_a, equivalents_b)
    r = minority / majority

    # Carothers-style bounds.
    max_conversion_minority = 1.0
    max_conversion_majority = r

    notes: list[str] = []
    gel_conversion: float | None = None
    can_gel = False

    if functionality_a is None or functionality_b is None:
        notes.append(
            "Functionality unknown on at least one side — gel-point cannot "
            "be evaluated. Set PhysicalProperties.functionality on both."
        )
    else:
        # Flory-Stockmayer condition for A_f + B_g step-growth:
        #   gelation is possible iff (f-1)(g-1) > 1.
        branching_factor = (functionality_a - 1.0) * (functionality_b - 1.0)
        if branching_factor > 1.0:
            can_gel = True
            try:
                gel_conversion = 1.0 / (r * branching_factor) ** 0.5
            except (ValueError, ZeroDivisionError):
                gel_conversion = None
                notes.append("Gel-point formula degenerated (numerical).")
            if gel_conversion is not None and gel_conversion >= 1.0:
                notes.append(
                    f"Predicted gel-point conversion {gel_conversion:.2f} is "
                    "≥ 1.0 — the branching envelope is too weak for gelation "
                    "at the current stoichiometry."
                )
        else:
            notes.append(
                f"Branching factor (f-1)(g-1) = {branching_factor:.2f} ≤ 1 — "
                "system is linear; expect thermoplastic-like behaviour."
            )

    return FloryAnalysis(
        functionality_a=functionality_a,
        functionality_b=functionality_b,
        equivalents_ratio_r=r,
        gel_point_conversion=gel_conversion,
        max_conversion_minority=max_conversion_minority,
        max_conversion_majority=max_conversion_majority,
        can_form_network=can_gel,
        notes=tuple(notes),
    )


__all__ = [
    "AmineReactivityBreakdown",
    "FloryAnalysis",
    "amine_h_breakdown",
    "analyse_flory",
]
