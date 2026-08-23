"""REACH / SVHC compliance checker.

The reference lists used here are curated snapshots of the ECHA
"Candidate List of substances of very high concern" (Annex XIV entry
process) and a small selection of REACH Annex XVII restrictions
relevant to paints and coatings.  The lists are intentionally not
exhaustive — they establish the *shape* of the check, and can be
extended by loading a full CSV in the future.

Nothing in this module performs I/O; the reference tables are
constants.  A callable can override them at instantiation time (useful
for tests or for injecting a fresh ECHA export).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..entities.recipe import Recipe


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class RegulatoryFinding:
    rule_id: str
    severity: Severity
    substance: str
    cas_number: str
    message: str
    reference: str = ""


@dataclass(frozen=True, slots=True)
class SubstanceRestriction:
    """One row in a restriction list."""

    cas_number: str
    name: str
    max_concentration_percent: float | None = None  # None = fully forbidden
    scope: str = "general"  # "toys", "consumer", "professional_only", "general"
    reference: str = ""


# ==============================================================================
# Curated snapshots (partial; ~40 entries).  In production these can be loaded
# from CSV in ``data/regulatory/*.csv`` shipped with the release.
# ==============================================================================
# ECHA SVHC candidate list — a representative sample.
_SVHC_CANDIDATES: tuple[SubstanceRestriction, ...] = (
    SubstanceRestriction(
        "1163-19-5", "Decabromodiphenyl ether (decaBDE)", reference="ECHA candidate list 2012-12-19"
    ),
    SubstanceRestriction(
        "117-81-7", "Bis(2-ethylhexyl) phthalate (DEHP)", reference="ECHA candidate list 2008-10-28"
    ),
    SubstanceRestriction(
        "84-74-2", "Dibutyl phthalate (DBP)", reference="ECHA candidate list 2008-10-28"
    ),
    SubstanceRestriction(
        "85-68-7", "Benzyl butyl phthalate (BBP)", reference="ECHA candidate list 2008-10-28"
    ),
    SubstanceRestriction(
        "84-69-5", "Diisobutyl phthalate (DIBP)", reference="ECHA candidate list 2010-01-13"
    ),
    SubstanceRestriction(
        "107-06-2", "1,2-Dichloroethane (EDC)", reference="ECHA candidate list 2010-06-18"
    ),
    SubstanceRestriction(
        "111-15-9", "2-Ethoxyethyl acetate", reference="ECHA candidate list 2011-12-19"
    ),
    SubstanceRestriction("110-80-5", "2-Ethoxyethanol", reference="ECHA candidate list 2011-12-19"),
    SubstanceRestriction(
        "110-71-4", "1,2-Dimethoxyethane (EGDME)", reference="ECHA candidate list 2012-12-19"
    ),
    SubstanceRestriction(
        "140-66-9", "4-tert-Octylphenol", reference="ECHA candidate list 2011-12-19"
    ),
    SubstanceRestriction(
        "25637-99-4", "Hexabromocyclododecane (HBCDD)", reference="ECHA candidate list 2008-10-28"
    ),
    SubstanceRestriction("50-00-0", "Formaldehyde", reference="ECHA candidate list 2019-06-27"),
    SubstanceRestriction("7439-92-1", "Lead", reference="ECHA candidate list 2018-06-27"),
    SubstanceRestriction("7440-43-9", "Cadmium", reference="ECHA candidate list 2018-06-27"),
    SubstanceRestriction("7440-38-2", "Arsenic", reference="ECHA candidate list 2018-06-27"),
    SubstanceRestriction("108-95-2", "Phenol", reference="ECHA candidate list 2019-06-27"),
    SubstanceRestriction("110-83-8", "Cyclohexane", reference="Precautionary — check use"),
    SubstanceRestriction("108-88-3", "Toluene", reference="Reprotoxic Cat. 2 — CLP"),
    SubstanceRestriction(
        "1330-20-7", "Xylene", reference="Under evaluation, community rolling action plan"
    ),
    SubstanceRestriction("71-43-2", "Benzene", reference="Annex XVII — restricted"),
)

# REACH Annex XVII — restrictions actually applicable to coatings.
_ANNEX_XVII: tuple[SubstanceRestriction, ...] = (
    SubstanceRestriction(
        "71-43-2",
        "Benzene",
        max_concentration_percent=0.1,
        scope="general",
        reference="REACH Annex XVII entry 5",
    ),
    SubstanceRestriction(
        "7439-92-1",
        "Lead",
        max_concentration_percent=0.03,
        scope="general",
        reference="REACH Annex XVII entry 63",
    ),
    SubstanceRestriction(
        "7440-43-9",
        "Cadmium",
        max_concentration_percent=0.01,
        scope="general",
        reference="REACH Annex XVII entry 23",
    ),
    SubstanceRestriction(
        "7440-38-2",
        "Arsenic",
        max_concentration_percent=0.0,
        scope="general",
        reference="REACH Annex XVII entry 19",
    ),
    SubstanceRestriction(
        "50-00-0",
        "Formaldehyde",
        max_concentration_percent=0.1,
        scope="consumer",
        reference="REACH Annex XVII entry 77",
    ),
    SubstanceRestriction(
        "117-81-7",
        "Bis(2-ethylhexyl) phthalate (DEHP)",
        max_concentration_percent=0.1,
        scope="consumer",
        reference="REACH Annex XVII entry 51",
    ),
    SubstanceRestriction(
        "108-88-3",
        "Toluene",
        max_concentration_percent=0.1,
        scope="consumer",
        reference="REACH Annex XVII entry 48",
    ),
    SubstanceRestriction(
        "110-80-5",
        "2-Ethoxyethanol",
        max_concentration_percent=0.5,
        scope="general",
        reference="REACH Annex XVII entry 30 (CMR)",
    ),
)


def _index_by_cas(rows: tuple[SubstanceRestriction, ...]) -> dict[str, SubstanceRestriction]:
    return {r.cas_number.strip(): r for r in rows}


class RegulatoryComplianceChecker:
    """Check a :class:`Recipe` against REACH candidate + Annex XVII lists.

    Injection of alternative lists (``svhc_list`` / ``annex_xvii_list``)
    is intended primarily for tests and for keeping the checker current
    without a release.
    """

    def __init__(
        self,
        svhc_list: tuple[SubstanceRestriction, ...] | None = None,
        annex_xvii_list: tuple[SubstanceRestriction, ...] | None = None,
    ) -> None:
        self._svhc = _index_by_cas(svhc_list or _SVHC_CANDIDATES)
        self._annex = _index_by_cas(annex_xvii_list or _ANNEX_XVII)

    # ------------------------------------------------------------------ API
    def check(self, recipe: Recipe, *, consumer_use: bool = True) -> list[RegulatoryFinding]:
        findings: list[RegulatoryFinding] = []
        for component in recipe.all_components:
            cas = (component.cas_number or "").strip()
            if cas in {"mixture", "proprietary", "unspecified", ""}:
                continue

            # SVHC candidate list — always info+ (labelling / declaration).
            svhc = self._svhc.get(cas)
            if svhc is not None:
                findings.append(
                    RegulatoryFinding(
                        rule_id="REACH-SVHC",
                        severity=Severity.WARNING,
                        substance=svhc.name,
                        cas_number=cas,
                        message=(
                            f"{svhc.name} ({cas}) is on the ECHA SVHC candidate list; "
                            f"safety data sheet and Article 33 information duty apply "
                            f"if > 0.1 % w/w in the finished article."
                        ),
                        reference=svhc.reference,
                    )
                )

            # Annex XVII — proper limit check.
            restriction = self._annex.get(cas)
            if restriction is None:
                continue

            if restriction.scope == "consumer" and not consumer_use:
                # Professional-only exemptions can apply.
                findings.append(
                    RegulatoryFinding(
                        rule_id="REACH-XVII-INFO",
                        severity=Severity.INFO,
                        substance=restriction.name,
                        cas_number=cas,
                        message=(
                            f"{restriction.name} carries a consumer-scope restriction. "
                            f"Recipe is flagged as professional_only=True; verify labelling."
                        ),
                        reference=restriction.reference,
                    )
                )
                continue

            limit = restriction.max_concentration_percent
            if limit is None:
                # Prohibited outright.
                findings.append(
                    RegulatoryFinding(
                        rule_id="REACH-XVII",
                        severity=Severity.ERROR,
                        substance=restriction.name,
                        cas_number=cas,
                        message=f"{restriction.name} is banned by REACH Annex XVII.",
                        reference=restriction.reference,
                    )
                )
                continue

            if component.mass_percent > limit:
                findings.append(
                    RegulatoryFinding(
                        rule_id="REACH-XVII",
                        severity=Severity.ERROR,
                        substance=restriction.name,
                        cas_number=cas,
                        message=(
                            f"{restriction.name}: {component.mass_percent:.3f} % exceeds "
                            f"REACH Annex XVII limit {limit:.3f} % ({restriction.scope} scope)."
                        ),
                        reference=restriction.reference,
                    )
                )
        return findings


__all__ = [
    "RegulatoryComplianceChecker",
    "RegulatoryFinding",
    "Severity",
    "SubstanceRestriction",
]
