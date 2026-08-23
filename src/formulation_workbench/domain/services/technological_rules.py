"""Technological validity rules for coatings/adhesives/sealants formulations.

These rules answer *"is this formulation a technically reasonable
starting point?"* — a superset of the bibliographic verification rules
in :mod:`.verification_rules`.

Every rule returns a :class:`RuleFinding` with a severity so consumers
can treat *info* as advisory and *warning* / *error* as blockers.  The
rules are pure functions of the domain entities — no I/O, no lookups.

Sources for envelopes/thresholds:
    * Flick, E. W. — Water-Based Paint Formulations, Vols. 1-3 (Noyes).
    * Wicks, Z. — Organic Coatings: Science and Technology (4th ed.).
    * Vincentz — European Coatings Handbook (2nd ed.).
    * EU Directive 2004/42/EC, Annex II  (VOC ceilings).
    * BASF, Byk, Evonik technical bulletins for additive dosing.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from ..value_objects.functions import ComponentFunction, envelope_for

if TYPE_CHECKING:
    from ..entities.recipe import Recipe


# ==============================================================================
# Result types
# ==============================================================================
class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class RuleFinding:
    rule_id: str
    severity: Severity
    message: str
    reference: str = ""


# ==============================================================================
# VOC ceilings — EU Directive 2004/42/EC, Annex II ("Products for Vehicle
# Refinishing" excluded; those numbers apply to Cat. A/B/C/D subclasses of
# "coatings for buildings").  Numbers are g/L, ready-to-use.
# ==============================================================================
_VOC_CEILING_G_PER_L: dict[str, dict[str, float]] = {
    # category → subcategory → VOC ceiling
    "Краски": {
        "Водно-дисперсионные": 30.0,  # a) interior matte
        "Interior_glossy": 100.0,  # b) interior glossy
        "Wood_metal_indoor": 130.0,  # d) trim/paneling
        "Wood_metal_outdoor": 300.0,  # e) outdoor trim
    },
    "Грунтовки": {"default": 30.0},  # h) primers
    "Лаки": {"default": 130.0},  # e) wood/metal varnish
    "Клеи": {"default": 100.0},
    "Герметики": {"default": 200.0},
}


def voc_ceiling_for(recipe: Recipe) -> float | None:
    """Look up the VOC ceiling for the recipe's category/subcategory."""
    cat = _VOC_CEILING_G_PER_L.get(recipe.category)
    if cat is None:
        return None
    return cat.get(recipe.subcategory) or cat.get("default")


# ==============================================================================
# Individual rules
# ==============================================================================
def _rule_binder_present(recipe: Recipe) -> list[RuleFinding]:
    """T1 — Every recipe must have at least one BINDER component."""
    findings: list[RuleFinding] = []
    binders = [c for c in recipe.all_components if c.functional_role is ComponentFunction.BINDER]
    if not binders:
        findings.append(
            RuleFinding(
                rule_id="T1",
                severity=Severity.ERROR,
                message="Recipe has no BINDER component; a film-former is required.",
                reference="Wicks §3.1",
            )
        )
    return findings


def _rule_binder_dose(recipe: Recipe) -> list[RuleFinding]:
    """T2 — Binder mass fraction should sit inside its typical envelope."""
    total_binder = sum(
        c.mass_percent
        for c in recipe.all_components
        if c.functional_role is ComponentFunction.BINDER
    )
    if total_binder == 0:
        return []  # covered by T1
    env = envelope_for(ComponentFunction.BINDER)
    if not env.contains(total_binder):
        return [
            RuleFinding(
                rule_id="T2",
                severity=Severity.WARNING,
                message=(
                    f"Total binder is {total_binder:.1f} %; typical envelope is "
                    f"{env.min_percent}-{env.max_percent} % ({env.notes})."
                ),
                reference=env.reference,
            )
        ]
    return []


def _rule_additive_envelopes(recipe: Recipe) -> list[RuleFinding]:
    """T3 — Each additive stays inside the per-function envelope."""
    findings: list[RuleFinding] = []
    per_function: dict[ComponentFunction, float] = {}
    for c in recipe.all_components:
        per_function[c.functional_role] = per_function.get(c.functional_role, 0.0) + c.mass_percent

    for func, total in per_function.items():
        env = envelope_for(func)
        if func in {
            ComponentFunction.BINDER,
            ComponentFunction.VEHICLE,
            ComponentFunction.SOLVENT,
            ComponentFunction.PIGMENT,
            ComponentFunction.EXTENDER,
            ComponentFunction.UNSPECIFIED,
        }:
            # Structural components — covered by dedicated rules.
            continue
        if env.max_percent >= 100.0:
            continue  # nothing to check
        if total > env.max_percent:
            # A modest overdose is a warning; a gross overdose (≥ 5× the
            # typical maximum) is almost certainly a labelling mistake or
            # a broken formulation and gets flagged as an ERROR so it
            # cannot slip through to production.
            gross_overdose = env.max_percent > 0 and total >= env.max_percent * 5.0
            severity = Severity.ERROR if gross_overdose else Severity.WARNING
            findings.append(
                RuleFinding(
                    rule_id="T3",
                    severity=severity,
                    message=(
                        f"{func.value} totals {total:.2f} % — "
                        f"{'≥ 5× above' if gross_overdose else 'above'} typical maximum "
                        f"{env.max_percent} %. {env.notes}"
                    ),
                    reference=env.reference,
                )
            )
        elif total < env.min_percent and total > 0:
            findings.append(
                RuleFinding(
                    rule_id="T3",
                    severity=Severity.INFO,
                    message=(
                        f"{func.value} totals only {total:.3f} % — below typical minimum "
                        f"{env.min_percent} %. Consider whether the additive will be effective."
                    ),
                    reference=env.reference,
                )
            )
    return findings


def _rule_biocide_required(recipe: Recipe) -> list[RuleFinding]:
    """T4 — Water-based systems should carry an in-can biocide."""
    is_water_based = any(
        c.functional_role is ComponentFunction.VEHICLE and "water" in c.name.lower()
        for c in recipe.all_components
    )
    if not is_water_based:
        return []
    biocides = [
        c for c in recipe.all_components if c.functional_role is ComponentFunction.IN_CAN_BIOCIDE
    ]
    if not biocides:
        return [
            RuleFinding(
                rule_id="T4",
                severity=Severity.WARNING,
                message="Water-based recipe has no IN_CAN_BIOCIDE — expect microbial spoilage.",
                reference="BPR — active substance list",
            )
        ]
    return []


def _rule_defoamer_required(recipe: Recipe) -> list[RuleFinding]:
    """T5 — Water-based recipes benefit from a defoamer."""
    is_water_based = any(
        c.functional_role is ComponentFunction.VEHICLE and "water" in c.name.lower()
        for c in recipe.all_components
    )
    if not is_water_based:
        return []
    defoamers = [
        c for c in recipe.all_components if c.functional_role is ComponentFunction.DEFOAMER
    ]
    if not defoamers:
        return [
            RuleFinding(
                rule_id="T5",
                severity=Severity.INFO,
                message="No DEFOAMER in a water-based recipe — foaming at production may occur.",
                reference="Byk-Chemie technical",
            )
        ]
    return []


def _rule_coalescent_when_needed(recipe: Recipe) -> list[RuleFinding]:
    """T6 — Emulsion binders with high Tg require a coalescent."""
    high_tg_binder = False
    for c in recipe.all_components:
        if c.functional_role is not ComponentFunction.BINDER:
            continue
        props = c.properties
        if props is None:
            continue
        tg = props.glass_transition_c
        mfft = props.minimum_film_forming_temp_c
        if (tg is not None and tg > 5.0) or (mfft is not None and mfft > 5.0):
            high_tg_binder = True
            break
    if not high_tg_binder:
        return []
    coalescents = [
        c for c in recipe.all_components if c.functional_role is ComponentFunction.COALESCENT
    ]
    if not coalescents:
        return [
            RuleFinding(
                rule_id="T6",
                severity=Severity.WARNING,
                message=(
                    "Binder Tg / MFFT is above 5 °C but no COALESCENT is present — "
                    "film formation at ambient temperature is likely to fail."
                ),
                reference="Vincentz ECH §5.4",
            )
        ]
    return []


def _rule_voc_ceiling(recipe: Recipe) -> list[RuleFinding]:
    """T7 — Formulation VOC must respect EU 2004/42/EC ceilings."""
    ceiling = voc_ceiling_for(recipe)
    if ceiling is None:
        return []
    # Only recipes carrying declared VOC content can be checked.
    voc_target = next(
        (t for t in recipe.target_properties if t.property_code == "voc_content"), None
    )
    if voc_target is None:
        return []
    if voc_target.target_value > ceiling:
        return [
            RuleFinding(
                rule_id="T7",
                severity=Severity.ERROR,
                message=(
                    f"Declared VOC {voc_target.target_value:.0f} g/L exceeds the EU 2004/42/EC "
                    f"ceiling for {recipe.category}/{recipe.subcategory}: {ceiling:.0f} g/L."
                ),
                reference="EU Directive 2004/42/EC, Annex II",
            )
        ]
    return []


def _rule_hardener_ratio(recipe: Recipe) -> list[RuleFinding]:
    """T8 — 2K systems (with HARDENER) need at least ~5 % hardener on binder."""
    binder_mass = sum(
        c.mass_percent
        for c in recipe.all_components
        if c.functional_role is ComponentFunction.BINDER
    )
    hardener_mass = sum(
        c.mass_percent
        for c in recipe.all_components
        if c.functional_role is ComponentFunction.HARDENER
    )
    if hardener_mass == 0 or binder_mass == 0:
        return []
    ratio = hardener_mass / binder_mass
    if ratio < 0.05:
        return [
            RuleFinding(
                rule_id="T8",
                severity=Severity.WARNING,
                message=(
                    f"Hardener/binder ratio {ratio:.2f} is very low. Confirm the exact "
                    "stoichiometry against the resin datasheet."
                ),
                reference="Wicks §12",
            )
        ]
    if ratio > 1.5:
        return [
            RuleFinding(
                rule_id="T8",
                severity=Severity.WARNING,
                message=(
                    f"Hardener/binder ratio {ratio:.2f} is unusually high — check for a "
                    "swapped label between binder and hardener."
                ),
                reference="Wicks §12",
            )
        ]
    return []


def _rule_solvent_and_water(recipe: Recipe) -> list[RuleFinding]:
    """T9 — A recipe should not mix >5 % water and >5 % organic solvent."""
    water = sum(
        c.mass_percent
        for c in recipe.all_components
        if c.functional_role is ComponentFunction.VEHICLE and "water" in c.name.lower()
    )
    org_solvent = sum(
        c.mass_percent
        for c in recipe.all_components
        if c.functional_role in {ComponentFunction.SOLVENT, ComponentFunction.COSOLVENT}
    )
    if water > 5.0 and org_solvent > 5.0:
        return [
            RuleFinding(
                rule_id="T9",
                severity=Severity.WARNING,
                message=(
                    f"Recipe carries {water:.1f} % water AND {org_solvent:.1f} % organic solvent. "
                    "Hybrid systems require deliberate design — verify."
                ),
                reference="Vincentz ECH §7",
            )
        ]
    return []


def _rule_ph_for_waterborne(recipe: Recipe) -> list[RuleFinding]:
    """T10 — Water-based recipes with acrylic emulsion should target pH 8.0-9.5."""
    is_water_based = any(
        c.functional_role is ComponentFunction.VEHICLE and "water" in c.name.lower()
        for c in recipe.all_components
    )
    if not is_water_based:
        return []
    has_acrylic = any(
        c.functional_role is ComponentFunction.BINDER
        and ("acryl" in c.name.lower() or "acryl" in (c.inci_name or "").lower())
        for c in recipe.all_components
    )
    if not has_acrylic:
        return []
    ph_target = next((t for t in recipe.target_properties if t.property_code == "ph"), None)
    if ph_target is None:
        return [
            RuleFinding(
                rule_id="T10",
                severity=Severity.INFO,
                message="No pH target declared for a water-based acrylic — recommended 8.0-9.5.",
                reference="Vincentz ECH §5.2",
            )
        ]
    if not (7.5 <= ph_target.target_value <= 10.0):
        return [
            RuleFinding(
                rule_id="T10",
                severity=Severity.WARNING,
                message=(
                    f"Target pH {ph_target.target_value:.1f} is outside the 7.5-10.0 window "
                    "typical for water-based acrylics."
                ),
                reference="Vincentz ECH §5.2",
            )
        ]
    return []


def _rule_component_count(recipe: Recipe) -> list[RuleFinding]:
    """T11 — A finished recipe usually needs at least 3 distinct components."""
    if len(recipe.all_components) < 3:
        return [
            RuleFinding(
                rule_id="T11",
                severity=Severity.WARNING,
                message="Fewer than 3 components — recipe looks incomplete for a coating.",
            )
        ]
    return []


def _rule_target_properties_declared(recipe: Recipe) -> list[RuleFinding]:
    """T12 — A candidate for Verified should declare at least a couple of targets."""
    if len(recipe.target_properties) == 0:
        return [
            RuleFinding(
                rule_id="T12",
                severity=Severity.INFO,
                message=(
                    "No target properties declared. Verified recipes should carry a lab spec "
                    "(hiding power, gloss, VOC, drying time, …)."
                ),
            )
        ]
    return []


def _rule_pigment_or_binder_only(recipe: Recipe) -> list[RuleFinding]:
    """T13 — Pure pigment / pure vehicle formulations are almost certainly wrong."""
    if len(recipe.all_components) < 2:
        return []
    roles = {c.functional_role for c in recipe.all_components}
    if roles == {ComponentFunction.PIGMENT}:
        return [
            RuleFinding(
                rule_id="T13",
                severity=Severity.ERROR,
                message="Recipe contains only pigments — this is not a formulation.",
            )
        ]
    return []


# Master list — the order determines emission order in the assessment.
_RULES = (
    _rule_binder_present,
    _rule_binder_dose,
    _rule_pigment_or_binder_only,
    _rule_additive_envelopes,
    _rule_biocide_required,
    _rule_defoamer_required,
    _rule_coalescent_when_needed,
    _rule_hardener_ratio,
    _rule_solvent_and_water,
    _rule_ph_for_waterborne,
    _rule_component_count,
    _rule_target_properties_declared,
    _rule_voc_ceiling,
)


def evaluate(recipe: Recipe) -> list[RuleFinding]:
    """Run every technological rule and return the aggregated findings."""
    findings: list[RuleFinding] = []
    for rule in _RULES:
        findings.extend(rule(recipe))
    return findings


__all__ = [
    "RuleFinding",
    "Severity",
    "evaluate",
    "voc_ceiling_for",
]
