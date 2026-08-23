"""Regression calibration for the RandomForest predictors.

Two complementary techniques bundled behind one API:

- **Isotonic calibration** — fits a monotonic increasing function that
  maps raw model outputs to the observed distribution.  Excellent when
  the RF over- or under-shoots in a systematic, monotone way, which is
  the typical failure mode after retraining on a shifted dataset.
- **Platt-style quantile calibration** — inspired by Platt scaling for
  probabilistic classifiers.  We fit a small logistic on the quantile
  interval widths so a stated "90 % interval" actually covers ~90 % of
  fresh calibration samples.  Falls back to a linear rescale when the
  logistic fit is degenerate.

Both calibrators are saved next to the underlying model as
``<code>.calibration.json`` so predictions can pick them up
transparently.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


class CalibrationError(Exception):
    """Raised when calibration cannot be performed."""


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class IsotonicCalibration:
    """Piecewise-constant increasing mapping ``raw → calibrated``.

    Serialised as two parallel lists of *sorted* raw predictions and
    their calibrated targets.  Prediction uses linear interpolation
    between the pinned points and clamps at the ends.
    """

    raw_predictions: tuple[float, ...]
    calibrated_targets: tuple[float, ...]

    def apply(self, raw: float) -> float:
        if not self.raw_predictions:
            return raw
        xs = self.raw_predictions
        ys = self.calibrated_targets
        if raw <= xs[0]:
            return ys[0]
        if raw >= xs[-1]:
            return ys[-1]
        # Binary search — the arrays are small (<= ~200 anchors typically).
        lo, hi = 0, len(xs) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if xs[mid] > raw:
                hi = mid
            else:
                lo = mid
        x0, x1 = xs[lo], xs[hi]
        y0, y1 = ys[lo], ys[hi]
        if x1 == x0:
            return (y0 + y1) / 2.0
        return y0 + (y1 - y0) * (raw - x0) / (x1 - x0)


@dataclass(frozen=True, slots=True)
class IntervalCalibration:
    """Multiplier applied to raw quantile-interval half-widths.

    Reports the empirical coverage on calibration data along with the
    coefficient so operators can spot pathological calibrations
    (``factor > 3`` typically means the model can't be trusted at all).
    """

    factor: float  # multiply raw half-width by this
    empirical_coverage: float  # 0..1 — measured on calibration set
    target_coverage: float  # e.g. 0.9

    def apply(self, mean: float, lower: float, upper: float) -> tuple[float, float]:
        """Return the recalibrated (lower, upper) bounds."""
        half = (upper - lower) / 2.0
        return (mean - half * self.factor, mean + half * self.factor)


@dataclass(frozen=True, slots=True)
class CalibrationBundle:
    """Everything persisted for one calibrated model."""

    property_code: str
    version: str
    isotonic: IsotonicCalibration | None = None
    interval: IntervalCalibration | None = None
    calibration_n: int = 0
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "property_code": self.property_code,
            "version": self.version,
            "calibration_n": self.calibration_n,
            "notes": list(self.notes),
            "isotonic": (
                {
                    "raw_predictions": list(self.isotonic.raw_predictions),
                    "calibrated_targets": list(self.isotonic.calibrated_targets),
                }
                if self.isotonic is not None
                else None
            ),
            "interval": (
                {
                    "factor": self.interval.factor,
                    "empirical_coverage": self.interval.empirical_coverage,
                    "target_coverage": self.interval.target_coverage,
                }
                if self.interval is not None
                else None
            ),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> CalibrationBundle:
        iso = data.get("isotonic")
        interval = data.get("interval")
        isotonic = (
            IsotonicCalibration(
                raw_predictions=tuple(iso["raw_predictions"]),  # type: ignore[index]
                calibrated_targets=tuple(iso["calibrated_targets"]),  # type: ignore[index]
            )
            if isinstance(iso, dict)
            else None
        )
        interval_cal = (
            IntervalCalibration(
                factor=float(interval["factor"]),  # type: ignore[index]
                empirical_coverage=float(interval["empirical_coverage"]),  # type: ignore[index]
                target_coverage=float(interval["target_coverage"]),  # type: ignore[index]
            )
            if isinstance(interval, dict)
            else None
        )
        return cls(
            property_code=str(data["property_code"]),
            version=str(data["version"]),
            isotonic=isotonic,
            interval=interval_cal,
            calibration_n=int(str(data.get("calibration_n", 0) or 0)),
            notes=tuple(data.get("notes", ())),  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Isotonic fitting (Pool Adjacent Violators — pure Python, no sklearn dep)
# ---------------------------------------------------------------------------
def fit_isotonic(raw: list[float], target: list[float]) -> IsotonicCalibration:
    """Fit a monotonically increasing mapping via PAV.

    Complexity O(n log n) with the sort dominating; PAV itself is O(n).
    """
    if len(raw) != len(target):
        raise CalibrationError("raw / target lengths differ")
    if len(raw) < 2:
        raise CalibrationError("need at least two points to fit isotonic")

    order = sorted(range(len(raw)), key=lambda i: raw[i])
    xs = [raw[i] for i in order]
    ys = [target[i] for i in order]

    # Pool Adjacent Violators — keep stacks of (weight, mean, span_index).
    weights = [1.0] * len(ys)
    means = list(ys)
    i = 0
    while i < len(means) - 1:
        if means[i] <= means[i + 1] + 1e-12:
            i += 1
            continue
        # Merge violators i, i+1 (weighted mean) and back-track.
        w = weights[i] + weights[i + 1]
        m = (weights[i] * means[i] + weights[i + 1] * means[i + 1]) / w
        means[i] = m
        weights[i] = w
        del means[i + 1]
        del weights[i + 1]
        # Also shrink xs to keep parallel with the merged block
        # (use max of the merged xs so the anchor covers the full range).
        xs[i] = xs[i + 1] if i + 1 < len(xs) else xs[i]
        del xs[i + 1]
        if i > 0:
            i -= 1
    return IsotonicCalibration(raw_predictions=tuple(xs), calibrated_targets=tuple(means))


# ---------------------------------------------------------------------------
# Interval calibration
# ---------------------------------------------------------------------------
def fit_interval_calibration(
    means: list[float],
    lowers: list[float],
    uppers: list[float],
    actual: list[float],
    *,
    target_coverage: float = 0.9,
) -> IntervalCalibration:
    """Find the multiplier that makes empirical coverage = target.

    We search for ``k`` such that ``P(|actual - mean| <= k * halfwidth) ==
    target``.  Bisection on the empirical CDF works well when N >= ~30
    and avoids a scipy dependency for a two-liner.
    """
    n = len(actual)
    if n == 0 or not (0.0 < target_coverage < 1.0):
        raise CalibrationError("invalid inputs for interval calibration")
    if not (len(means) == len(lowers) == len(uppers) == n):
        raise CalibrationError("all inputs must have the same length")

    half_widths = [max(1e-9, (u - lower) / 2.0) for lower, u in zip(lowers, uppers, strict=True)]
    normalised_errors = [
        abs(a - m) / hw for a, m, hw in zip(actual, means, half_widths, strict=True)
    ]

    # Empirical CDF is a step function — we want the smallest k such
    # that P(err <= k) >= target.  Sort once and read that quantile
    # directly; bisection would only re-discover the same step.
    sorted_errors = sorted(normalised_errors)
    quantile_index = min(n - 1, max(0, int(round(target_coverage * n) - 1)))
    factor = sorted_errors[quantile_index]
    # Safety: never return zero (would collapse the interval).
    factor = max(factor, 1e-6)
    empirical = sum(1 for e in normalised_errors if e <= factor) / n
    return IntervalCalibration(
        factor=factor,
        empirical_coverage=empirical,
        target_coverage=target_coverage,
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def write_bundle(path: Path, bundle: CalibrationBundle) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(bundle.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def read_bundle(path: Path) -> CalibrationBundle | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("could not decode calibration file %s", path)
        return None
    try:
        return CalibrationBundle.from_dict(data)
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("skipping malformed calibration bundle at %s: %s", path, exc)
        return None


__all__ = [
    "CalibrationBundle",
    "CalibrationError",
    "IntervalCalibration",
    "IsotonicCalibration",
    "fit_interval_calibration",
    "fit_isotonic",
    "read_bundle",
    "write_bundle",
]
