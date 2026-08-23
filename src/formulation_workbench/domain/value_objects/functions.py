"""Component functions — enumerated, with per-function typical ranges.

The 1.0 line represented the "function" of a component as a free-text
string.  That made verification, validation, and generation guess-work.
This module replaces it with a controlled vocabulary plus per-function
concentration envelopes drawn from formulation textbooks.

Sources for the default envelopes:
    - Flick, E. W. — Water-Based Paint Formulations, Vols. 1-3 (Noyes).
    - Wicks, Z. — Organic Coatings: Science and Technology (Wiley, 4th ed.).
    - Vincentz — European Coatings Handbook (2nd ed.).
    - ГОСТ Р 52020-2003 (VOC labelling).

Numbers are advisory: they describe what a competent formulator would
typically use as a starting point, not a hard-and-fast law.  The
verification-rules layer consumes them via
:meth:`ComponentFunction.envelope`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ComponentFunction(str, Enum):
    """First-class function taxonomy for recipe components."""

    # ---- Vehicle / carrier ---------------------------------------------------
    VEHICLE = "vehicle"  # water, mineral spirits, etc.
    SOLVENT = "solvent"  # active solvent (dissolves resin)
    COSOLVENT = "cosolvent"  # improves solvency / flow
    COALESCENT = "coalescent"  # film-forming aid for latex

    # ---- Film former ---------------------------------------------------------
    BINDER = "binder"  # main resin
    HARDENER = "hardener"  # crosslinker (isocyanate, amine, …)
    PLASTICIZER = "plasticizer"

    # ---- Pigment & filler ----------------------------------------------------
    PIGMENT = "pigment"  # white/coloured (TiO2, Fe2O3, PB15…)
    EXTENDER = "extender"  # filler (CaCO3, talc, kaolin, silica)
    ANTICORROSIVE_PIGMENT = "anticorrosive_pigment"  # Zn phosphate, MIO, …

    # ---- Additives (functional) ---------------------------------------------
    DISPERSANT = "dispersant"
    WETTING_AGENT = "wetting_agent"
    DEFOAMER = "defoamer"
    RHEOLOGY_MODIFIER = "rheology_modifier"
    THICKENER = "thickener"
    LEVELING_AGENT = "leveling_agent"

    # ---- Additives (preservation) -------------------------------------------
    IN_CAN_BIOCIDE = "biocide"  # in-can preservation
    FILM_BIOCIDE = "film_biocide"  # dry-film fungicide / algaecide
    UV_STABILIZER = "uv_stabilizer"
    HALS = "hals"  # hindered amine light stabilizer
    ANTIOXIDANT = "antioxidant"

    # ---- Additives (misc) ---------------------------------------------------
    DRIER = "drier"  # Co, Zr, Ca octoate — for alkyds
    MATTING_AGENT = "matting_agent"
    ANTIFREEZE = "antifreeze"
    PH_MODIFIER = "ph_modifier"
    FLASH_RUST_INHIBITOR = "flash_rust_inhibitor"
    ANTI_SETTLING = "anti_settling"
    ANTI_SKINNING = "anti_skinning"

    # ---- Special / other ----------------------------------------------------
    ADDITIVE_OTHER = "additive_other"  # explicit catch-all for uncatalogued additives
    UNSPECIFIED = "unspecified"  # legacy import / uncategorised

    @classmethod
    def parse(cls, raw: str) -> ComponentFunction:
        """Accept free-text values from legacy data.

        Falls back to :attr:`UNSPECIFIED` for anything we do not recognise
        so that historical seed files keep loading without a hard failure.
        """
        needle = (raw or "").strip().lower().replace(" ", "_").replace("-", "_")
        for member in cls:
            if member.value == needle:
                return member
        # Best-effort synonyms.
        synonyms = {
            "solvent_carrier": cls.VEHICLE,
            "water": cls.VEHICLE,
            "resin": cls.BINDER,
            "polymer": cls.BINDER,
            "emulsion": cls.BINDER,
            "latex": cls.BINDER,
            "filler": cls.EXTENDER,
            "opaque": cls.PIGMENT,
            "tio2": cls.PIGMENT,
            "acid": cls.PH_MODIFIER,
            "base": cls.PH_MODIFIER,
            "amine": cls.PH_MODIFIER,
            "surfactant": cls.WETTING_AGENT,
        }
        return synonyms.get(needle, cls.UNSPECIFIED)


@dataclass(frozen=True, slots=True)
class FunctionEnvelope:
    """Typical concentration envelope for a :class:`ComponentFunction`.

    All figures are mass percents in the *finished formulation*
    (i.e. after everything sums to 100 %).  ``max_percent`` is treated
    as a soft warning threshold — the verification layer flags recipes
    that step outside the envelope, but never rejects them outright.
    """

    function: ComponentFunction
    min_percent: float
    max_percent: float
    notes: str = ""
    reference: str = ""
    is_required: bool = False  # is this function usually present?
    approved_forms: tuple[str, ...] = field(default_factory=tuple)

    def contains(self, mass_percent: float) -> bool:
        return self.min_percent <= mass_percent <= self.max_percent


# ---- Curated default envelopes --------------------------------------------
_ENVELOPES: dict[ComponentFunction, FunctionEnvelope] = {
    ComponentFunction.VEHICLE: FunctionEnvelope(
        function=ComponentFunction.VEHICLE,
        min_percent=0.0,
        max_percent=80.0,
        notes="Water-based systems typically 30-60 % water; solvent-based can be 30-55 %.",
        reference="Flick vol. 1, ch. 2",
        is_required=True,
    ),
    ComponentFunction.SOLVENT: FunctionEnvelope(
        function=ComponentFunction.SOLVENT,
        min_percent=0.0,
        max_percent=70.0,
        notes="Only in solvent-based systems.",
        reference="Wicks, ch. 21",
    ),
    ComponentFunction.COALESCENT: FunctionEnvelope(
        function=ComponentFunction.COALESCENT,
        min_percent=0.5,
        max_percent=3.0,
        notes="Rule of thumb: 5-15 % on binder solids, adjusted for Tg.",
        reference="Vincentz ECH, §5.4",
    ),
    ComponentFunction.BINDER: FunctionEnvelope(
        function=ComponentFunction.BINDER,
        min_percent=8.0,
        max_percent=60.0,
        notes="Below 8 % — insufficient film formation; above 60 % — usually a pure varnish.",
        reference="Wicks, ch. 3",
        is_required=True,
    ),
    ComponentFunction.HARDENER: FunctionEnvelope(
        function=ComponentFunction.HARDENER,
        min_percent=1.0,
        max_percent=40.0,
        notes="Stoichiometric ratio to binder is the governing constraint.",
        reference="Wicks, ch. 12",
    ),
    ComponentFunction.PIGMENT: FunctionEnvelope(
        function=ComponentFunction.PIGMENT,
        min_percent=0.0,
        max_percent=45.0,
        notes="Pigmentation depends on hiding target; 12-25 % TiO2 typical for whites.",
        reference="Wicks, ch. 5",
    ),
    ComponentFunction.EXTENDER: FunctionEnvelope(
        function=ComponentFunction.EXTENDER,
        min_percent=0.0,
        max_percent=35.0,
        notes="Combined with pigments defines PVC.",
        reference="Wicks, ch. 5",
    ),
    ComponentFunction.ANTICORROSIVE_PIGMENT: FunctionEnvelope(
        function=ComponentFunction.ANTICORROSIVE_PIGMENT,
        min_percent=2.0,
        max_percent=20.0,
        notes="Zinc phosphate / MIO / calcium exchanged silica.",
        reference="Vincentz Anticorrosive Coatings",
    ),
    ComponentFunction.DISPERSANT: FunctionEnvelope(
        function=ComponentFunction.DISPERSANT,
        min_percent=0.1,
        max_percent=2.5,
        notes="Typically ~1 % on total pigment, ~0.5 % on formulation.",
        reference="BASF Dispex technical",
    ),
    ComponentFunction.WETTING_AGENT: FunctionEnvelope(
        function=ComponentFunction.WETTING_AGENT,
        min_percent=0.05,
        max_percent=1.5,
    ),
    ComponentFunction.DEFOAMER: FunctionEnvelope(
        function=ComponentFunction.DEFOAMER,
        min_percent=0.05,
        max_percent=0.8,
        notes="Overdose causes cratering and fisheyes.",
    ),
    ComponentFunction.RHEOLOGY_MODIFIER: FunctionEnvelope(
        function=ComponentFunction.RHEOLOGY_MODIFIER,
        min_percent=0.05,
        max_percent=1.5,
    ),
    ComponentFunction.THICKENER: FunctionEnvelope(
        function=ComponentFunction.THICKENER,
        min_percent=0.1,
        max_percent=2.0,
    ),
    ComponentFunction.LEVELING_AGENT: FunctionEnvelope(
        function=ComponentFunction.LEVELING_AGENT,
        min_percent=0.05,
        max_percent=1.0,
    ),
    ComponentFunction.IN_CAN_BIOCIDE: FunctionEnvelope(
        function=ComponentFunction.IN_CAN_BIOCIDE,
        min_percent=0.05,
        max_percent=0.4,
        notes="Typical isothiazolinone dose 0.1-0.2 %.",
        reference="BPR — active substance list",
    ),
    ComponentFunction.FILM_BIOCIDE: FunctionEnvelope(
        function=ComponentFunction.FILM_BIOCIDE,
        min_percent=0.1,
        max_percent=1.5,
    ),
    ComponentFunction.UV_STABILIZER: FunctionEnvelope(
        function=ComponentFunction.UV_STABILIZER,
        min_percent=0.05,
        max_percent=1.5,
    ),
    ComponentFunction.HALS: FunctionEnvelope(
        function=ComponentFunction.HALS,
        min_percent=0.1,
        max_percent=1.5,
    ),
    ComponentFunction.ANTIOXIDANT: FunctionEnvelope(
        function=ComponentFunction.ANTIOXIDANT,
        min_percent=0.05,
        max_percent=1.0,
    ),
    ComponentFunction.DRIER: FunctionEnvelope(
        function=ComponentFunction.DRIER,
        min_percent=0.05,
        max_percent=1.2,
        notes="Balanced Co/Zr/Ca system typical for alkyds.",
        reference="ГОСТ 5972-77",
    ),
    ComponentFunction.MATTING_AGENT: FunctionEnvelope(
        function=ComponentFunction.MATTING_AGENT,
        min_percent=0.5,
        max_percent=6.0,
    ),
    ComponentFunction.ANTIFREEZE: FunctionEnvelope(
        function=ComponentFunction.ANTIFREEZE,
        min_percent=1.0,
        max_percent=5.0,
        notes="Propylene glycol / ethylene glycol; check VOC classification.",
    ),
    ComponentFunction.PH_MODIFIER: FunctionEnvelope(
        function=ComponentFunction.PH_MODIFIER,
        min_percent=0.05,
        max_percent=1.0,
    ),
    ComponentFunction.FLASH_RUST_INHIBITOR: FunctionEnvelope(
        function=ComponentFunction.FLASH_RUST_INHIBITOR,
        min_percent=0.1,
        max_percent=1.0,
    ),
    ComponentFunction.ANTI_SETTLING: FunctionEnvelope(
        function=ComponentFunction.ANTI_SETTLING,
        min_percent=0.1,
        max_percent=1.5,
    ),
    ComponentFunction.ANTI_SKINNING: FunctionEnvelope(
        function=ComponentFunction.ANTI_SKINNING,
        min_percent=0.05,
        max_percent=0.5,
    ),
    ComponentFunction.PLASTICIZER: FunctionEnvelope(
        function=ComponentFunction.PLASTICIZER,
        min_percent=0.5,
        max_percent=10.0,
    ),
    ComponentFunction.COSOLVENT: FunctionEnvelope(
        function=ComponentFunction.COSOLVENT,
        min_percent=0.5,
        max_percent=15.0,
    ),
    ComponentFunction.ADDITIVE_OTHER: FunctionEnvelope(
        function=ComponentFunction.ADDITIVE_OTHER,
        min_percent=0.0,
        max_percent=5.0,
    ),
    ComponentFunction.UNSPECIFIED: FunctionEnvelope(
        function=ComponentFunction.UNSPECIFIED,
        min_percent=0.0,
        max_percent=100.0,
    ),
}


def envelope_for(func: ComponentFunction) -> FunctionEnvelope:
    """Return the canonical envelope for a function (never raises)."""
    return _ENVELOPES.get(func, _ENVELOPES[ComponentFunction.UNSPECIFIED])


__all__ = ["ComponentFunction", "FunctionEnvelope", "envelope_for"]
