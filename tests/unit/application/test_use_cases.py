"""Unit tests for use cases.

Tests use cases with mock repository and audit logger.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from formulation_workbench.application.use_cases.create_recipe import (
    CreateRecipeCommand,
    CreateRecipeUseCase,
)
from formulation_workbench.application.use_cases.delete_recipe import (
    DeleteRecipeCommand,
    DeleteRecipeUseCase,
)
from formulation_workbench.application.use_cases.search_recipes import (
    SearchFilter,
    SearchRecipesUseCase,
)
from formulation_workbench.application.use_cases.update_recipe import (
    UpdateRecipeCommand,
    UpdateRecipeUseCase,
)
from formulation_workbench.application.use_cases.verification_workflow import (
    SubmitRecipeForReviewCommand,
    SubmitRecipeForReviewUseCase,
    VerifyRecipeCommand,
    VerifyRecipeUseCase,
)
from formulation_workbench.domain.entities.recipe import (
    Component,
    CompositionStage,
    ProcessParams,
    ProductClass,
    Recipe,
)
from formulation_workbench.domain.value_objects.citation import Citation
from formulation_workbench.domain.value_objects.isbn import Isbn
from formulation_workbench.domain.value_objects.verification_status import VerificationState


def make_recipe(
    id: str = "test-recipe-id",
    status_state: VerificationState = VerificationState.DRAFT,
    verification_count: int = 0,
    version: int = 1,
) -> Recipe:
    citation = Citation(
        authors="Flick, E.W.",
        title="Water-Based Paint Formulations, Vol. 3",
        year=1995,
        publisher="Noyes Publications",
        isbn=Isbn("9780815513773"),
        page_or_formula="pp. 78-82",
    )
    from formulation_workbench.domain.value_objects.verification_status import VerificationStatus

    return Recipe(
        id=id,
        category="Краски",
        subcategory="Водно-дисперсионные",
        binder_type="Акриловая",
        product_class=ProductClass.PREMIUM,
        intended_use="Test interior paint",
        stages=(
            CompositionStage(
                stage_number=1,
                name="Mixing",
                description="Mix all components",
                components=(
                    Component(
                        name="Water", cas_number="7732-18-5", function="vehicle", mass_percent=50.0
                    ),
                    Component(
                        name="Binder", cas_number="mixture", function="binder", mass_percent=40.0
                    ),
                    Component(
                        name="TiO2", cas_number="13463-67-7", function="pigment", mass_percent=10.0
                    ),
                ),
                process=ProcessParams(equipment="Disperser"),
            ),
        ),
        primary_source=citation,
        status=VerificationStatus(state=status_state, verification_count=verification_count),
        version=version,
    )


class TestCreateRecipeUseCase:
    """Tests for CreateRecipeUseCase."""

    async def test_create_recipe_persists_and_logs(self) -> None:
        repo = AsyncMock()
        audit = AsyncMock()
        use_case = CreateRecipeUseCase(repo, audit)
        recipe = make_recipe()
        command = CreateRecipeCommand(recipe=recipe, actor="user1")

        result = await use_case.execute(command)

        repo.save.assert_called_once_with(recipe)
        audit.log.assert_called_once()
        assert result.id == recipe.id


class TestUpdateRecipeUseCase:
    """Tests for UpdateRecipeUseCase."""

    async def test_update_draft_recipe_succeeds(self) -> None:
        repo = AsyncMock()
        audit = AsyncMock()
        repo.get_by_id.return_value = make_recipe(status_state=VerificationState.DRAFT)
        use_case = UpdateRecipeUseCase(repo, audit)
        new_recipe = make_recipe()
        command = UpdateRecipeCommand(
            recipe=new_recipe, actor="user1", changes_summary="Fixed typo"
        )

        result = await use_case.execute(command)

        repo.save.assert_called_once_with(new_recipe)
        audit.log.assert_called_once()
        assert result.id == new_recipe.id

    async def test_update_verified_recipe_rejected(self) -> None:
        repo = AsyncMock()
        audit = AsyncMock()
        existing = make_recipe(status_state=VerificationState.VERIFIED, verification_count=3)
        repo.get_by_id.return_value = existing
        use_case = UpdateRecipeUseCase(repo, audit)
        # Attempting to update with same version
        command = UpdateRecipeCommand(
            recipe=make_recipe(status_state=VerificationState.VERIFIED, verification_count=3),
            actor="user1",
        )

        with pytest.raises(ValueError, match="Verified"):
            await use_case.execute(command)


class TestDeleteRecipeUseCase:
    """Tests for DeleteRecipeUseCase."""

    async def test_soft_delete_marks_as_rejected(self) -> None:
        repo = AsyncMock()
        audit = AsyncMock()
        repo.get_by_id.return_value = make_recipe()
        use_case = DeleteRecipeUseCase(repo, audit)
        command = DeleteRecipeCommand(recipe_id="test-recipe-id", actor="user1", hard_delete=False)

        await use_case.execute(command)

        repo.save.assert_called_once()
        audit.log.assert_called_once_with(
            action="Rejected",
            aggregate_id="test-recipe-id",
            actor="user1",
            metadata={"soft_delete": True},
        )

    async def test_hard_delete_removes_from_db(self) -> None:
        repo = AsyncMock()
        audit = AsyncMock()
        repo.get_by_id.return_value = make_recipe()
        use_case = DeleteRecipeUseCase(repo, audit)
        command = DeleteRecipeCommand(recipe_id="test-recipe-id", actor="user1", hard_delete=True)

        await use_case.execute(command)

        repo.delete.assert_called_once_with("test-recipe-id")
        audit.log.assert_called_once_with(
            action="Deleted",
            aggregate_id="test-recipe-id",
            actor="user1",
            metadata={"hard_delete": True},
        )


class TestVerificationWorkflowUseCases:
    """Tests for verification workflow."""

    async def test_submit_for_review_succeeds(self) -> None:
        repo = AsyncMock()
        audit = AsyncMock()
        repo.get_by_id.return_value = make_recipe()
        use_case = SubmitRecipeForReviewUseCase(repo, audit)
        command = SubmitRecipeForReviewCommand(recipe_id="test-recipe-id", actor="user1")

        result = await use_case.execute(command)

        assert result.status.state == VerificationState.PENDING_REVIEW
        repo.save.assert_called_once()
        audit.log.assert_called_once()

    async def test_verify_three_times_reaches_verified(self) -> None:
        repo = AsyncMock()
        audit = AsyncMock()
        current = {"recipe": make_recipe(status_state=VerificationState.PENDING_REVIEW)}

        async def _get(rid: str) -> Recipe:
            return current["recipe"]

        async def _save(r: Recipe) -> None:
            current["recipe"] = r

        repo.get_by_id.side_effect = _get
        repo.save.side_effect = _save
        use_case = VerifyRecipeUseCase(repo, audit)

        for i in range(3):
            cmd = VerifyRecipeCommand(
                recipe_id="test-recipe-id",
                verifier=f"user{i}",
                source_citation_id=f"cite{i}",
            )
            result = await use_case.execute(cmd)

        assert result.status.state == VerificationState.VERIFIED
        assert result.status.verification_count == 3

    async def test_verify_draft_recipe_rejected(self) -> None:
        repo = AsyncMock()
        audit = AsyncMock()
        repo.get_by_id.return_value = make_recipe(status_state=VerificationState.DRAFT)
        use_case = VerifyRecipeUseCase(repo, audit)
        command = VerifyRecipeCommand(
            recipe_id="test-recipe-id",
            verifier="user1",
            source_citation_id="cite1",
        )

        with pytest.raises(ValueError, match="PendingReview"):
            await use_case.execute(command)


class TestSearchRecipesUseCase:
    """Tests for SearchRecipesUseCase."""

    async def test_search_with_text_query(self) -> None:
        repo = AsyncMock()
        recipe = make_recipe()
        repo.search_by_text.return_value = [recipe]
        use_case = SearchRecipesUseCase(repo)

        filter_ = SearchFilter(text_query="краска", limit=10)
        result = await use_case.execute(filter_)

        repo.search_by_text.assert_called_once()
        assert len(result.recipes) == 1
        assert result.recipes[0].id == recipe.id

    async def test_search_with_filters(self) -> None:
        repo = AsyncMock()
        recipe = make_recipe()
        repo.find_by_criteria.return_value = [recipe]
        use_case = SearchRecipesUseCase(repo)

        filter_ = SearchFilter(
            categories=("Краски",),
            product_classes=("Premium",),
            limit=10,
        )
        result = await use_case.execute(filter_)

        repo.find_by_criteria.assert_called_once()
        assert len(result.recipes) == 1

    async def test_search_pagination(self) -> None:
        repo = AsyncMock()
        # Return limit + 1 to indicate has_more
        recipes = [make_recipe(id=f"recipe-{i}") for i in range(11)]
        repo.search_by_text.return_value = recipes
        use_case = SearchRecipesUseCase(repo)

        filter_ = SearchFilter(text_query="test", limit=10)
        result = await use_case.execute(filter_)

        assert len(result.recipes) == 10  # Trimmed to limit
        assert result.has_more is True
