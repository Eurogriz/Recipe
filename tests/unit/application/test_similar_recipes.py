"""Unit tests for FindSimilarRecipesUseCase.

Uses an in-memory fake ``RecipeRepository`` — the interesting logic
(cosine similarity, category filtering, self-exclusion, top-K
ordering) is entirely in the use case, so we avoid the SQLAlchemy
setup dance here.
"""

from __future__ import annotations

import pytest

from formulation_workbench.application.use_cases.search_recipes import SearchFilter
from formulation_workbench.application.use_cases.similar_recipes import (
    FindSimilarQuery,
    FindSimilarRecipesUseCase,
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


def _make_recipe(
    rid: str,
    *,
    category: str = "Paints",
    binder_pct: float = 30.0,
    pigment_pct: float = 20.0,
) -> Recipe:
    water = round(100.0 - binder_pct - pigment_pct, 3)
    stage = CompositionStage(
        stage_number=1,
        name="Mix",
        description="",
        components=(
            Component(
                name="Water",
                cas_number="7732-18-5",
                function="vehicle",
                mass_percent=water,
                tolerance_percent=1.0,
            ),
            Component(
                name="Acrylic",
                cas_number="mixture",
                function="binder",
                mass_percent=binder_pct,
                tolerance_percent=1.0,
            ),
            Component(
                name="TiO2",
                cas_number="13463-67-7",
                function="pigment",
                mass_percent=pigment_pct,
                tolerance_percent=1.0,
            ),
        ),
        process=None,
    )
    return Recipe(
        id=rid,
        category=category,
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
        cross_references=(),
    )


class FakeRepo:
    def __init__(self, recipes: list[Recipe]) -> None:
        self._by_id = {r.id: r for r in recipes}

    async def get_by_id(self, rid: str) -> Recipe | None:
        return self._by_id.get(rid)

    async def find_by_criteria(
        self,
        category: str | None = None,
        subcategory: str | None = None,
        product_class: str | None = None,
        status: VerificationState | None = None,
        tags: list[str] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Recipe]:
        rs = list(self._by_id.values())
        if category is not None:
            rs = [r for r in rs if r.category == category]
        return rs[offset : offset + limit]


async def test_returns_none_when_reference_missing() -> None:
    uc = FindSimilarRecipesUseCase(FakeRepo([]))  # type: ignore[arg-type]
    result = await uc.execute(FindSimilarQuery(recipe_id="nope"))
    assert result is None


async def test_ranks_by_composition_similarity() -> None:
    # Reference: binder 30, pigment 20.  Two close, one far, one different category.
    ref = _make_recipe("ref", binder_pct=30.0, pigment_pct=20.0)
    close_a = _make_recipe("close_a", binder_pct=31.0, pigment_pct=19.0)
    close_b = _make_recipe("close_b", binder_pct=28.0, pigment_pct=22.0)
    far = _make_recipe("far", binder_pct=60.0, pigment_pct=1.0)
    other_cat = _make_recipe("other_cat", category="Sealants", binder_pct=30.0, pigment_pct=20.0)
    uc = FindSimilarRecipesUseCase(FakeRepo([ref, close_a, close_b, far, other_cat]))  # type: ignore[arg-type]

    result = await uc.execute(FindSimilarQuery(recipe_id="ref", top_k=3))
    assert result is not None
    ids = [m.recipe_id for m in result]
    assert "ref" not in ids  # self-excluded
    assert "other_cat" not in ids  # different category filtered out
    assert ids[0] in {"close_a", "close_b"}  # nearest first
    assert result[0].similarity >= result[-1].similarity
    assert all(0.0 <= m.similarity <= 1.0 for m in result)


async def test_top_k_and_min_similarity_gate() -> None:
    ref = _make_recipe("ref", binder_pct=30.0, pigment_pct=20.0)
    close = _make_recipe("close", binder_pct=30.1, pigment_pct=19.9)
    far = _make_recipe("far", binder_pct=1.0, pigment_pct=99.0)
    uc = FindSimilarRecipesUseCase(FakeRepo([ref, close, far]))  # type: ignore[arg-type]

    top_1 = await uc.execute(FindSimilarQuery(recipe_id="ref", top_k=1))
    assert top_1 is not None
    assert len(top_1) == 1
    assert top_1[0].recipe_id == "close"

    strict = await uc.execute(FindSimilarQuery(recipe_id="ref", top_k=10, min_similarity=0.99))
    assert strict is not None
    for match in strict:
        assert match.similarity >= 0.99


async def test_cross_category_when_flag_disabled() -> None:
    ref = _make_recipe("ref", binder_pct=30.0, pigment_pct=20.0)
    other_cat = _make_recipe("other_cat", category="Sealants", binder_pct=30.0, pigment_pct=20.0)
    uc = FindSimilarRecipesUseCase(FakeRepo([ref, other_cat]))  # type: ignore[arg-type]

    result = await uc.execute(FindSimilarQuery(recipe_id="ref", same_category_only=False))
    assert result is not None
    ids = [m.recipe_id for m in result]
    assert "other_cat" in ids


# SearchFilter is imported so IDEs can surface breaking changes even
# though the use case only references it via a local import inside
# execute() (kept to avoid an import cycle).
_ = SearchFilter
