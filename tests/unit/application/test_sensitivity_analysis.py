"""Unit tests for SensitivityAnalysisUseCase — pure logic.

We wire the use case to a fake repo + fake regressor so the tests
focus on rebalancing arithmetic and skip-logic without needing
sklearn or a database.
"""

from __future__ import annotations

import pytest

from formulation_workbench.application.use_cases.sensitivity_analysis import (
    ComponentNotInRecipeError,
    SensitivityAnalysisUseCase,
    SensitivityQuery,
    _linspace,
    _rebalance_around,
)
from formulation_workbench.domain.entities.recipe import (
    Component,
    CompositionStage,
    ProductClass,
    Recipe,
)
from formulation_workbench.domain.value_objects.citation import Citation
from formulation_workbench.domain.value_objects.isbn import Isbn
from formulation_workbench.domain.value_objects.verification_status import VerificationState

pytestmark = [pytest.mark.unit]


def _recipe() -> Recipe:
    stage = CompositionStage(
        stage_number=1,
        name="Mix",
        description="",
        components=(
            Component(
                name="Water",
                cas_number="7732-18-5",
                function="vehicle",
                mass_percent=50.0,
                tolerance_percent=1.0,
            ),
            Component(
                name="Binder",
                cas_number="mixture",
                function="binder",
                mass_percent=30.0,
                tolerance_percent=1.0,
            ),
            Component(
                name="TiO2",
                cas_number="13463-67-7",
                function="pigment",
                mass_percent=20.0,
                tolerance_percent=1.0,
            ),
        ),
        process=None,
    )
    return Recipe(
        id="r1",
        category="Paints",
        subcategory="test",
        binder_type="Acrylic",
        product_class=ProductClass.STANDARD,
        intended_use="Test",
        stages=(stage,),
        primary_source=Citation(
            authors="Test",
            title="Test formulary",
            year=2020,
            publisher="Test publisher",
            isbn=Isbn("9780815513773"),
        ),
    )


class _FakeRepo:
    def __init__(self, recipes: dict[str, Recipe]) -> None:
        self._by_id = recipes

    async def get_by_id(self, rid: str) -> Recipe | None:
        return self._by_id.get(rid)

    # The use case only calls get_by_id, but keep the port contract.
    async def find_by_criteria(self, **_: object) -> list[Recipe]:  # pragma: no cover
        return list(self._by_id.values())

    async def save(self, recipe: Recipe) -> None:  # pragma: no cover
        self._by_id[recipe.id] = recipe

    async def delete(self, recipe_id: str) -> None:  # pragma: no cover
        self._by_id.pop(recipe_id, None)

    async def search_by_text(self, query: str, limit: int = 50) -> list[Recipe]:  # pragma: no cover
        return []

    async def count_by_status(self) -> dict[VerificationState, int]:  # pragma: no cover
        return {}

    async def get_all_versions(self, recipe_id: str) -> list[Recipe]:  # pragma: no cover
        return []


class _FakeRegressor:
    """Records predict() calls and returns a linear function of TiO2."""

    def __init__(self, codes: tuple[str, ...] = ("gloss_60",)) -> None:
        self.calls: list[tuple[str, str, float]] = []
        self._codes = codes

    def list_models(self) -> list[object]:
        # Minimal shape — the use case only reads `.property_code`.
        return [type("M", (), {"property_code": c})() for c in self._codes]

    def predict(self, recipe: Recipe, code: str, *, alpha: float | None = None):  # type: ignore[no-untyped-def]
        tio2 = next(
            (c.mass_percent for c in recipe.all_components if c.name == "TiO2"),
            0.0,
        )
        self.calls.append((recipe.id, code, tio2))

        # Signal: gloss_60 falls linearly with TiO2 (matches typical
        # paint physics well enough for the test).
        value = 100.0 - 2.0 * tio2 if code == "gloss_60" else tio2
        return type("P", (), {"predicted_value": value})()


# ---------------------------------------------------------------------------
# _linspace
# ---------------------------------------------------------------------------
def test_linspace_endpoints_and_count() -> None:
    xs = _linspace(10.0, 20.0, 5)
    assert xs[0] == 10.0
    assert xs[-1] == 20.0
    assert len(xs) == 5
    assert xs[2] == 15.0  # midpoint


# ---------------------------------------------------------------------------
# _rebalance_around
# ---------------------------------------------------------------------------
def test_rebalance_sum_stays_at_100() -> None:
    r = _recipe()
    perturbed = _rebalance_around(r, "TiO2", 25.0)
    total = sum(c.mass_percent for c in perturbed.all_components)
    assert abs(total - 100.0) < 1e-3


def test_rebalance_scales_others_pro_rata() -> None:
    # Original: Water 50, Binder 30, TiO2 20 → other_total = 80
    # New TiO2 = 25 → remaining = 75 → scale = 75/80 = 0.9375
    r = _recipe()
    perturbed = _rebalance_around(r, "TiO2", 25.0)
    water = next(c.mass_percent for c in perturbed.all_components if c.name == "Water")
    binder = next(c.mass_percent for c in perturbed.all_components if c.name == "Binder")
    assert abs(water - 50.0 * 0.9375) < 1e-3
    assert abs(binder - 30.0 * 0.9375) < 1e-3


def test_rebalance_refuses_when_no_free_mass() -> None:
    r = _recipe()
    # Setting TiO2 to 100 % leaves 0 % for the two other components.
    with pytest.raises(ValueError):
        _rebalance_around(r, "TiO2", 100.0)


def test_rebalance_refuses_unknown_component() -> None:
    r = _recipe()
    with pytest.raises(ValueError):
        _rebalance_around(r, "does-not-exist", 10.0)


# ---------------------------------------------------------------------------
# Use case
# ---------------------------------------------------------------------------
async def test_returns_none_when_recipe_missing() -> None:
    uc = SensitivityAnalysisUseCase(_FakeRepo({}), _FakeRegressor())  # type: ignore[arg-type]
    result = await uc.execute(
        SensitivityQuery(recipe_id="nope", component_name="TiO2", min_percent=0, max_percent=1)
    )
    assert result is None


async def test_raises_when_component_missing() -> None:
    r = _recipe()
    uc = SensitivityAnalysisUseCase(_FakeRepo({"r1": r}), _FakeRegressor())  # type: ignore[arg-type]
    with pytest.raises(ComponentNotInRecipeError):
        await uc.execute(
            SensitivityQuery(
                recipe_id="r1",
                component_name="missing",
                min_percent=0,
                max_percent=1,
            )
        )


async def test_sweeps_the_range_and_hits_every_model() -> None:
    r = _recipe()
    reg = _FakeRegressor(codes=("gloss_60", "voc_content"))
    uc = SensitivityAnalysisUseCase(_FakeRepo({"r1": r}), reg)  # type: ignore[arg-type]
    result = await uc.execute(
        SensitivityQuery(
            recipe_id="r1",
            component_name="TiO2",
            min_percent=10.0,
            max_percent=30.0,
            steps=5,
        )
    )
    assert result is not None
    assert result.baseline_percent == 20.0
    assert result.component_name == "TiO2"
    assert result.property_codes == ("gloss_60", "voc_content")
    assert len(result.points) == 5
    # Predictions monotonically decreasing for gloss_60 (linear -2×TiO2).
    gloss_curve = [p.predictions["gloss_60"] for p in result.points]
    assert gloss_curve == sorted(gloss_curve, reverse=True)
    # First and last targets bracket the requested range.
    assert result.points[0].target_percent == 10.0
    assert result.points[-1].target_percent == 30.0
    # Fake regressor was called ``steps × len(codes)`` times.
    assert len(reg.calls) == 5 * 2


async def test_skipped_step_when_range_exceeds_budget() -> None:
    r = _recipe()
    reg = _FakeRegressor()
    uc = SensitivityAnalysisUseCase(_FakeRepo({"r1": r}), reg)  # type: ignore[arg-type]
    result = await uc.execute(
        SensitivityQuery(
            recipe_id="r1",
            component_name="TiO2",
            min_percent=10.0,
            max_percent=100.0,  # top end has no mass budget
            steps=10,
        )
    )
    assert result is not None
    assert any(p.skipped for p in result.points)
    for point in result.points:
        if point.skipped:
            assert not point.predictions
            assert point.skip_reason
