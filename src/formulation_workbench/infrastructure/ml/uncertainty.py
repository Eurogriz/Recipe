"""Prediction uncertainty for RandomForest regressors.

Two complementary techniques:

- **Per-tree quantiles.** For a fitted :class:`RandomForestRegressor` we
  gather the individual tree predictions and compute their empirical
  distribution. This is the same idea as Meinshausen's quantile
  regression forests (QRF, 2006) applied to *tree-level averages*
  rather than to leaf memberships — cheap, works on any RF, and is
  perfectly adequate for the small dataset regime we're in
  (:math:`n \\lesssim 10^3`).
- **Prediction interval width** — the difference between the requested
  low/high quantiles is exposed alongside the mean so downstream code
  (assessment API, optimiser) can prefer confident predictions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sklearn.ensemble import RandomForestRegressor


@dataclass(frozen=True, slots=True)
class PredictionInterval:
    """Point estimate and 1 - alpha prediction interval."""

    mean: float
    median: float
    lower: float
    upper: float
    alpha: float  # e.g. 0.1 for a 90 % interval
    interval_width: float  # upper - lower

    def contains(self, value: float) -> bool:
        return self.lower <= value <= self.upper


def predict_with_interval(
    model: RandomForestRegressor,
    features: list[float],
    *,
    alpha: float = 0.1,
) -> PredictionInterval:
    """Return the ``(1-alpha)`` prediction interval for ``features``.

    Uses tree-level predictions.  ``alpha`` must be in :math:`(0, 1)`;
    the interval spans ``[alpha/2, 1 - alpha/2]`` quantiles.
    """
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0, 1); got {alpha}")
    import numpy as np

    x = np.asarray([features], dtype=float)
    per_tree = np.asarray([tree.predict(x)[0] for tree in model.estimators_])
    lower_q = alpha / 2.0
    upper_q = 1.0 - alpha / 2.0
    lower = float(np.quantile(per_tree, lower_q))
    upper = float(np.quantile(per_tree, upper_q))
    return PredictionInterval(
        mean=float(per_tree.mean()),
        median=float(np.median(per_tree)),
        lower=lower,
        upper=upper,
        alpha=alpha,
        interval_width=upper - lower,
    )


__all__ = ["PredictionInterval", "predict_with_interval"]
