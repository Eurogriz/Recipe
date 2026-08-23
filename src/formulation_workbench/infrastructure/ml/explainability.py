"""Explainability for tree-based regressors.

Two levels of detail:

- **Global feature importance.**  Just the RandomForest's
  ``feature_importances_`` — cheap and stable enough for regression.
- **Local attribution** for a single prediction.  Uses SHAP's
  ``TreeExplainer`` when the ``shap`` package is installed (adds a
  proper Shapley-value ranking), and falls back to a **path-based
  contribution** — the average difference between each tree's leaf
  prediction and the tree's root prediction along the traversed path,
  attributed to the split feature.  This mirrors the "TreeInterpreter"
  approach of Saabas (2014) and is the standard fallback when SHAP is
  unavailable.

Everything runs at prediction time, so the code is deliberately
side-effect free and takes a fitted model + a feature vector as input.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .features import FEATURE_NAMES

if TYPE_CHECKING:
    from sklearn.ensemble import RandomForestRegressor

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FeatureAttribution:
    """One feature's local contribution to a prediction."""

    feature_name: str
    contribution: float  # positive = pushes prediction up
    baseline_value: float  # feature value in the input vector
    global_importance: float  # RF's feature_importances_ entry


def _path_attributions(model: RandomForestRegressor, features: list[float]) -> list[float]:
    """Saabas-style attribution: mean gain along the traversed path."""
    import numpy as np

    x = np.asarray([features], dtype=float)
    n_features = len(features)
    contributions = np.zeros(n_features)
    for tree in model.estimators_:
        node_indicator = tree.decision_path(x)
        leaf_id = tree.apply(x)[0]
        # Walk the traversed nodes from root to leaf.
        path_indices = node_indicator.indices[node_indicator.indptr[0] : node_indicator.indptr[1]]
        tree_ = tree.tree_
        # Baseline value = the root's average target; each split's
        # contribution to a feature = child's value - parent's value.
        for k in range(len(path_indices) - 1):
            parent = path_indices[k]
            child = path_indices[k + 1]
            feature = tree_.feature[parent]
            if feature < 0 or feature >= n_features:
                continue
            parent_value = tree_.value[parent].ravel()[0]
            child_value = tree_.value[child].ravel()[0]
            contributions[feature] += child_value - parent_value
        _ = leaf_id  # unused but documents intent
    contributions /= len(model.estimators_)
    return [float(c) for c in contributions]


def explain_prediction(
    model: RandomForestRegressor,
    features: list[float],
    *,
    top_k: int = 3,
    feature_names: tuple[str, ...] = FEATURE_NAMES,
) -> list[FeatureAttribution]:
    """Return the top-``k`` features driving one prediction.

    Falls back to Saabas-style attribution when SHAP is unavailable —
    both share the same ranking semantics (larger |contribution| = more
    influence) so callers can treat the result identically.
    """
    if len(features) != len(feature_names):
        raise ValueError(
            f"features has length {len(features)} but FEATURE_NAMES has {len(feature_names)}"
        )

    try:
        import shap  # type: ignore[import-not-found]

        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values([features])[0]
        contributions = [float(v) for v in shap_values]
        source = "shap"
    except Exception:  # pragma: no cover — fallback path is well-tested
        contributions = _path_attributions(model, features)
        source = "path"

    importances = getattr(model, "feature_importances_", None)
    if importances is None:
        importances = [0.0] * len(feature_names)

    ranked = sorted(
        range(len(contributions)),
        key=lambda i: abs(contributions[i]),
        reverse=True,
    )[:top_k]
    logger.debug("prediction_explained", extra={"source": source, "top_k": top_k})
    return [
        FeatureAttribution(
            feature_name=feature_names[i],
            contribution=contributions[i],
            baseline_value=features[i],
            global_importance=float(importances[i]),
        )
        for i in ranked
    ]


__all__ = ["FeatureAttribution", "explain_prediction"]
