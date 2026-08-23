# Recipe quality benchmark

The `tests/qualification/` suite answers the question **"how well does
the system actually design recipes?"** — end-to-end, against a synthetic
but realistic physical model of paint measurements.

## Running the benchmark

```bash
pytest -m qualification tests/qualification -s
```

The `-s` flag ensures the final report gets printed.  It's opt-in — the
default `pytest` run skips it via `-m "not qualification"`.

## What it measures

| # | Test | What it checks |
| - | ---- | -------------- |
| 1 | `test_prediction_quality_on_holdout` | R² and MAE for `gloss_60`, `hiding_power`, `viscosity_mid_shear`, `voc_content` on a 20-recipe hold-out (trained on 60). |
| 2 | `test_optimiser_hits_target_within_tolerance` | Runs the single-objective optimiser against 2 targets and evaluates the true-physics gap between the optimiser's optimum and the requested value. |
| 3 | `test_assessment_flags_defective_recipes` | Feeds 3 knowingly-broken recipes (no binder, defoamer overdose, pigment-only) — every one must be flagged with an ERROR and Maturity DRAFT-or-DEFECTIVE. |
| 4 | `test_assessment_accepts_a_reasonable_recipe` | A hand-tuned textbook waterborne acrylic paint must **not** be labelled defective. |
| 5 | `test_pareto_finds_trade_off_between_gloss_and_voc` | Multi-objective search must produce a non-trivial Pareto front. |

## Regression thresholds (2026-08-23)

The suite fails hard if any of these numbers regress:

| Metric | Threshold | Current |
| --- | --- | --- |
| gloss_60 R² | ≥ 0.55 | 0.935 |
| hiding_power R² | ≥ 0.75 | 0.938 |
| viscosity_mid_shear R² | ≥ 0.45 | 0.987 |
| voc_content R² | ≥ 0.75 | 0.985 |
| Optimiser gap (gloss target) | ≤ 20 % | 1.4 % |
| Optimiser gap (viscosity target) | ≤ 45 % | 9.7 % |
| Defective recipe detection | 3 / 3 | 3 / 3 |
| Pareto front size | ≥ 1 pt | 8 pts |

## Interpreting the report

- **R² < 0.5 or MAE spike** on a property → your ground truth changed
  or the regressor got shallower.  Investigate feature extraction and
  hyperparameters before disabling the test.
- **Optimiser gap ↑** → the optimiser is finding a local optimum the
  regressor believes but reality contradicts.  Add regularisation,
  more training data, or tighten the bounds.
- **Defect detection <100 %** → one of the `technological_rules.py`
  rules mis-graded a broken recipe.  This is exactly how the
  gross-overdose-→-ERROR escalation was discovered in v1.6.1.
- **Pareto front collapses to 1 point** → the optimiser exhausted the
  search bounds (all candidates cluster).  Widen `ComponentBounds` or
  increase `generations`.
