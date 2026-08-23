"""Unit tests for isotonic + interval calibration."""

from __future__ import annotations

import pytest

from formulation_workbench.infrastructure.ml.calibration import (
    CalibrationBundle,
    CalibrationError,
    IntervalCalibration,
    IsotonicCalibration,
    fit_interval_calibration,
    fit_isotonic,
    read_bundle,
    write_bundle,
)


class TestIsotonic:
    def test_identity_pav_on_monotone_data(self) -> None:
        cal = fit_isotonic([1.0, 2.0, 3.0, 4.0], [1.1, 2.0, 3.05, 4.02])
        # Already monotone → no merging.
        assert len(cal.raw_predictions) == 4
        assert cal.apply(2.0) == pytest.approx(2.0)

    def test_pav_merges_violators(self) -> None:
        # 2.0 -> 3.0 is a violation of the following 3.0 -> 2.5 pair.
        cal = fit_isotonic([1.0, 2.0, 3.0, 4.0], [1.0, 3.0, 2.5, 5.0])
        # PAV should have averaged the two middle points → (3 + 2.5)/2 = 2.75.
        applied = [cal.apply(x) for x in [1.0, 2.0, 3.0, 4.0]]
        # Monotone non-decreasing sequence after fit.
        assert all(applied[i] <= applied[i + 1] + 1e-9 for i in range(len(applied) - 1))

    def test_apply_clamps_at_ends(self) -> None:
        cal = IsotonicCalibration(raw_predictions=(1.0, 5.0), calibrated_targets=(10.0, 20.0))
        assert cal.apply(0.0) == 10.0
        assert cal.apply(100.0) == 20.0
        # Linear interp in between.
        assert cal.apply(3.0) == pytest.approx(15.0)

    def test_requires_two_points(self) -> None:
        with pytest.raises(CalibrationError):
            fit_isotonic([1.0], [1.0])

    def test_length_mismatch_rejected(self) -> None:
        with pytest.raises(CalibrationError):
            fit_isotonic([1.0, 2.0], [1.0])


class TestIntervalCalibration:
    def test_intervals_that_undercover_get_scaled_up(self) -> None:
        """Half-width was too small — factor must exceed 1 to hit 90 %."""
        means = [0.0] * 100
        lowers = [-0.5] * 100
        uppers = [0.5] * 100
        # 90 samples at |err|=1.0, 10 at |err|=3.0 → normalised errors 2.0 and 6.0.
        actual = [1.0] * 90 + [3.0] * 10
        cal = fit_interval_calibration(means, lowers, uppers, actual, target_coverage=0.9)
        assert cal.empirical_coverage >= 0.9
        # Half-widths were 0.5; to cover 90 % of |err|<=1.0 we need factor >= 2.
        assert cal.factor >= 2.0

    def test_wide_intervals_shrink_factor_below_one(self) -> None:
        """Half-width was way too big — factor stays well below 1."""
        means = [0.0] * 100
        lowers = [-10.0] * 100
        uppers = [10.0] * 100
        actual = [0.5] * 90 + [3.0] * 10
        cal = fit_interval_calibration(means, lowers, uppers, actual, target_coverage=0.9)
        assert cal.empirical_coverage >= 0.9
        assert cal.factor < 1.0

    def test_needs_wider_interval_when_undercovered(self) -> None:
        means = [0.0] * 20
        lowers = [-0.1] * 20
        uppers = [0.1] * 20
        actual = [1.0] * 20  # every sample is way outside
        cal = fit_interval_calibration(means, lowers, uppers, actual, target_coverage=0.9)
        # Must scale the half-width dramatically to cover all points.
        assert cal.factor > 5.0

    def test_apply_widens_interval(self) -> None:
        cal = IntervalCalibration(factor=2.0, empirical_coverage=0.91, target_coverage=0.9)
        lower, upper = cal.apply(mean=10.0, lower=9.0, upper=11.0)
        # Half-width was 1.0; factor=2 → new half-width 2.0.
        assert lower == pytest.approx(8.0)
        assert upper == pytest.approx(12.0)


class TestBundlePersistence:
    def test_roundtrip(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        bundle = CalibrationBundle(
            property_code="gloss_60",
            version="20260823T120000Z",
            isotonic=fit_isotonic([1.0, 2.0, 3.0], [1.1, 1.9, 3.0]),
            interval=IntervalCalibration(factor=1.2, empirical_coverage=0.92, target_coverage=0.9),
            calibration_n=42,
            notes=("anchored to model v1",),
        )
        path = tmp_path / "gloss_60.calibration.json"
        write_bundle(path, bundle)
        loaded = read_bundle(path)
        assert loaded is not None
        assert loaded.property_code == "gloss_60"
        assert loaded.isotonic is not None
        assert loaded.interval is not None
        assert loaded.interval.factor == pytest.approx(1.2)

    def test_missing_file_returns_none(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        assert read_bundle(tmp_path / "nope.json") is None

    def test_malformed_json_returns_none(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        path = tmp_path / "broken.json"
        path.write_text("not-json", encoding="utf-8")
        assert read_bundle(path) is None
