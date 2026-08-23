"""Unit tests for the 2D what-if heatmap use case."""

from __future__ import annotations

import pytest

from formulation_workbench.application.use_cases.sensitivity_analysis import (
    ComponentNotInRecipeError,
)
from formulation_workbench.application.use_cases.sensitivity_heatmap import (
    HeatmapQuery,
    SensitivityHeatmapUseCase,
    _rebalance_pair,
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
            authors="T",
            title="T",
            year=2020,
            publisher="T",
            isbn=Isbn("9780815513773"),
        ),
    )


class _FakeRepo:
    def __init__(self, recipes: dict[str, Recipe]) -> None:
        self._by_id = recipes

    async def get_by_id(self, rid: str) -> Recipe | None:
        return self._by_id.get(rid)

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
    """Returns a smooth function of the two target components."""

    def list_models(self) -> list[object]:  # pragma: no cover
        return [type("M", (), {"property_code": "gloss_60"})()]

    def predict(self, recipe, code, *, alpha=None):  # type: ignore[no-untyped-def]
        tio2 = next((c.mass_percent for c in recipe.all_components if c.name == "TiO2"), 0.0)
        binder = next((c.mass_percent for c in recipe.all_components if c.name == "Binder"), 0.0)
        # Gloss goes up with binder, down with TiO2 — classic paint physics.
        value = 100.0 + 0.5 * binder - 2.0 * tio2
        return type("P", (), {"predicted_value": value})()


# ---------------------------------------------------------------------------
# _rebalance_pair
# ---------------------------------------------------------------------------
def test_rebalance_pair_sum_stays_at_100() -> None:
    r = _recipe()
    perturbed = _rebalance_pair(r, "TiO2", 25.0, "Binder", 35.0)
    total = sum(c.mass_percent for c in perturbed.all_components)
    assert abs(total - 100.0) < 1e-3


def test_rebalance_pair_scales_others_pro_rata() -> None:
    # Original: Water 50, Binder 30, TiO2 20.  other_total (Water) = 50.
    # New Binder=35, TiO2=25 → remaining = 40 → scale = 40/50 = 0.8
    r = _recipe()
    perturbed = _rebalance_pair(r, "TiO2", 25.0, "Binder", 35.0)
    water = next(c.mass_percent for c in perturbed.all_components if c.name == "Water")
    assert abs(water - 50.0 * 0.8) < 1e-3


def test_rebalance_pair_refuses_when_over_budget() -> None:
    r = _recipe()
    with pytest.raises(ValueError):
        _rebalance_pair(r, "TiO2", 60.0, "Binder", 60.0)  # 120% before scaling


# ---------------------------------------------------------------------------
# Use case
# ---------------------------------------------------------------------------
async def test_returns_none_when_recipe_missing() -> None:
    uc = SensitivityHeatmapUseCase(_FakeRepo({}), _FakeRegressor())  # type: ignore[arg-type]
    result = await uc.execute(
        HeatmapQuery(
            recipe_id="nope",
            component_a="TiO2",
            component_b="Binder",
            property_code="gloss_60",
            a_min=10,
            a_max=25,
            b_min=20,
            b_max=40,
        )
    )
    assert result is None


async def test_raises_for_same_component() -> None:
    r = _recipe()
    uc = SensitivityHeatmapUseCase(_FakeRepo({"r1": r}), _FakeRegressor())  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        await uc.execute(
            HeatmapQuery(
                recipe_id="r1",
                component_a="TiO2",
                component_b="TiO2",
                property_code="gloss_60",
                a_min=10,
                a_max=25,
                b_min=10,
                b_max=25,
            )
        )


async def test_raises_for_missing_component() -> None:
    r = _recipe()
    uc = SensitivityHeatmapUseCase(_FakeRepo({"r1": r}), _FakeRegressor())  # type: ignore[arg-type]
    with pytest.raises(ComponentNotInRecipeError):
        await uc.execute(
            HeatmapQuery(
                recipe_id="r1",
                component_a="unknown",
                component_b="Binder",
                property_code="gloss_60",
                a_min=10,
                a_max=25,
                b_min=20,
                b_max=40,
            )
        )


async def test_grid_shape_and_monotonic_axes() -> None:
    r = _recipe()
    uc = SensitivityHeatmapUseCase(_FakeRepo({"r1": r}), _FakeRegressor())  # type: ignore[arg-type]
    result = await uc.execute(
        HeatmapQuery(
            recipe_id="r1",
            component_a="TiO2",
            component_b="Binder",
            property_code="gloss_60",
            a_min=10,
            a_max=25,
            b_min=20,
            b_max=40,
            steps_a=4,
            steps_b=5,
        )
    )
    assert result is not None
    assert len(result.a_values) == 4
    assert len(result.b_values) == 5
    assert len(result.values) == 4
    for row in result.values:
        assert len(row) == 5

    # Along axis A (TiO2 ↑), gloss should fall.
    for j in range(5):
        col = [result.values[i][j] for i in range(4)]
        # None-safe: predictor always returns a value here, so no Nones.
        assert col == sorted(col, reverse=True), col
    # Along axis B (binder ↑), gloss should rise.
    for i in range(4):
        row = result.values[i]
        assert list(row) == sorted(row), row

    assert result.z_min is not None
    assert result.z_max is not None
    assert result.z_min <= result.z_max


async def test_cap_on_cells() -> None:
    r = _recipe()
    uc = SensitivityHeatmapUseCase(_FakeRepo({"r1": r}), _FakeRegressor())  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        # 25 × 25 = 625 > MAX_CELLS (400).
        await uc.execute(
            HeatmapQuery(
                recipe_id="r1",
                component_a="TiO2",
                component_b="Binder",
                property_code="gloss_60",
                a_min=10,
                a_max=25,
                b_min=20,
                b_max=40,
                steps_a=25,
                steps_b=25,
            )
        )


async def test_infeasible_cells_become_null() -> None:
    r = _recipe()
    uc = SensitivityHeatmapUseCase(_FakeRepo({"r1": r}), _FakeRegressor())  # type: ignore[arg-type]
    result = await uc.execute(
        HeatmapQuery(
            recipe_id="r1",
            component_a="TiO2",
            component_b="Binder",
            property_code="gloss_60",
            a_min=5,
            a_max=60,  # top of A + top of B > 100 → some cells infeasible
            b_min=5,
            b_max=60,
            steps_a=6,
            steps_b=6,
        )
    )
    assert result is not None
    flat = [v for row in result.values for v in row]
    assert any(v is None for v in flat), "expected at least one infeasible cell"
    assert any(v is not None for v in flat), "expected at least one feasible cell"
