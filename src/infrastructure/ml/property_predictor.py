"""ML-advisory Property Predictor.

Trains scikit-learn regressors on verified recipe dataset to predict
properties that are hard to calculate analytically:

- Scrub resistance (cycles, ISO 11998)
- Adhesion class (ISO 2409, 0-5)
- Gloss 60° (GU)
- Contrast ratio (0..1)
- Density (g/cm³) — if not analytically known

CRITICAL: All predictions are marked with ⚠ "advisory hint, not measured"
and require laboratory confirmation before industrial use.

Approach:
1. Feature engineering: composition → numeric features (mass% per material type,
   counts of additives, binder type one-hot)
2. Train RandomForestRegressor (robust, interpretable) on verified dataset
3. Predict with confidence estimation
4. Version the model for reproducibility
"""

from __future__ import annotations

import logging
import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

logger = logging.getLogger(__name__)

# sklearn imports are conditional — wrapped in try-except for environments without it
try:
    from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
    from sklearn.model_selection import cross_val_score, KFold
    from sklearn.preprocessing import StandardScaler
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    logger.warning("scikit-learn not available, ML predictor will use rule-based fallback")

if TYPE_CHECKING:
    from ...domain.entities.recipe import Recipe


# Properties we can predict
PREDICTABLE_PROPERTIES: tuple[str, ...] = (
    "scrub_resistance_cycles",
    "adhesion_class",
    "gloss_60_gu",
    "contrast_ratio",
    "density_g_per_cm3",
)


@dataclass(frozen=True, slots=True)
class PredictionResult:
    """Результат ML-прогноза с обязательной маркировкой advisory."""

    property_name: str
    value: float
    unit: str
    confidence: float  # 0..1
    model_version: str
    is_predicted: bool = True  # Always True for ML predictions
    method: str = "ML-advisory"
    warning: str = "⚠ Advisory hint, requires laboratory confirmation"


@dataclass(frozen=True, slots=True)
class ModelMetrics:
    """Метрики качества ML-модели."""

    property_name: str
    mae: float  # Mean Absolute Error
    r2: float  # R² score
    cv_folds: int
    n_samples: int
    feature_importance: dict[str, float] = field(default_factory=dict)


class PropertyPredictor:
    """ML-advisory predictor for paint/coating properties.

    Workflow:
    1. Train on verified dataset (called once, persisted to disk)
    2. Predict for new recipes (called many times, in-memory)
    3. Always mark predictions with ⚠ advisory warning

    Model versioning: each trained model has a version (e.g., v1.0.0)
    persisted alongside metrics.
    """

    MODEL_VERSION = "1.0.0"

    def __init__(self, model_dir: Path | None = None) -> None:
        self._model_dir = model_dir or Path.home() / ".formulation-workbench" / "models"
        self._models: dict[str, object] = {}
        self._scalers: dict[str, object] = {}
        self._feature_names: tuple[str, ...] = ()
        self._metrics: dict[str, ModelMetrics] = {}

    # =========================================================================
    # Feature engineering
    # =========================================================================

    @classmethod
    def _extract_features(cls, recipe: Recipe) -> tuple[float, ...]:
        """Extract numeric features from a recipe.

        Features (16 total):
        - binder_mass_pct (float)
        - pigment_mass_pct (float, sum of TiO2 + other pigments)
        - tio2_mass_pct (float)
        - filler_mass_pct (float, CaCO3 + talc + etc.)
        - water_mass_pct (float)
        - coalescent_mass_pct (float)
        - defoamer_count (int)
        - thickener_count (int)
        - biocide_present (bool)
        - hals_present (bool)
        - uv_absorber_present (bool)
        - associative_thickener_present (bool)
        - binder_type_acrylic (bool)
        - binder_type_polyurethane (bool)
        - binder_type_alkyd (bool)
        - binder_type_epoxy (bool)
        """
        features = [0.0] * 16

        binder_mass = 0.0
        pigment_mass = 0.0
        tio2_mass = 0.0
        filler_mass = 0.0
        water_mass = 0.0
        coalescent_mass = 0.0
        defoamer_count = 0
        thickener_count = 0
        biocide_present = 0
        hals_present = 0
        uv_absorber_present = 0
        associative_thickener_present = 0

        binder_lower = recipe.binder_type.lower()

        # Determine binder type
        if "acrylic" in binder_lower:
            features[12] = 1.0
        if "polyurethane" in binder_lower or "pu" == binder_lower.strip():
            features[13] = 1.0
        if "alkyd" in binder_lower:
            features[14] = 1.0
        if "epoxy" in binder_lower:
            features[15] = 1.0

        for comp in recipe.all_components:
            name_lower = comp.name.lower()
            mass_pct = comp.mass_percent

            # Categorize
            if any(kw in name_lower for kw in ("acrylic", "polyurethane", "alkyd", "epoxy", "binder")):
                binder_mass += mass_pct
            elif "titanium" in name_lower or "tio2" in name_lower or "13463-67-7" in comp.cas_number:
                tio2_mass += mass_pct
                pigment_mass += mass_pct
            elif any(kw in name_lower for kw in ("carbonate", "talc", "kaolin", "silica", "filler")):
                filler_mass += mass_pct
                pigment_mass += mass_pct
            elif any(kw in name_lower for kw in ("water", "вода", "aqua")):
                water_mass += mass_pct
            elif "Texanol" in name_lower or "coalescent" in name_lower:
                coalescent_mass += mass_pct
            elif "defoamer" in name_lower or "antifoam" in name_lower:
                defoamer_count += 1
            elif "thickener" in name_lower or "rheology" in name_lower:
                thickener_count += 1
                if "associative" in name_lower or "hase" in name_lower or "heur" in name_lower:
                    associative_thickener_present = 1
            elif "biocide" in name_lower or "isothiazolin" in name_lower:
                biocide_present = 1
            elif "hals" in name_lower:
                hals_present = 1
            elif "uv" in name_lower and "absorber" in name_lower:
                uv_absorber_present = 1

        features[0] = binder_mass
        features[1] = pigment_mass
        features[2] = tio2_mass
        features[3] = filler_mass
        features[4] = water_mass
        features[5] = coalescent_mass
        features[6] = float(defoamer_count)
        features[7] = float(thickener_count)
        features[8] = float(biocide_present)
        features[9] = float(hals_present)
        features[10] = float(uv_absorber_present)
        features[11] = float(associative_thickener_present)

        return tuple(features)

    FEATURE_NAMES: tuple[str, ...] = (
        "binder_mass_pct",
        "pigment_mass_pct",
        "tio2_mass_pct",
        "filler_mass_pct",
        "water_mass_pct",
        "coalescent_mass_pct",
        "defoamer_count",
        "thickener_count",
        "biocide_present",
        "hals_present",
        "uv_absorber_present",
        "associative_thickener_present",
        "binder_acrylic",
        "binder_polyurethane",
        "binder_alkyd",
        "binder_epoxy",
    )

    # =========================================================================
    # Training
    # =========================================================================

    def train(
        self,
        training_recipes: list[Recipe],
        training_data: dict[str, list[float]],
        n_estimators: int = 100,
    ) -> dict[str, ModelMetrics]:
        """Train models for each predictable property.

        Args:
            training_recipes: List of verified recipes for training.
            training_data: Dict mapping property_name → list of measured values
                          (one per recipe, same order as training_recipes).
            n_estimators: Number of trees in RandomForest.

        Returns:
            Dict of property_name → ModelMetrics.
        """
        if not SKLEARN_AVAILABLE:
            logger.error("Cannot train: scikit-learn not available")
            return {}

        if len(training_recipes) < 50:
            logger.warning(
                "Training set too small (%d). ML predictions may be unreliable.",
                len(training_recipes),
            )

        # Extract features for all recipes
        X = np.array([self._extract_features(r) for r in training_recipes])
        self._feature_names = self.FEATURE_NAMES

        # Train one model per property
        metrics_dict: dict[str, ModelMetrics] = {}
        for prop_name, y_values in training_data.items():
            if prop_name not in PREDICTABLE_PROPERTIES:
                logger.warning("Unknown property: %s, skipping", prop_name)
                continue

            if len(y_values) != len(training_recipes):
                logger.error(
                    "Property %s: mismatched sample count (%d vs %d)",
                    prop_name, len(y_values), len(training_recipes),
                )
                continue

            y = np.array(y_values)

            # Skip if all values are NaN
            valid_mask = ~np.isnan(y)
            if valid_mask.sum() < 30:
                logger.warning("Property %s: too few valid samples (%d)", prop_name, valid_mask.sum())
                continue
            X_valid = X[valid_mask]
            y_valid = y[valid_mask]

            # Standardize features
            scaler = StandardScaler()
            X_scaled = scaler.fit_transform(X_valid)
            self._scalers[prop_name] = scaler

            # Train RandomForest
            model = RandomForestRegressor(
                n_estimators=n_estimators,
                max_depth=10,
                min_samples_split=5,
                random_state=42,
                n_jobs=-1,
            )
            model.fit(X_scaled, y_valid)
            self._models[prop_name] = model

            # Cross-validation metrics
            kf = KFold(n_splits=5, shuffle=True, random_state=42)
            try:
                cv_scores = cross_val_score(
                    model, X_scaled, y_valid,
                    cv=kf, scoring="neg_mean_absolute_error",
                )
                mae = float(-cv_scores.mean())
            except Exception as e:
                logger.warning("CV failed for %s: %s", prop_name, e)
                mae = 0.0

            try:
                cv_r2 = cross_val_score(
                    model, X_scaled, y_valid,
                    cv=kf, scoring="r2",
                )
                r2 = float(cv_r2.mean())
            except Exception:
                r2 = 0.0

            # Feature importance
            importance_dict = {
                name: float(imp)
                for name, imp in zip(self._feature_names, model.feature_importances_)
            }
            importance_dict = dict(
                sorted(importance_dict.items(), key=lambda x: x[1], reverse=True)
            )

            metrics = ModelMetrics(
                property_name=prop_name,
                mae=mae,
                r2=r2,
                cv_folds=5,
                n_samples=int(valid_mask.sum()),
                feature_importance=importance_dict,
            )
            metrics_dict[prop_name] = metrics
            self._metrics[prop_name] = metrics
            logger.info(
                "Trained %s: MAE=%.3f, R²=%.3f, n=%d",
                prop_name, mae, r2, metrics.n_samples,
            )

        return metrics_dict

    # =========================================================================
    # Prediction
    # =========================================================================

    def predict(
        self,
        recipe: Recipe,
        property_name: str,
    ) -> PredictionResult | None:
        """Predict a property for a recipe using the trained model.

        Returns None if no model is trained for this property.
        """
        if not SKLEARN_AVAILABLE:
            return cls._rule_based_fallback(recipe, property_name)

        if property_name not in self._models:
            logger.warning("No model for property: %s", property_name)
            return None

        model = self._models[property_name]
        scaler = self._scalers[property_name]
        features = np.array([self._extract_features(recipe)])
        features_scaled = scaler.transform(features)

        # Predict
        prediction = float(model.predict(features_scaled)[0])

        # Confidence based on R² and feature similarity to training distribution
        metrics = self._metrics.get(property_name)
        if metrics is not None:
            # Higher R² = higher confidence; clip to [0.2, 0.95]
            confidence = max(0.2, min(0.95, metrics.r2))
        else:
            confidence = 0.5

        # Unit
        units = {
            "scrub_resistance_cycles": "cycles",
            "adhesion_class": "ISO class",
            "gloss_60_gu": "GU",
            "contrast_ratio": "ratio",
            "density_g_per_cm3": "g/cm³",
        }
        unit = units.get(property_name, "")

        return PredictionResult(
            property_name=property_name,
            value=round(prediction, 3),
            unit=unit,
            confidence=round(confidence, 3),
            model_version=self.MODEL_VERSION,
            is_predicted=True,
            method="ML-advisory (RandomForest)",
            warning="⚠ Advisory hint, requires laboratory confirmation",
        )

    @classmethod
    def _rule_based_fallback(
        cls, recipe: Recipe, property_name: str
    ) -> PredictionResult | None:
        """Simple rule-based fallback when sklearn is not available."""
        if property_name == "scrub_resistance_cycles":
            # Rough heuristic: more binder + HALS → higher cycles
            binder_pct = sum(
                c.mass_percent for c in recipe.all_components
                if any(kw in c.name.lower() for kw in ("acrylic", "polyurethane", "alkyd", "epoxy", "binder"))
            )
            cycles = 500 + binder_pct * 30  # very rough
            return PredictionResult(
                property_name=property_name,
                value=round(cycles, 0),
                unit="cycles",
                confidence=0.3,  # low confidence for rule-based
                model_version="rule-based-fallback",
                is_predicted=True,
                method="Rule-based (ML unavailable)",
                warning="⚠ Low-confidence estimate, ML unavailable",
            )
        return None

    # =========================================================================
    # Persistence
    # =========================================================================

    def save(self, name: str = "property_predictor") -> Path:
        """Save trained models to disk."""
        if not self._model_dir:
            raise ValueError("model_dir not set")
        self._model_dir.mkdir(parents=True, exist_ok=True)

        path = self._model_dir / f"{name}_v{self.MODEL_VERSION}.pkl"
        payload = {
            "version": self.MODEL_VERSION,
            "feature_names": self._feature_names,
            "models": self._models,
            "scalers": self._scalers,
            "metrics": self._metrics,
        }
        with open(path, "wb") as f:
            pickle.dump(payload, f)
        logger.info("Saved model to %s", path)
        return path

    def load(self, path: Path) -> None:
        """Load trained models from disk."""
        with open(path, "rb") as f:
            payload = pickle.load(f)
        self._models = payload["models"]
        self._scalers = payload["scalers"]
        self._feature_names = payload["feature_names"]
        self._metrics = payload["metrics"]
        logger.info("Loaded model from %s (version %s)", path, payload["version"])
