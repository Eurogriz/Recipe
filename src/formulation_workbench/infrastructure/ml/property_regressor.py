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
        }


@dataclass(frozen=True, slots=True)
class PropertyPrediction:
    property_code: str
    predicted_value: float
    model_version: str
    model_cv_r2: float
    unit: str = ""


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

    # ------------------------------------------------------------------ train
    def train(self, samples: list[TrainingSample]) -> TrainingResult:
        """Train one RandomForest per distinct property code.

        Only property codes with at least :attr:`MIN_SAMPLES` samples
        are trained; the rest are surfaced in ``TrainingResult.skipped``.
        """
        try:
            import numpy as np
            from sklearn.ensemble import RandomForestRegressor
            from sklearn.model_selection import KFold, cross_val_score
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
            x = np.asarray([s.features for s in bucket], dtype=float)
            y = np.asarray([s.target for s in bucket], dtype=float)

            model = RandomForestRegressor(
                n_estimators=100,
                max_depth=None,
                min_samples_leaf=1,
                n_jobs=1,
                random_state=42,
            )
            folds = max(2, min(self.CV_FOLDS, len(bucket)))
            try:
                # KFold with shuffle stabilises the score when the dataset
                # was generated by a monotonic scan (typical for lab work
                # that varies one factor at a time).
                cv = KFold(n_splits=folds, shuffle=True, random_state=42)
                cv_scores = cross_val_score(model, x, y, cv=cv, scoring="r2", n_jobs=1)
            except Exception as exc:
                skipped[code] = f"cross_val_score failed: {exc}"
                continue
            model.fit(x, y)

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
                fingerprint=fingerprint,
            )
            self._save_model(code, model, metadata)
            trained.append(metadata)
            logger.info(
                "regressor_trained",
                extra={
                    "property_code": code,
                    "n_samples": len(bucket),
                    "cv_mean_r2": round(metadata.cv_mean_r2, 3),
                    "cv_std_r2": round(metadata.cv_std_r2, 3),
                    "version": version,
                },
            )

        return TrainingResult(trained=tuple(trained), skipped=skipped)

    # ------------------------------------------------------------------ predict
    def predict(self, recipe: Recipe, property_code: str) -> PropertyPrediction | None:
        model, metadata = self._load_model(property_code)
        if model is None or metadata is None:
            return None
        vector = to_vector(recipe)
        try:
            import numpy as np
        except ImportError as exc:  # pragma: no cover
            raise ModelUnavailableError("scikit-learn / numpy required for prediction") from exc
        value = float(model.predict(np.asarray([vector], dtype=float))[0])
        return PropertyPrediction(
            property_code=property_code,
            predicted_value=value,
            model_version=metadata.version,
            model_cv_r2=metadata.cv_mean_r2,
        )

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

    def _save_model(self, code: str, model, metadata: ModelMetadata) -> None:  # type: ignore[no-untyped-def]
        self._model_path(code).write_bytes(pickle.dumps(model, protocol=pickle.HIGHEST_PROTOCOL))
        self._meta_path(code).write_text(
            json.dumps(metadata.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_model(self, code: str):  # type: ignore[no-untyped-def]
        m_path = self._model_path(code)
        meta_path = self._meta_path(code)
        if not m_path.exists() or not meta_path.exists():
            return None, None
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
        return model, metadata


__all__ = [
    "ModelMetadata",
    "ModelUnavailableError",
    "PropertyPrediction",
    "PropertyRegressor",
    "TrainingResult",
    "TrainingSample",
    "build_training_samples",
]
