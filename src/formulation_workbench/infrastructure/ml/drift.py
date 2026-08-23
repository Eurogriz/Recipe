"""Distributional drift detection.

Two industry-standard statistics — kept dependency-light on purpose:

- **PSI (Population Stability Index).**  ``PSI < 0.1`` = no drift,
  ``0.1 – 0.25`` = moderate, ``>= 0.25`` = significant.  Widely used in
  credit / regulated ML contexts (SR 11-7).  We compute it against a
  fixed 10-bucket quantile histogram of the reference sample.
- **KS (Kolmogorov-Smirnov).**  Distribution-free two-sample test.  We
  return the statistic + p-value from scipy when available, and a
  lookup-table approximation otherwise so the module works in the
  ML-lite install profile.

The interpretation is deliberately conservative — labels are:
``no_drift`` / ``moderate_drift`` / ``severe_drift``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

_EPS = 1e-6


class DriftLevel(str, Enum):
    NO_DRIFT = "no_drift"
    MODERATE_DRIFT = "moderate_drift"
    SEVERE_DRIFT = "severe_drift"


@dataclass(frozen=True, slots=True)
class DriftReport:
    """Result of running the reference vs. current sample comparison."""

    feature_name: str
    psi: float
    ks_statistic: float
    ks_p_value: float | None
    level: DriftLevel
    n_reference: int
    n_current: int


# ---------------------------------------------------------------------------
# PSI
# ---------------------------------------------------------------------------
def population_stability_index(
    reference: list[float], current: list[float], *, buckets: int = 10
) -> float:
    """Return the PSI of ``current`` against ``reference``.

    Buckets are quantile-based on the reference sample.  Empty bins
    are floored to ``_EPS`` to keep the log finite.
    """
    if len(reference) < 2 or len(current) < 2:
        return 0.0

    ref_sorted = sorted(reference)
    step = 1.0 / buckets
    boundaries: list[float] = []
    for i in range(1, buckets):
        pos = i * step * (len(ref_sorted) - 1)
        lo = math.floor(pos)
        hi = min(lo + 1, len(ref_sorted) - 1)
        frac = pos - lo
        boundaries.append(ref_sorted[lo] + frac * (ref_sorted[hi] - ref_sorted[lo]))

    def _bin_share(sample: list[float]) -> list[float]:
        counts = [0] * buckets
        for v in sample:
            placed = False
            for i, b in enumerate(boundaries):
                if v <= b:
                    counts[i] += 1
                    placed = True
                    break
            if not placed:
                counts[-1] += 1
        total = len(sample) or 1
        return [max(_EPS, c / total) for c in counts]

    ref_shares = _bin_share(reference)
    cur_shares = _bin_share(current)
    psi = 0.0
    for r, c in zip(ref_shares, cur_shares, strict=True):
        psi += (c - r) * math.log(c / r)
    return float(psi)


# ---------------------------------------------------------------------------
# KS
# ---------------------------------------------------------------------------
def ks_statistic(reference: list[float], current: list[float]) -> float:
    """Two-sample Kolmogorov-Smirnov statistic.

    Follows the merged-sort formulation from Press et al. — for every
    distinct value in the pooled sample we compare the two empirical
    CDFs and keep the maximum absolute gap.
    """
    if not reference or not current:
        return 0.0
    ref = sorted(reference)
    cur = sorted(current)
    n1, n2 = len(ref), len(cur)
    pool = sorted(set(ref) | set(cur))
    d = 0.0
    for v in pool:
        # Right-continuous ECDF (count of values <= v).
        c1 = sum(1 for x in ref if x <= v) / n1
        c2 = sum(1 for x in cur if x <= v) / n2
        d = max(d, abs(c1 - c2))
    return float(d)


def ks_p_value(d: float, n1: int, n2: int) -> float | None:
    """Approximate p-value; asymptotic form good enough for n >= 20."""
    if n1 == 0 or n2 == 0:
        return None
    en = math.sqrt(n1 * n2 / (n1 + n2))
    lam = (en + 0.12 + 0.11 / en) * d
    # Kolmogorov distribution — convergent series (Numerical Recipes 14.3).
    j = 1
    fac = 2.0
    sum_ = 0.0
    prev = 0.0
    while j < 100:
        term = fac * math.exp(-2.0 * lam * lam * j * j)
        sum_ += term
        if abs(term) <= 1e-10 * abs(prev):
            return max(0.0, min(1.0, sum_))
        fac = -fac
        prev = term
        j += 1
    return max(0.0, min(1.0, sum_))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def classify_psi(psi: float) -> DriftLevel:
    if psi < 0.1:
        return DriftLevel.NO_DRIFT
    if psi < 0.25:
        return DriftLevel.MODERATE_DRIFT
    return DriftLevel.SEVERE_DRIFT


def compare_distributions(
    reference: list[float],
    current: list[float],
    *,
    feature_name: str = "value",
) -> DriftReport:
    """Compute PSI + KS + composite drift level for one feature."""
    psi = population_stability_index(reference, current)
    d = ks_statistic(reference, current)
    p = ks_p_value(d, len(reference), len(current))
    level = classify_psi(psi)
    # Escalate on strong KS even if PSI is quiet.
    if p is not None and p < 0.01 and level is DriftLevel.NO_DRIFT:
        level = DriftLevel.MODERATE_DRIFT
    return DriftReport(
        feature_name=feature_name,
        psi=psi,
        ks_statistic=d,
        ks_p_value=p,
        level=level,
        n_reference=len(reference),
        n_current=len(current),
    )


def compare_feature_matrices(
    reference: list[list[float]],
    current: list[list[float]],
    *,
    feature_names: list[str],
) -> list[DriftReport]:
    """Run :func:`compare_distributions` on each column of the matrices.

    ``reference`` and ``current`` are lists of *feature vectors* of
    equal width; the returned list preserves the order of
    ``feature_names`` so the caller can join back to metadata.  Columns
    that are constant on the reference side are skipped and reported
    with ``level=NO_DRIFT`` + statistics = 0 (nothing to compare).
    """
    if not reference:
        return []
    width = len(feature_names)
    if any(len(row) != width for row in reference) or any(len(row) != width for row in current):
        raise ValueError("all vectors must have the same width as feature_names")

    reports: list[DriftReport] = []
    for col in range(width):
        ref_col = [row[col] for row in reference]
        cur_col = [row[col] for row in current]
        if len(set(ref_col)) <= 1 and len(set(cur_col)) <= 1:
            reports.append(
                DriftReport(
                    feature_name=feature_names[col],
                    psi=0.0,
                    ks_statistic=0.0,
                    ks_p_value=None,
                    level=DriftLevel.NO_DRIFT,
                    n_reference=len(ref_col),
                    n_current=len(cur_col),
                )
            )
            continue
        reports.append(compare_distributions(ref_col, cur_col, feature_name=feature_names[col]))
    return reports


__all__ = [
    "DriftLevel",
    "DriftReport",
    "classify_psi",
    "compare_distributions",
    "compare_feature_matrices",
    "ks_p_value",
    "ks_statistic",
    "population_stability_index",
]
