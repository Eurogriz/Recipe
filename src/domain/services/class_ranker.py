"""Class Ranker domain service.

Algorithm for classifying a recipe into a product class
(SuperEconomy / Economy / Standard / Premium / SuperPremium / Industrial / Specialty)
based on multiple weighted factors.

Output:
- Recommended class
- Score breakdown (which factors contributed)
- Confidence (0..1)

This is a pure domain algorithm — no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..entities.recipe import Component, ProductClass, Recipe


class ClassFactor(str, Enum):
    """Factors considered in class ranking."""

    BINDER_QUALITY = "binder_quality"
    PIGMENT_QUALITY = "pigment_quality"
    FUNCTIONAL_ADDITIVES = "functional_additives"
    PREDICTED_PROPERTIES = "predicted_properties"
    COST_INDEX = "cost_index"


@dataclass(frozen=True, slots=True)
class ClassRanking:
    """Result of class ranking."""

    recommended_class: ProductClass
    confidence: float  # 0.0 .. 1.0
    factor_scores: dict[ClassFactor, float]  # 0.0 .. 1.0 per factor
    rationale: str


class ClassRanker:
    """Algorithm for classifying recipes by product class.

    Multi-criteria scoring with weighted sum.

    Default weights:
        - Binder quality: 30%
        - Pigment quality: 15%
        - Functional additives: 20%
        - Predicted properties: 25%
        - Cost index: 10% (optional)

    Total score normalized to 0..1, then mapped to product class:
        - 0.00-0.20: SuperEconomy
        - 0.20-0.40: Economy
        - 0.40-0.60: Standard
        - 0.60-0.80: Premium
        - 0.80-0.95: SuperPremium
        - 0.95+:   Specialty
    Note: Industrial class is assigned by business rule, not score.
    """

    # Default weights
    DEFAULT_WEIGHTS: dict[ClassFactor, float] = {
        ClassFactor.BINDER_QUALITY: 0.30,
        ClassFactor.PIGMENT_QUALITY: 0.15,
        ClassFactor.FUNCTIONAL_ADDITIVES: 0.20,
        ClassFactor.PREDICTED_PROPERTIES: 0.25,
        ClassFactor.COST_INDEX: 0.10,
    }

    # Score → class mapping (upper bounds are inclusive)
    CLASS_THRESHOLDS: tuple[tuple[float, ProductClass], ...] = (
        (0.20, ProductClass.SUPER_ECONOMY),
        (0.40, ProductClass.ECONOMY),
        (0.60, ProductClass.STANDARD),
        (0.80, ProductClass.PREMIUM),
        (0.95, ProductClass.SUPER_PREMIUM),
    )

    # Keywords indicating high-quality binder
    PREMIUM_BINDER_KEYWORDS: frozenset[str] = frozenset(
        {
            "acrylic", "polyurethane", "silicone", "fluoropolymer",
            "epoxy", "hybrid", "100% solids", "self-crosslinking",
        }
    )

    ECONOMY_BINDER_KEYWORDS: frozenset[str] = frozenset(
        {
            "pva", "pvoh", "styrene-butadiene", "vinyl acetate",
            "economy", "basic",
        }
    )

    # Keywords indicating premium additives
    PREMIUM_ADDITIVE_KEYWORDS: frozenset[str] = frozenset(
        {
            "hals", "uv-absorber", "biozide premium", "associative thickener",
            "defoamer premium", "coalescent premium", "rheology modifier",
        }
    )

    @classmethod
    def rank(
        cls,
        recipe: Recipe,
        cost_index: float | None = None,
        weights: dict[ClassFactor, float] | None = None,
    ) -> ClassRanking:
        """Rank the recipe and return recommended class.

        Args:
            recipe: The recipe to classify.
            cost_index: Relative cost index (0..1) where 1 is most expensive.
                        If None, cost_index factor is excluded from the weighted average.
            weights: Override default factor weights. Must sum to 1.0.

        Returns:
            ClassRanking with recommended class and rationale.
        """
        weights = weights or cls.DEFAULT_WEIGHTS.copy()
        cls._validate_weights(weights)

        # Compute individual factor scores (0..1 each)
        scores: dict[ClassFactor, float] = {
            ClassFactor.BINDER_QUALITY: cls._score_binder(recipe),
            ClassFactor.PIGMENT_QUALITY: cls._score_pigment(recipe),
            ClassFactor.FUNCTIONAL_ADDITIVES: cls._score_additives(recipe),
            ClassFactor.PREDICTED_PROPERTIES: cls._score_predicted_properties(recipe),
        }

        # Include cost_index if provided
        if cost_index is not None:
            scores[ClassFactor.COST_INDEX] = max(0.0, min(1.0, cost_index))
            total_weight = sum(weights.values())
        else:
            # Redistribute cost_index weight to other factors
            scores[ClassFactor.COST_INDEX] = 0.0
            total_weight = sum(v for k, v in weights.items() if k != ClassFactor.COST_INDEX)

        # Weighted sum
        weighted_sum = sum(scores[k] * weights.get(k, 0.0) for k in scores)
        total_score = weighted_sum / total_weight if total_weight > 0 else 0.0

        # Map to class
        recommended = cls._score_to_class(total_score)

        # Confidence: based on variance of factor scores
        if scores:
            avg = sum(scores.values()) / len(scores)
            variance = sum((s - avg) ** 2 for s in scores.values()) / len(scores)
            # Lower variance = higher confidence
            confidence = max(0.0, 1.0 - variance * 2)
        else:
            confidence = 0.0

        rationale = cls._build_rationale(scores, weights, recommended, total_score)

        return ClassRanking(
            recommended_class=recommended,
            confidence=confidence,
            factor_scores=scores,
            rationale=rationale,
        )

    @classmethod
    def _score_binder(cls, recipe: Recipe) -> float:
        """Score binder quality (0..1)."""
        binder_lower = recipe.binder_type.lower()

        # Count premium keywords in binder_type
        premium_hits = sum(1 for kw in cls.PREMIUM_BINDER_KEYWORDS if kw in binder_lower)
        economy_hits = sum(1 for kw in cls.ECONOMY_BINDER_KEYWORDS if kw in binder_lower)

        if premium_hits > 0:
            return min(1.0, 0.7 + 0.1 * premium_hits)
        if economy_hits > 0:
            return max(0.0, 0.3 - 0.1 * economy_hits)

        # Default (unknown binder type)
        return 0.5

    @classmethod
    def _score_pigment(cls, recipe: Recipe) -> float:
        """Score pigment quality (0..1) based on TiO2 content and notes."""
        # Find TiO2 component
        tio2_components = [
            c for c in recipe.all_components
            if "titanium dioxide" in c.name.lower() or "tio2" in c.name.lower() or c.cas_number == "13463-67-7"
        ]

        if not tio2_components:
            return 0.0

        total_tio2_pct = sum(c.mass_percent for c in tio2_components)

        # Rutile vs anatase (heuristic via notes)
        for c in tio2_components:
            notes_lower = c.notes.lower()
            if "rutile" in notes_lower:
                # Rutile is preferred — high score
                return min(1.0, 0.6 + total_tio2_pct / 30.0)
            if "anatase" in notes_lower:
                # Anatase is lower quality
                return max(0.0, 0.3 + total_tio2_pct / 50.0)

        # Default — assume rutile
        return min(1.0, 0.5 + total_tio2_pct / 30.0)

    @classmethod
    def _score_additives(cls, recipe: Recipe) -> float:
        """Score functional additives (0..1) based on presence of premium additives."""
        all_text = " ".join(
            c.name.lower() + " " + c.notes.lower() + " " + c.function.lower()
            for c in recipe.all_components
        )

        premium_hits = sum(1 for kw in cls.PREMIUM_ADDITIVE_KEYWORDS if kw in all_text)

        # Base score by number of components
        n_components = len(recipe.all_components)
        base = min(0.5, n_components / 20.0)  # 0.5 if 10+ components

        return min(1.0, base + 0.15 * premium_hits)

    @classmethod
    def _score_predicted_properties(cls, recipe: Recipe) -> float:
        """Score predicted properties (0..1).

        This is a placeholder — in MVP, full predicted properties come from
        the predictor module, not stored on Recipe entity directly.
        We use a neutral 0.5 default here.
        """
        # In full implementation, this would consume predicted_properties
        # from the recipe. For now, neutral.
        return 0.5

    @classmethod
    def _score_to_class(cls, score: float) -> ProductClass:
        """Map score to product class using thresholds."""
        for threshold, product_class in cls.CLASS_THRESHOLDS:
            if score <= threshold:
                return product_class
        # Above 0.95
        return ProductClass.SUPER_PREMIUM

    @classmethod
    def _validate_weights(cls, weights: dict[ClassFactor, float]) -> None:
        if not weights:
            raise ValueError("Weights cannot be empty")
        if any(w < 0 for w in weights.values()):
            raise ValueError(f"Weights cannot be negative: {weights}")

    @classmethod
    def _build_rationale(
        cls,
        scores: dict[ClassFactor, float],
        weights: dict[ClassFactor, float],
        recommended: ProductClass,
        total: float,
    ) -> str:
        """Build human-readable rationale."""
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top_factor, top_score = sorted_scores[0]
        bottom_factor, bottom_score = sorted_scores[-1]

        return (
            f"Recommended class: {recommended.value} (score: {total:.2f}). "
            f"Strongest factor: {top_factor.value} ({top_score:.2f}). "
            f"Weakest factor: {bottom_factor.value} ({bottom_score:.2f})."
        )
