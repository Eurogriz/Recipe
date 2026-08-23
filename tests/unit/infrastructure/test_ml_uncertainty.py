"""Uncertainty + drift-detection unit tests."""

from __future__ import annotations

import random

import pytest

from formulation_workbench.infrastructure.ml.drift import (
    DriftLevel,
    classify_psi,
    compare_distributions,
    ks_p_value,
    ks_statistic,
    population_stability_index,
)


class TestPsi:
    def test_identical_distributions_zero(self) -> None:
        rng = random.Random(0)
        data = [rng.gauss(0, 1) for _ in range(500)]
        psi = population_stability_index(data, data.copy())
        assert psi < 0.001

    def test_shifted_distribution_flags_drift(self) -> None:
        rng = random.Random(0)
        reference = [rng.gauss(0, 1) for _ in range(500)]
        rng2 = random.Random(1)
        current = [rng2.gauss(2.0, 1) for _ in range(500)]
        psi = population_stability_index(reference, current)
        assert psi > 0.25

    def test_classification_thresholds(self) -> None:
        assert classify_psi(0.05) is DriftLevel.NO_DRIFT
        assert classify_psi(0.15) is DriftLevel.MODERATE_DRIFT
        assert classify_psi(0.30) is DriftLevel.SEVERE_DRIFT

    def test_empty_inputs_return_zero(self) -> None:
        assert population_stability_index([], []) == 0.0


class TestKs:
    def test_identical_zero_statistic(self) -> None:
        data = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert ks_statistic(data, data.copy()) == 0.0

    def test_disjoint_maximises_statistic(self) -> None:
        d = ks_statistic([0.0, 0.1, 0.2, 0.3], [10.0, 11.0, 12.0, 13.0])
        assert d == pytest.approx(1.0, abs=1e-9)

    def test_p_value_bounds(self) -> None:
        p = ks_p_value(0.0, 100, 100)
        assert 0.0 <= p <= 1.0
        p_hi = ks_p_value(1.0, 100, 100)
        assert p_hi is not None
        assert p_hi < 0.01


class TestCompareDistributions:
    def test_no_drift_labelled(self) -> None:
        rng = random.Random(42)
        reference = [rng.gauss(0, 1) for _ in range(300)]
        current = [rng.gauss(0.02, 1) for _ in range(300)]
        report = compare_distributions(reference, current)
        assert report.level in {DriftLevel.NO_DRIFT, DriftLevel.MODERATE_DRIFT}
        assert report.n_reference == 300

    def test_severe_drift_labelled(self) -> None:
        rng = random.Random(0)
        ref = [rng.gauss(0, 1) for _ in range(500)]
        rng2 = random.Random(1)
        cur = [rng2.gauss(3.0, 1) for _ in range(500)]
        report = compare_distributions(ref, cur, feature_name="mass_percent_binder")
        assert report.level is DriftLevel.SEVERE_DRIFT
        assert report.feature_name == "mass_percent_binder"


class TestPredictionInterval:
    def test_interval_wraps_the_mean(self) -> None:
        """Trees vote → the mean must lie inside the interval by construction."""
        try:
            import numpy as np
            from sklearn.ensemble import RandomForestRegressor
        except ImportError:
            pytest.skip("sklearn not available")
        from formulation_workbench.infrastructure.ml.uncertainty import (
            predict_with_interval,
        )

        rng = np.random.RandomState(42)
        x = rng.rand(50, 3)
        y = x[:, 0] * 3 + rng.randn(50) * 0.1
        model = RandomForestRegressor(n_estimators=25, random_state=1)
        model.fit(x, y)

        interval = predict_with_interval(model, [0.5, 0.5, 0.5], alpha=0.1)
        assert interval.lower <= interval.mean <= interval.upper
        assert interval.interval_width >= 0
        assert interval.alpha == 0.1

    def test_alpha_bounds_validated(self) -> None:
        try:
            from sklearn.ensemble import RandomForestRegressor
        except ImportError:
            pytest.skip("sklearn not available")
        from formulation_workbench.infrastructure.ml.uncertainty import (
            predict_with_interval,
        )

        model = RandomForestRegressor(n_estimators=5).fit([[0.0]], [0.0])
        with pytest.raises(ValueError):
            predict_with_interval(model, [0.0], alpha=1.5)
        with pytest.raises(ValueError):
            predict_with_interval(model, [0.0], alpha=0.0)
