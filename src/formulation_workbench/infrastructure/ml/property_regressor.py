"""Property regressor: learn ``Recipe → measured property value``.

Trains one small model per property code (gloss_60, viscosity_mid_shear,
…) using RandomForest regression on the features from
:mod:`.features`.  RandomForest is a defensible default for our regime:
tens to hundreds of samples, mixed-scale features, no assumption of
linearity, and free from feature scaling headaches.

Model metadata (version, feature names, cross-validation score, number
of samples) is stored side-by-side with the pickled sklearn object so
predictions cannot silently drift when the training set evolves.
"""

from __future__ import annotations

import hashlib
import json
import logging
import pickle
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from .features import FEATURE_NAMES, to_vector

if TYPE_CHECKING:
    from ...domain.entities.experiment import ExperimentRun
    from ...domain.entities.recipe import Recipe
    from .calibration import CalibrationBundle

logger = logging.getLogger(__name__)


class ModelUnavailableError(RuntimeError):
    """Raised when scikit-learn is not installed or training data is missing."""


@dataclass(frozen=True, slots=True)
class TrainingSample:
    property_code: str
    features: list[float]
    target: float
    recipe_id: str
    experiment_id: str


@dataclass(frozen=True, slots=True)
class ModelMetadata:
    """Everything a caller needs to trust and reload a model."""

    property_code: str
    version: str  # ISO timestamp — sortable + human-readable
    n_samples: int
    n_features: int
    feature_names: tuple[str, ...]
    cv_mean_r2: float
    cv_std_r2: float
    training_recipe_ids: tuple[str, ...]
    algorithm: str = "RandomForestRegressor"
    fingerprint: str = ""  # sha256 of the training data digest
    # ---- Optional held-out evaluation ---------------------------------
    # Populated when we can afford a train/holdout split (n_samples ≥ 30).
    # ``holdout_size`` is the number of samples the model never saw.
    holdout_r2: float | None = None
    holdout_mae: float | None = None
    holdout_size: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "property_code": self.property_code,
            "version": self.version,
            "n_samples": self.n_samples,
            "n_features": self.n_features,
            "feature_names": list(self.feature_names),
            "cv_mean_r2": self.cv_mean_r2,
            "cv_std_r2": self.cv_std_r2,
            "training_recipe_ids": list(self.training_recipe_ids),
            "algorithm": self.algorithm,
            "fingerprint": self.fingerprint,
            "holdout_r2": self.holdout_r2,
            "holdout_mae": self.holdout_mae,
            "holdout_size": self.holdout_size,
        }


@dataclass(frozen=True, slots=True)
class FeatureImpact:
    feature_name: str
    contribution: float
    baseline_value: float
    global_importance: float


@dataclass(frozen=True, slots=True)
class PropertyPrediction:
    property_code: str
    predicted_value: float
    model_version: str
    model_cv_r2: float
    unit: str = ""
    # Uncertainty descriptors — populated when the underlying model
    # is an ensemble that can report per-tree quantiles.
    lower_bound: float | None = None
    upper_bound: float | None = None
    interval_alpha: float | None = None
    # Top-k explanation of what drove the prediction.  Empty when
    # explain=False or the model doesn't support attribution.
    top_features: tuple[FeatureImpact, ...] = ()


@dataclass(frozen=True, slots=True)
class TrainingResult:
    """What :meth:`PropertyRegressor.train` returns."""

    trained: tuple[ModelMetadata, ...] = field(default_factory=tuple)
    skipped: dict[str, str] = field(default_factory=dict)  # property_code → reason


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------
def build_training_samples(
    experiments: list[ExperimentRun],
    recipes: dict[str, Recipe],
) -> list[TrainingSample]:
    """Flatten completed experiments into ``(property_code, X, y)`` triples."""
    samples: list[TrainingSample] = []
    for run in experiments:
        if run.verdict is None:
            continue
        recipe = recipes.get(run.recipe_id)
        if recipe is None:
            continue
        vector = to_vector(recipe)
        for mv in run.measured_properties:
            samples.append(
                TrainingSample(
                    property_code=mv.property_code,
                    features=vector,
                    target=mv.value,
                    recipe_id=recipe.id,
                    experiment_id=run.id,
                )
            )
    return samples


def _valid_property_code(code: str) -> bool:
    return bool(re.match(r"^[a-z][a-z0-9_]{1,60}$", code))


# ---------------------------------------------------------------------------
# Regressor
# ---------------------------------------------------------------------------
class PropertyRegressor:
    """A collection of per-property models, addressable by property code."""

    MIN_SAMPLES = 6  # below this we don't even try to fit
    CV_FOLDS = 3  # tiny datasets — keep CV cheap and honest

    def __init__(self, storage_dir: Path) -> None:
        self._storage = Path(storage_dir)
        self._storage.mkdir(parents=True, exist_ok=True)
        # In-memory cache of ``(model, metadata)`` keyed by property
        # code + on-disk mtime.  Predict() is called hundreds of times
        # per optimiser / pareto request, and re-unpickling the stacked
        # ensemble on every call was ~50 ms of pure overhead.
        self._cache: dict[str, tuple[float, object, ModelMetadata]] = {}

    # ------------------------------------------------------------------ train
    HOLDOUT_MIN_SAMPLES = 30  # below this we don't hold anything out — too small

    def _build_pipeline(self):  # type: ignore[no-untyped-def]
        """Return the training Pipeline used for every property model.

        We deliberately keep this to a single, well-tested sklearn
        recipe rather than doing per-property hyperparameter search:

        1. ``StandardScaler`` — HistGradientBoosting is scale-invariant,
           but scaling makes the RF-vs-HGBM contribution weights
           comparable and stabilises the Ridge meta-learner.
        2. ``VarianceThreshold(0.0)`` — after ScikitLearn scaling many
           mass-percent bucket columns are entirely zero for a given
           corpus (a category may never use plasticiser, for example).
           Dropping constant columns keeps the polynomial expansion
           tractable and avoids feeding the meta-learner degenerate
           inputs.
        3. ``PolynomialFeatures(2, interaction_only=True,
           include_bias=False)`` — captures pairwise composition
           interactions (binder×pigment, thickener×pigment, …) which
           are known to drive gloss/viscosity nonlinearly.
        4. ``StackingRegressor`` with two base learners:
             - ``RandomForestRegressor`` — robust to noisy tabular data
             - ``HistGradientBoostingRegressor`` — better bias on
               smooth nonlinear surfaces
           and a ``Ridge`` meta-learner (5-fold CV internal blending).
        """
        from sklearn.ensemble import (
            HistGradientBoostingRegressor,
            RandomForestRegressor,
            StackingRegressor,
        )
        from sklearn.feature_selection import VarianceThreshold
        from sklearn.linear_model import Ridge
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler

        rf = RandomForestRegressor(
            n_estimators=120,
            max_depth=None,
            min_samples_leaf=2,
            n_jobs=1,
            random_state=42,
        )
        gbm = HistGradientBoostingRegressor(
            max_depth=8,
            max_iter=200,
            learning_rate=0.06,
            l2_regularization=1e-3,
            random_state=42,
            early_stopping=True,
            validation_fraction=0.15,
            n_iter_no_change=15,
        )
        stack = StackingRegressor(
            estimators=[("rf", rf), ("gbm", gbm)],
            final_estimator=Ridge(alpha=1.0, random_state=42),
            cv=3,
            n_jobs=1,
            passthrough=False,
        )
        # NB: no PolynomialFeatures in the pipeline — both base learners
        # (Random Forest, Histogram Gradient Boosting) already model
        # pairwise interactions natively via tree splits.  Feeding them a
        # 990-column polynomial expansion was strictly worse in
        # benchmarking on the seed corpus: same CV R², ~40× slower fit.
        return Pipeline(
            [
                ("scale", StandardScaler(with_mean=True, with_std=True)),
                ("prune", VarianceThreshold(threshold=0.0)),
                ("stack", stack),
            ]
        )

    def train(self, samples: list[TrainingSample]) -> TrainingResult:
        """Train a stacked (RF + HGBM → Ridge) regressor per property.

        Only property codes with at least :attr:`MIN_SAMPLES` samples
        are trained; the rest are surfaced in ``TrainingResult.skipped``.
        For buckets ≥ ``HOLDOUT_MIN_SAMPLES`` we additionally split off
        20 % as a held-out set that the model never sees, so metadata
        carries an honest ``holdout_r2`` alongside the CV score.
        """
        try:
            import numpy as np
            from sklearn.metrics import mean_absolute_error, r2_score
            from sklearn.model_selection import KFold, cross_val_score, train_test_split
        except ImportError as exc:
            raise ModelUnavailableError(
                "scikit-learn is required for training — install 'formulation-workbench[ml]'."
            ) from exc

        buckets: dict[str, list[TrainingSample]] = {}
        for s in samples:
            if not _valid_property_code(s.property_code):
                continue
            buckets.setdefault(s.property_code, []).append(s)

        trained: list[ModelMetadata] = []
        skipped: dict[str, str] = {}

        for code, bucket in sorted(buckets.items()):
            if len(bucket) < self.MIN_SAMPLES:
                skipped[code] = f"only {len(bucket)} samples (need >= {self.MIN_SAMPLES})"
                continue

            x_all = np.asarray([s.features for s in bucket], dtype=float)
            y_all = np.asarray([s.target for s in bucket], dtype=float)

            # ------------------- optional held-out split
            holdout_r2: float | None = None
            holdout_mae: float | None = None
            holdout_size: int | None = None
            if len(bucket) >= self.HOLDOUT_MIN_SAMPLES:
                x_fit, x_hold, y_fit, y_hold = train_test_split(
                    x_all, y_all, test_size=0.2, random_state=42
                )
                # Evaluate a fresh pipeline that never saw x_hold.
                eval_pipe = self._build_pipeline()
                try:
                    eval_pipe.fit(x_fit, y_fit)
                    preds_hold = eval_pipe.predict(x_hold)
                    holdout_r2 = float(r2_score(y_hold, preds_hold))
                    holdout_mae = float(mean_absolute_error(y_hold, preds_hold))
                    holdout_size = len(y_hold)
                except Exception as exc:
                    logger.warning(
                        "holdout_eval_failed",
                        extra={"property_code": code, "error": str(exc)},
                    )

            # ------------------- honest cross-validation
            folds = max(2, min(self.CV_FOLDS, len(bucket)))
            try:
                cv = KFold(n_splits=folds, shuffle=True, random_state=42)
                cv_pipe = self._build_pipeline()
                cv_scores = cross_val_score(cv_pipe, x_all, y_all, cv=cv, scoring="r2", n_jobs=1)
            except Exception as exc:
                skipped[code] = f"cross_val_score failed: {exc}"
                continue

            # ------------------- final fit on the full bucket
            model = self._build_pipeline()
            try:
                model.fit(x_all, y_all)
            except Exception as exc:
                skipped[code] = f"final fit failed: {exc}"
                continue

            version = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            fingerprint = hashlib.sha256(
                json.dumps(
                    [(s.experiment_id, s.recipe_id, s.target) for s in bucket],
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()[:16]

            metadata = ModelMetadata(
                property_code=code,
                version=version,
                n_samples=len(bucket),
                n_features=len(FEATURE_NAMES),
                feature_names=FEATURE_NAMES,
                cv_mean_r2=float(cv_scores.mean()),
                cv_std_r2=float(cv_scores.std()),
                training_recipe_ids=tuple(sorted({s.recipe_id for s in bucket})),
                algorithm="Stacking(RF+HGBM)->Ridge",
                fingerprint=fingerprint,
                holdout_r2=holdout_r2,
                holdout_mae=holdout_mae,
                holdout_size=holdout_size,
            )
            self._save_model(code, model, metadata, samples=bucket)
            trained.append(metadata)
            logger.info(
                "regressor_trained",
                extra={
                    "property_code": code,
                    "n_samples": len(bucket),
                    "cv_mean_r2": round(metadata.cv_mean_r2, 3),
                    "cv_std_r2": round(metadata.cv_std_r2, 3),
                    "holdout_r2": (
                        round(metadata.holdout_r2, 3) if metadata.holdout_r2 is not None else None
                    ),
                    "version": version,
                },
            )

        return TrainingResult(trained=tuple(trained), skipped=skipped)

    # ------------------------------------------------------------------ predict
    def predict(
        self,
        recipe: Recipe,
        property_code: str,
        *,
        alpha: float | None = 0.1,
        explain_top_k: int | None = None,
    ) -> PropertyPrediction | None:
        """Point prediction with an optional ``(1 - alpha)`` interval.

        ``alpha=None`` skips the interval computation (small speedup).
        """
        model, metadata = self._load_model(property_code)
        if model is None or metadata is None:
            return None
        vector = to_vector(recipe)
        try:
            import numpy as np
        except ImportError as exc:  # pragma: no cover
            raise ModelUnavailableError("scikit-learn / numpy required for prediction") from exc

        value = float(model.predict(np.asarray([vector], dtype=float))[0])

        # Extract the RandomForest sub-estimator + the vector as it looks
        # AFTER the preprocessing pipeline sees it, so uncertainty and
        # explainability keep working on the stacked ensemble.
        rf_model, rf_vector, rf_feature_names = _rf_view_for(model, vector)

        lower = upper = None
        used_alpha: float | None = None
        if alpha is not None and rf_model is not None:
            try:
                from .uncertainty import predict_with_interval

                interval = predict_with_interval(rf_model, rf_vector, alpha=alpha)
                lower = interval.lower
                upper = interval.upper
                used_alpha = alpha
            except Exception:  # pragma: no cover — never break a prediction
                logger.exception("uncertainty_interval_failed")

        # Apply calibration (both point + interval) if available.
        bundle = self.get_calibration(property_code)
        if bundle is not None:
            if bundle.isotonic is not None:
                value = bundle.isotonic.apply(value)
            if bundle.interval is not None and lower is not None and upper is not None:
                lower, upper = bundle.interval.apply(value, lower, upper)

        top_features: tuple[FeatureImpact, ...] = ()
        if explain_top_k is not None and explain_top_k > 0 and rf_model is not None:
            try:
                from .explainability import explain_prediction

                attributions = explain_prediction(
                    rf_model,
                    rf_vector,
                    top_k=explain_top_k,
                    feature_names=tuple(rf_feature_names),
                )
                top_features = tuple(
                    FeatureImpact(
                        feature_name=a.feature_name,
                        contribution=a.contribution,
                        baseline_value=a.baseline_value,
                        global_importance=a.global_importance,
                    )
                    for a in attributions
                )
            except Exception:  # pragma: no cover — never break a prediction
                logger.exception("explainability_failed")

        return PropertyPrediction(
            property_code=property_code,
            predicted_value=value,
            model_version=metadata.version,
            model_cv_r2=metadata.cv_mean_r2,
            lower_bound=lower,
            upper_bound=upper,
            interval_alpha=used_alpha,
            top_features=top_features,
        )

    # ------------------------------------------------------------------ calibration
    def calibrate(
        self,
        property_code: str,
        raw_predictions: list[float],
        actual_values: list[float],
        *,
        lowers: list[float] | None = None,
        uppers: list[float] | None = None,
        target_coverage: float = 0.9,
    ) -> CalibrationBundle:
        """Fit isotonic + (optional) interval calibration and persist.

        Requires the model for ``property_code`` to already exist on
        disk (calibration references its version for auditability).
        """
        from datetime import datetime, timezone

        from .calibration import (
            CalibrationBundle,
            CalibrationError,
            fit_interval_calibration,
            fit_isotonic,
            write_bundle,
        )

        _, metadata = self._load_model(property_code)
        if metadata is None:
            raise CalibrationError(f"No model for property_code={property_code!r}; train first.")
        isotonic = fit_isotonic(raw_predictions, actual_values)

        interval_cal = None
        if lowers is not None and uppers is not None and len(lowers) == len(actual_values):
            interval_cal = fit_interval_calibration(
                raw_predictions,
                lowers,
                uppers,
                actual_values,
                target_coverage=target_coverage,
            )

        version = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        bundle = CalibrationBundle(
            property_code=property_code,
            version=version,
            isotonic=isotonic,
            interval=interval_cal,
            calibration_n=len(actual_values),
            notes=(f"anchored to model version {metadata.version}",),
        )
        write_bundle(self._calibration_path(property_code), bundle)
        logger.info(
            "calibration_written",
            extra={
                "property_code": property_code,
                "n": len(actual_values),
                "coverage": (
                    round(interval_cal.empirical_coverage, 3) if interval_cal is not None else None
                ),
            },
        )
        return bundle

    def get_calibration(self, property_code: str) -> CalibrationBundle | None:
        from .calibration import read_bundle

        return read_bundle(self._calibration_path(property_code))

    def _calibration_path(self, property_code: str) -> Path:
        return self._storage / f"{property_code}.calibration.json"

    def get_training_vectors(self, property_code: str) -> list[list[float]] | None:
        """Return the feature vectors used to train ``property_code``.

        Used by drift detection to compare an incoming batch against the
        distribution the model was trained on.  Returns ``None`` if we
        don't have a snapshot on disk (e.g. legacy model or the file was
        pruned).
        """
        path = self._storage / f"{property_code}.samples.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        return [list(map(float, row)) for row in data]

    # ------------------------------------------------------------------ registry
    def list_models(self) -> list[ModelMetadata]:
        result: list[ModelMetadata] = []
        for meta_path in sorted(self._storage.glob("*.meta.json")):
            try:
                data = json.loads(meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            result.append(
                ModelMetadata(
                    property_code=data["property_code"],
                    version=data["version"],
                    n_samples=int(data["n_samples"]),
                    n_features=int(data["n_features"]),
                    feature_names=tuple(data["feature_names"]),
                    cv_mean_r2=float(data["cv_mean_r2"]),
                    cv_std_r2=float(data["cv_std_r2"]),
                    training_recipe_ids=tuple(data.get("training_recipe_ids", ())),
                    algorithm=data.get("algorithm", "RandomForestRegressor"),
                    fingerprint=data.get("fingerprint", ""),
                    holdout_r2=(
                        float(data["holdout_r2"]) if data.get("holdout_r2") is not None else None
                    ),
                    holdout_mae=(
                        float(data["holdout_mae"]) if data.get("holdout_mae") is not None else None
                    ),
                    holdout_size=(
                        int(data["holdout_size"]) if data.get("holdout_size") is not None else None
                    ),
                )
            )
        return result

    def has_model(self, property_code: str) -> bool:
        return (self._storage / f"{property_code}.pkl").exists()

    # ------------------------------------------------------------------ private
    def _model_path(self, property_code: str) -> Path:
        return self._storage / f"{property_code}.pkl"

    def _meta_path(self, property_code: str) -> Path:
        return self._storage / f"{property_code}.meta.json"

    def _save_model(  # type: ignore[no-untyped-def]
        self,
        code: str,
        model,
        metadata: ModelMetadata,
        *,
        samples: list[TrainingSample] | None = None,
    ) -> None:
        self._model_path(code).write_bytes(pickle.dumps(model, protocol=pickle.HIGHEST_PROTOCOL))
        self._meta_path(code).write_text(
            json.dumps(metadata.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        # Persist the training feature vectors — needed by the drift
        # detector.  Kept in a sidecar so old readers (which don't know
        # about it) simply ignore it.
        if samples:
            samples_path = self._storage / f"{code}.samples.json"
            samples_path.write_text(json.dumps([s.features for s in samples]), encoding="utf-8")

    def _load_model(self, code: str):  # type: ignore[no-untyped-def]
        m_path = self._model_path(code)
        meta_path = self._meta_path(code)
        if not m_path.exists() or not meta_path.exists():
            return None, None
        # Return the cached copy when the pkl file hasn't changed on
        # disk since we last loaded it (checked via mtime).  Stops
        # per-predict pickle overhead from dominating optimiser loops.
        try:
            mtime = m_path.stat().st_mtime
        except OSError:
            mtime = 0.0
        cached = self._cache.get(code)
        if cached is not None and cached[0] == mtime:
            return cached[1], cached[2]
        try:
            model = pickle.loads(m_path.read_bytes())
            data = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, pickle.UnpicklingError, json.JSONDecodeError) as exc:
            logger.warning("Failed to load model %s: %s", code, exc)
            return None, None
        metadata = ModelMetadata(
            property_code=data["property_code"],
            version=data["version"],
            n_samples=int(data["n_samples"]),
            n_features=int(data["n_features"]),
            feature_names=tuple(data["feature_names"]),
            cv_mean_r2=float(data["cv_mean_r2"]),
            cv_std_r2=float(data["cv_std_r2"]),
            training_recipe_ids=tuple(data.get("training_recipe_ids", ())),
            algorithm=data.get("algorithm", "RandomForestRegressor"),
            fingerprint=data.get("fingerprint", ""),
        )
        self._cache[code] = (mtime, model, metadata)
        return model, metadata


# ---------------------------------------------------------------------------
# Ensemble helpers — used by predict() to route uncertainty +
# explainability through the RandomForest sub-estimator of the stacked
# pipeline.  A legacy plain-RF model is handled by the same code path
# because ``_rf_view_for`` returns ``(model, vector)`` unchanged in that
# case.
# ---------------------------------------------------------------------------
def _rf_view_for(model, vector):  # type: ignore[no-untyped-def]
    """Return ``(random_forest, transformed_vector, feature_names)``.

    ``feature_names`` reflects the columns the RF actually saw after
    the pre-``stack`` pipeline pruned constant features — so
    explainability can label attributions correctly.

    Cases:
      - Legacy plain ``RandomForestRegressor`` → returns it, the raw
        vector, and the canonical :data:`FEATURE_NAMES`.
      - Pipeline with a ``StackingRegressor`` step → returns the fitted
        RF sub-estimator, the vector after ``scale`` + ``prune``, and
        the surviving :data:`FEATURE_NAMES` (via VarianceThreshold's
        ``get_support`` mask).
      - Anything else → ``(None, vector, FEATURE_NAMES)`` so predict()
        can skip uncertainty + explainability instead of crashing.
    """
    import numpy as np

    # Plain estimator (old format).
    if hasattr(model, "estimators_") and not hasattr(model, "named_steps"):
        return model, vector, list(FEATURE_NAMES)

    named_steps = getattr(model, "named_steps", None)
    if named_steps is None:
        return None, vector, list(FEATURE_NAMES)
    stack = named_steps.get("stack")
    if stack is None or not hasattr(stack, "named_estimators_"):
        return None, vector, list(FEATURE_NAMES)
    rf = stack.named_estimators_.get("rf")
    if rf is None or not hasattr(rf, "estimators_"):
        return None, vector, list(FEATURE_NAMES)

    # Push the vector through every pre-stack step so the RF sees the
    # same shape it was fit on.
    x = np.asarray([vector], dtype=float)
    surviving_names = list(FEATURE_NAMES)
    for _name, step in model.steps[:-1]:  # everything except the stack
        if hasattr(step, "transform"):
            x = step.transform(x)
        # If this step is a feature selector, propagate the surviving
        # column names so downstream explainability can label them.
        if hasattr(step, "get_support"):
            try:
                mask = step.get_support()
                if len(mask) == len(surviving_names):
                    surviving_names = [
                        n for n, keep in zip(surviving_names, mask, strict=False) if keep
                    ]
            except Exception:  # defensive: mapping is best-effort
                # and must not break predict()
                logger.debug("feature_name_mapping_failed", exc_info=True)
    return rf, list(map(float, x[0])), surviving_names


__all__ = [
    "ModelMetadata",
    "ModelUnavailableError",
    "PropertyPrediction",
    "PropertyRegressor",
    "TrainingResult",
    "TrainingSample",
    "build_training_samples",
]
