"""End-to-end quality benchmark.

Answers "how well does the system actually design recipes?" against a
synthetic-but-realistic ground truth.  Run with:

    pytest -m qualification tests/qualification -s

Everything prints a compact summary at the end so the operator can
eyeball whether we're on target.  The benchmark also enforces
regression thresholds — if predictions get worse in a future commit,
the run fails.
"""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass

import pytest

from formulation_workbench.domain.entities.recipe import ProductClass
from formulation_workbench.domain.services.recipe_assessment import (
    Maturity,
    RecipeAssessmentService,
)
from formulation_workbench.infrastructure.ml.optimiser import (
    ComponentBounds,
    OptimisationRequest,
    PropertyTarget,
    RecipeOptimiser,
)
from formulation_workbench.infrastructure.ml.pareto import (
    ParetoOptimiser,
    ParetoRequest,
)
from formulation_workbench.infrastructure.ml.property_regressor import (
    PropertyRegressor,
    build_training_samples,
)

from .factories import RecipeSpec, build_recipe, completed_experiment, measure_recipe
from .ground_truth import measure

pytestmark = [pytest.mark.qualification]


# ---------------------------------------------------------------------------
# Corpus generation
# ---------------------------------------------------------------------------
def _random_water_based(rng: random.Random) -> RecipeSpec:
    """A plausible water-based interior paint with random composition."""
    binder = rng.uniform(20.0, 45.0)
    tio2 = rng.uniform(10.0, 24.0)
    caco3 = rng.uniform(2.0, 12.0)
    talc = rng.uniform(0.0, 6.0)
    texanol = rng.uniform(0.5, 3.0)
    rheo = rng.uniform(0.2, 1.0)
    pg = rng.uniform(0.5, 3.0)
    dispex = 0.5
    foamex = 0.3
    kathon = 0.15
    fixed = binder + tio2 + caco3 + talc + texanol + rheo + pg + dispex + foamex + kathon
    water = round(100.0 - fixed, 2)
    if water < 15.0:
        # too crowded — retry with a smaller pigment load
        return _random_water_based(rng)
    return RecipeSpec(
        mass_percent={
            "Water": water,
            "Acrylic": round(binder, 2),
            "TiO2": round(tio2, 2),
            "CaCO3": round(caco3, 2),
            "Talc": round(talc, 2),
            "Texanol": round(texanol, 2),
            "Rheo": round(rheo, 2),
            "PG": round(pg, 2),
            "Dispex": dispex,
            "Foamex": foamex,
            "Kathon": kathon,
        },
        product_class=ProductClass.PREMIUM,
        intended_use="Interior paint, random population",
    )


def _generate_corpus(n: int, *, seed: int = 42) -> list[tuple[RecipeSpec, object]]:
    rng = random.Random(seed)
    specs: list[tuple[RecipeSpec, object]] = []
    for i in range(n):
        spec = _random_water_based(rng)
        # Rename recipe id so ExperimentRun can distinguish runs.
        spec = RecipeSpec(
            mass_percent=spec.mass_percent,
            category=spec.category,
            subcategory=spec.subcategory,
            binder_type=spec.binder_type,
            product_class=spec.product_class,
            intended_use=spec.intended_use,
            recipe_id=f"corpus-{i:04d}",
        )
        measurements = measure_recipe(spec, seed=rng.randint(0, 10**6))
        specs.append((spec, measurements))
    return specs


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------
@dataclass
class BenchmarkReport:
    """Accumulated numbers for a single run of the suite."""

    n_train: int = 0
    n_test: int = 0
    prediction_r2: dict[str, float] = None  # type: ignore[assignment]
    prediction_mae: dict[str, float] = None  # type: ignore[assignment]
    optimiser_gap_pct: dict[str, float] = None  # type: ignore[assignment]
    assessment_true_positives: int = 0
    assessment_false_negatives: int = 0
    pareto_front_size: int = 0
    pareto_spread: float = 0.0

    def print_summary(self) -> None:
        print("\n" + "=" * 72)
        print(" FORMULATION WORKBENCH — QUALITY BENCHMARK")
        print("=" * 72)
        print(f" corpus  : {self.n_train} train / {self.n_test} holdout")
        print(" ─── Property prediction ────────────────────────────────────────────")
        for code in sorted(self.prediction_r2 or {}):
            r2 = self.prediction_r2[code]
            mae = self.prediction_mae[code]
            print(f"   {code:<28s} R²={r2:+.3f}   MAE={mae:8.3f}")
        print(" ─── Optimiser (single-objective) ───────────────────────────────────")
        for code, gap in (self.optimiser_gap_pct or {}).items():
            print(f"   target={code:<20s} gap to target={gap:6.2f} %")
        print(" ─── Assessment (defective-recipe detection) ────────────────────────")
        tp, fn = self.assessment_true_positives, self.assessment_false_negatives
        print(f"   detected {tp} of {tp + fn} defective recipes as ERROR")
        print(" ─── Pareto front (gloss ↑ vs voc ↓) ────────────────────────────────")
        print(
            f"   front size = {self.pareto_front_size},"
            f" spread (gloss max − min) = {self.pareto_spread:.2f}"
        )
        print("=" * 72)


# ---------------------------------------------------------------------------
# 1. Prediction quality (R² + MAE on hold-out)
# ---------------------------------------------------------------------------
def _r2(actual: list[float], predicted: list[float]) -> float:
    if len(actual) < 2:
        return 0.0
    mean_actual = statistics.fmean(actual)
    ss_tot = sum((a - mean_actual) ** 2 for a in actual)
    if ss_tot == 0:
        return 1.0
    ss_res = sum((a - p) ** 2 for a, p in zip(actual, predicted, strict=True))
    return 1.0 - ss_res / ss_tot


def _mae(actual: list[float], predicted: list[float]) -> float:
    return statistics.fmean(abs(a - p) for a, p in zip(actual, predicted, strict=True))


REPORT = BenchmarkReport(prediction_r2={}, prediction_mae={}, optimiser_gap_pct={})


@pytest.fixture(scope="module")
def trained_regressor(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[PropertyRegressor, list[tuple[RecipeSpec, object]], list[tuple[RecipeSpec, object]]]:
    """Train once per module; return the regressor + train + holdout sets."""
    corpus = _generate_corpus(60, seed=42)
    holdout = _generate_corpus(20, seed=1001)

    storage = tmp_path_factory.mktemp("qual_models")
    regressor = PropertyRegressor(storage_dir=storage)

    recipes = [build_recipe(spec) for spec, _ in corpus]
    runs = [completed_experiment(r, m) for r, (_, m) in zip(recipes, corpus, strict=True)]
    samples = build_training_samples(runs, {r.id: r for r in recipes})
    training_result = regressor.train(samples)

    trained_codes = {m.property_code for m in training_result.trained}
    assert "gloss_60" in trained_codes, f"gloss_60 not trained: {training_result.skipped}"

    REPORT.n_train = len(corpus)
    REPORT.n_test = len(holdout)
    return regressor, corpus, holdout


@pytest.mark.parametrize(
    ("property_code", "r2_min", "mae_max"),
    [
        ("gloss_60", 0.55, 8.0),  # nonlinear, noisy
        ("hiding_power", 0.75, 1.2),  # nearly linear in TiO2
        ("viscosity_mid_shear", 0.45, 180.0),  # strongly nonlinear
        ("voc_content", 0.75, 6.0),  # linear but small
    ],
)
def test_prediction_quality_on_holdout(
    trained_regressor,  # type: ignore[no-untyped-def]
    property_code: str,
    r2_min: float,
    mae_max: float,
) -> None:
    regressor, _, holdout = trained_regressor
    actual: list[float] = []
    predicted: list[float] = []
    for spec, measurements in holdout:
        recipe = build_recipe(spec)
        prediction = regressor.predict(recipe, property_code, alpha=None)
        assert prediction is not None, f"no model for {property_code}"
        actual.append(
            getattr(
                measurements,
                {
                    "gloss_60": "gloss_60",
                    "hiding_power": "hiding_power_m2_per_l",
                    "viscosity_mid_shear": "viscosity_mid_shear",
                    "voc_content": "voc_content",
                }[property_code],
            )
        )
        predicted.append(prediction.predicted_value)

    r2 = _r2(actual, predicted)
    mae = _mae(actual, predicted)
    REPORT.prediction_r2[property_code] = r2
    REPORT.prediction_mae[property_code] = mae
    assert r2 >= r2_min, f"{property_code}: R²={r2:.3f} below threshold {r2_min}"
    assert mae <= mae_max, f"{property_code}: MAE={mae:.3f} above threshold {mae_max}"


# ---------------------------------------------------------------------------
# 2. Optimiser quality — how close can it hit a stated target?
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("target_code", "target_value", "max_gap_pct"),
    [
        ("gloss_60", 65.0, 20.0),
        ("viscosity_mid_shear", 400.0, 45.0),
    ],
)
def test_optimiser_hits_target_within_tolerance(
    trained_regressor,  # type: ignore[no-untyped-def]
    target_code: str,
    target_value: float,
    max_gap_pct: float,
) -> None:
    regressor, corpus, _ = trained_regressor
    base = build_recipe(corpus[0][0])

    def _predict(candidate, code):  # type: ignore[no-untyped-def]
        p = regressor.predict(candidate, code, alpha=None)
        return p.predicted_value if p is not None else None

    optimiser = RecipeOptimiser(predictor=_predict)
    request = OptimisationRequest(
        base_recipe_id=base.id,
        targets=(PropertyTarget(property_code=target_code, target_value=target_value),),
        bounds=(
            ComponentBounds(component_name="Acrylic", min_percent=15.0, max_percent=50.0),
            ComponentBounds(component_name="TiO2", min_percent=5.0, max_percent=25.0),
            ComponentBounds(component_name="Water", min_percent=15.0, max_percent=70.0),
            ComponentBounds(component_name="Rheo", min_percent=0.05, max_percent=1.5),
            ComponentBounds(component_name="Texanol", min_percent=0.5, max_percent=3.5),
        ),
        max_iterations=40,
        population_size=25,
    )
    result = optimiser.optimise(base, request)
    predicted = result.predicted_values.get(target_code)
    assert predicted is not None, "optimiser did not return a prediction"

    # Also evaluate against ground truth to see how honest the model is.
    truth = measure(result.optimised_mass_percent, noise_std=0.0)
    truth_value = getattr(
        truth,
        {
            "gloss_60": "gloss_60",
            "viscosity_mid_shear": "viscosity_mid_shear",
        }[target_code],
    )
    gap_pct = abs(truth_value - target_value) / max(1e-9, target_value) * 100.0
    REPORT.optimiser_gap_pct[target_code] = gap_pct
    assert gap_pct <= max_gap_pct, (
        f"{target_code}: reality {truth_value:.2f} vs target {target_value:.2f} "
        f"→ {gap_pct:.1f}% gap"
    )


# ---------------------------------------------------------------------------
# 3. Assessment quality — catch defective recipes
# ---------------------------------------------------------------------------
_DEFECTIVE = [
    # No binder at all.
    RecipeSpec(
        mass_percent={"Water": 60.0, "TiO2": 30.0, "CaCO3": 10.0},
        intended_use="No binder — should be flagged",
    ),
    # Massive defoamer overdose.
    RecipeSpec(
        mass_percent={"Water": 40.0, "Acrylic": 30.0, "TiO2": 20.0, "Foamex": 10.0},
        intended_use="Defoamer overdose",
    ),
    # Only pigment + water.
    RecipeSpec(
        mass_percent={"Water": 40.0, "TiO2": 60.0},
        intended_use="Pigment slurry, no film former",
    ),
]


def test_assessment_flags_defective_recipes() -> None:
    detected = 0
    total = len(_DEFECTIVE)
    for spec in _DEFECTIVE:
        recipe = build_recipe(spec)
        assessment = RecipeAssessmentService.assess(recipe)
        if assessment.has_errors and assessment.maturity in {
            Maturity.DEFECTIVE,
            Maturity.DRAFT,
        }:
            detected += 1
    REPORT.assessment_true_positives = detected
    REPORT.assessment_false_negatives = total - detected
    assert detected == total, f"assessment missed {total - detected} defective recipes"


def test_assessment_accepts_a_reasonable_recipe() -> None:
    """A hand-tuned textbook recipe should NOT be flagged as defective."""
    healthy = RecipeSpec(
        mass_percent={
            "Water": 33.55,
            "Dispex": 0.6,
            "Foamex": 0.3,
            "Kathon": 0.15,
            "TiO2": 22.0,
            "CaCO3": 8.0,
            "Talc": 4.0,
            "Acrylic": 27.9,
            "Texanol": 1.5,
            "Rheo": 0.8,
            "PG": 1.2,
        },
        product_class=ProductClass.PREMIUM,
    )
    assessment = RecipeAssessmentService.assess(build_recipe(healthy))
    assert not assessment.has_errors, (
        f"healthy recipe was flagged: score={assessment.score}, "
        f"findings={[f.rule_id for f in assessment.findings]}"
    )
    assert assessment.maturity in {
        Maturity.LAB_READY,
        Maturity.PRODUCTION_READY,
        Maturity.REFERENCE,
    }


# ---------------------------------------------------------------------------
# 4. Pareto — does it show a real trade-off?
# ---------------------------------------------------------------------------
def test_pareto_finds_trade_off_between_gloss_and_voc(
    trained_regressor,  # type: ignore[no-untyped-def]
) -> None:
    regressor, corpus, _ = trained_regressor
    base = build_recipe(corpus[0][0])

    def _predict(candidate, code):  # type: ignore[no-untyped-def]
        p = regressor.predict(candidate, code, alpha=None)
        return p.predicted_value if p is not None else None

    optimiser = ParetoOptimiser(predictor=_predict)
    request = ParetoRequest(
        targets=(
            PropertyTarget(
                property_code="gloss_60",
                target_value=200.0,
                direction="maximise",
            ),
            PropertyTarget(
                property_code="voc_content",
                target_value=0.0,
                direction="minimise",
            ),
        ),
        bounds=(
            ComponentBounds(component_name="Acrylic", min_percent=15.0, max_percent=50.0),
            ComponentBounds(component_name="Texanol", min_percent=0.5, max_percent=4.0),
            ComponentBounds(component_name="Xylene", min_percent=0.0, max_percent=15.0),
        ),
        population_size=32,
        generations=12,
        seed=7,
    )
    # Corpus doesn't include Xylene originally — inject a small amount so the
    # optimiser has a lever for voc_content.
    base_spec = corpus[0][0]
    mass = {**base_spec.mass_percent}
    mass["Water"] = round(mass["Water"] - 1.0, 2)
    mass["Xylene"] = 1.0
    modified_spec = RecipeSpec(mass_percent=mass, product_class=base_spec.product_class)
    base = build_recipe(modified_spec)
    result = optimiser.optimise(base, request)

    front = result.front
    REPORT.pareto_front_size = len(front)
    if front:
        gloss_values = [p.objectives["gloss_60"] for p in front]
        REPORT.pareto_spread = max(gloss_values) - min(gloss_values)
    else:
        REPORT.pareto_spread = 0.0

    assert len(front) >= 1, "Pareto front empty"
    if len(front) > 1:
        # Real trade-off: at least some spread across the gloss axis
        # (otherwise the front collapses to one point and the search
        # didn't actually explore).
        assert REPORT.pareto_spread > 1.0, (
            f"Pareto front collapsed: gloss spread = {REPORT.pareto_spread:.2f}"
        )


# ---------------------------------------------------------------------------
# Session teardown: print report
# ---------------------------------------------------------------------------
def test_zzz_print_report() -> None:
    """Prints the full benchmark report after all other tests."""
    REPORT.print_summary()
