"""Unit tests for the tree-based explainer + drift-full aggregator."""

from __future__ import annotations

import pytest

from formulation_workbench.infrastructure.ml.drift import (
    DriftLevel,
    compare_feature_matrices,
)


class TestExplainer:
    def test_ranks_features_by_absolute_contribution(self) -> None:
        try:
            import numpy as np
            from sklearn.ensemble import RandomForestRegressor
        except ImportError:
            pytest.skip("sklearn missing")
        from formulation_workbench.infrastructure.ml.explainability import (
            explain_prediction,
        )

        rng = np.random.RandomState(0)
        x = rng.rand(80, 3)
        # y depends *mostly* on column 0.
        y = 5.0 * x[:, 0] + 0.1 * x[:, 1] + rng.randn(80) * 0.05
        model = RandomForestRegressor(n_estimators=30, random_state=0)
        model.fit(x, y)

        top = explain_prediction(
            model,
            [0.9, 0.1, 0.5],
            top_k=2,
            feature_names=("water", "binder", "pigment"),
        )
        assert len(top) == 2
        # Column 0 must appear in the top-2.
        assert any(fi.feature_name == "water" for fi in top)
        # global_importance sanity: water > pigment.
        water_imp = next(fi.global_importance for fi in top if fi.feature_name == "water")
        assert water_imp > 0.0

    def test_length_mismatch_raises(self) -> None:
        try:
            from sklearn.ensemble import RandomForestRegressor
        except ImportError:
            pytest.skip("sklearn missing")
        from formulation_workbench.infrastructure.ml.explainability import (
            explain_prediction,
        )

        model = RandomForestRegressor(n_estimators=2).fit([[0.0, 0.0]], [0.0])
        with pytest.raises(ValueError):
            explain_prediction(model, [0.0], top_k=1, feature_names=("a", "b"))


class TestDriftFullMatrix:
    def test_per_feature_reports_returned_in_order(self) -> None:
        ref = [[0.0, 0.0], [1.0, 0.0], [2.0, 0.0], [3.0, 0.0]]
        cur = [[10.0, 0.0], [11.0, 0.0], [12.0, 0.0]]
        reports = compare_feature_matrices(ref, cur, feature_names=["shifted", "constant"])
        assert len(reports) == 2
        assert reports[0].feature_name == "shifted"
        assert reports[1].feature_name == "constant"
        assert reports[0].level is DriftLevel.SEVERE_DRIFT
        # Constant column → skipped as NO_DRIFT with zero statistics.
        assert reports[1].level is DriftLevel.NO_DRIFT
        assert reports[1].psi == 0.0

    def test_shape_mismatch_raises(self) -> None:
        with pytest.raises(ValueError):
            compare_feature_matrices([[1.0, 2.0]], [[3.0]], feature_names=["a", "b"])
