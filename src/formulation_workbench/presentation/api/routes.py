"""HTTP routes.

The read endpoints are unauthenticated only when ``FW_API_TOKEN`` is
empty (development).  Write endpoints (``POST``, ``PUT``, ``PATCH``,
``DELETE``, verify/reject/submit) always require an authenticated
principal (see :mod:`.auth`).
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ... import __version__
from ...application.dto.recipe_dto import RecipeSummaryDto
from ...application.use_cases.create_recipe import CreateRecipeCommand
from ...application.use_cases.delete_recipe import DeleteRecipeCommand
from ...application.use_cases.get_recipe import GetRecipeByIdQuery
from ...application.use_cases.search_recipes import (
    GetCatalogStatisticsQuery,
    SearchFilter,
)
from ...application.use_cases.update_recipe import UpdateRecipeCommand
from ...application.use_cases.verification_workflow import (
    RejectRecipeCommand,
    SubmitRecipeForReviewCommand,
    VerifyRecipeCommand,
)
from ...domain.entities.recipe import InvalidRecipeError
from ...domain.exceptions import DomainError
from ...infrastructure.config import AppSettings
from ...infrastructure.di import Container
from .auth import Principal, require_reader, require_writer
from .dependencies import get_container, get_settings
from .mappers import to_recipe
from .schemas import (
    AppInfo,
    CatalogStats,
    CreateRecipeRequest,
    ErrorResponse,
    HealthResponse,
    RecipeSummary,
    RejectRequest,
    SearchResponse,
    SubmitReviewRequest,
    UpdateRecipeRequest,
    ValidationErrorResponse,
    VerifyRequest,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Ops
# ---------------------------------------------------------------------------
@router.get(
    "/health",
    response_model=HealthResponse,
    tags=["ops"],
    summary="Liveness / readiness probe",
    description="Always returns 200 when the process is up. No auth required.",
)
async def health(settings: Annotated[AppSettings, Depends(get_settings)]) -> HealthResponse:
    return HealthResponse(version=__version__, environment=settings.environment)


@router.get(
    "/info",
    response_model=AppInfo,
    tags=["ops"],
    summary="Build & runtime information",
)
async def app_info(settings: Annotated[AppSettings, Depends(get_settings)]) -> AppInfo:
    import os
    import platform
    import sys

    return AppInfo(
        name="formulation-workbench",
        version=__version__,
        environment=settings.environment,
        python=sys.version.split()[0],
        platform=platform.platform(terse=True),
        git_sha=os.environ.get("FW_GIT_SHA", "unknown"),
        build_date=os.environ.get("FW_BUILD_DATE", "unknown"),
    )


# ---------------------------------------------------------------------------
# Recipes — read
# ---------------------------------------------------------------------------
_Responses = dict[int | str, dict[str, Any]]

_UNAUTHORIZED: _Responses = {
    status.HTTP_401_UNAUTHORIZED: {
        "model": ErrorResponse,
        "description": "Missing or invalid token",
    },
}
_FORBIDDEN: _Responses = {
    status.HTTP_403_FORBIDDEN: {"model": ErrorResponse, "description": "Insufficient scope"},
}
_NOT_FOUND: _Responses = {
    status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "Recipe not found"},
}
_VALIDATION: _Responses = {
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "model": ValidationErrorResponse,
        "description": "Invalid payload",
    },
}
_CONFLICT: _Responses = {
    status.HTTP_409_CONFLICT: {"model": ErrorResponse, "description": "State conflict"},
}


@router.get(
    "/recipes",
    response_model=SearchResponse,
    tags=["recipes"],
    dependencies=[Depends(require_reader)],
    summary="Search / list recipes",
    responses={**_UNAUTHORIZED},
)
async def list_recipes(
    container: Annotated[Container, Depends(get_container)],
    q: str = Query("", description="Free-text query."),
    category: list[str] = Query(default_factory=list),
    product_class: list[str] = Query(default_factory=list),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> SearchResponse:
    result = await container.search_recipes.execute(
        SearchFilter(
            text_query=q,
            categories=tuple(category),
            product_classes=tuple(product_class),
            limit=limit,
            offset=offset,
        )
    )
    items = [
        RecipeSummary.model_validate(asdict(RecipeSummaryDto.from_recipe(r)))
        for r in result.recipes
    ]
    return SearchResponse(
        items=items,
        total_count=result.total_count,
        limit=result.limit,
        offset=result.offset,
        has_more=result.has_more,
    )


@router.get(
    "/recipes/{recipe_id}",
    response_model=RecipeSummary,
    tags=["recipes"],
    dependencies=[Depends(require_reader)],
    responses={**_UNAUTHORIZED, **_NOT_FOUND},
)
async def get_recipe(
    recipe_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> RecipeSummary:
    recipe = await container.get_recipe.execute(GetRecipeByIdQuery(recipe_id=recipe_id))
    if recipe is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recipe not found")
    return RecipeSummary.model_validate(asdict(RecipeSummaryDto.from_recipe(recipe)))


@router.get(
    "/catalog/stats",
    response_model=CatalogStats,
    tags=["catalog"],
    dependencies=[Depends(require_reader)],
    responses={**_UNAUTHORIZED},
)
async def catalog_stats(
    container: Annotated[Container, Depends(get_container)],
) -> CatalogStats:
    result = await container.catalog_stats.execute(GetCatalogStatisticsQuery())
    return CatalogStats(
        total=result.total,
        by_status={s.value: n for s, n in result.by_status.items()},
    )


# ---------------------------------------------------------------------------
# Recipes — write
# ---------------------------------------------------------------------------
def _recipe_summary(recipe) -> RecipeSummary:  # type: ignore[no-untyped-def]
    return RecipeSummary.model_validate(asdict(RecipeSummaryDto.from_recipe(recipe)))


@router.post(
    "/recipes",
    response_model=RecipeSummary,
    status_code=status.HTTP_201_CREATED,
    tags=["recipes"],
    summary="Create a new recipe",
    responses={**_UNAUTHORIZED, **_FORBIDDEN, **_VALIDATION},
)
async def create_recipe(
    payload: CreateRecipeRequest,
    container: Annotated[Container, Depends(get_container)],
    principal: Annotated[Principal, Depends(require_writer)],
) -> RecipeSummary:
    try:
        recipe = to_recipe(payload)
    except (InvalidRecipeError, DomainError, ValueError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    created = await container.create_recipe.execute(
        CreateRecipeCommand(recipe=recipe, actor=principal.subject)
    )
    return _recipe_summary(created)


@router.put(
    "/recipes/{recipe_id}",
    response_model=RecipeSummary,
    tags=["recipes"],
    summary="Replace an existing recipe",
    responses={**_UNAUTHORIZED, **_FORBIDDEN, **_NOT_FOUND, **_CONFLICT, **_VALIDATION},
)
async def replace_recipe(
    recipe_id: str,
    payload: UpdateRecipeRequest,
    container: Annotated[Container, Depends(get_container)],
    principal: Annotated[Principal, Depends(require_writer)],
) -> RecipeSummary:
    existing = await container.get_recipe.execute(GetRecipeByIdQuery(recipe_id=recipe_id))
    if existing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recipe not found")
    try:
        recipe = to_recipe(payload, recipe_id=recipe_id)
    except (InvalidRecipeError, DomainError, ValueError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    try:
        updated = await container.update_recipe.execute(
            UpdateRecipeCommand(recipe=recipe, actor=principal.subject)
        )
    except ValueError as exc:
        # Verified recipes cannot be updated directly.
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _recipe_summary(updated)


@router.delete(
    "/recipes/{recipe_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["recipes"],
    summary="Delete (soft or hard) a recipe",
    responses={**_UNAUTHORIZED, **_FORBIDDEN, **_NOT_FOUND},
)
async def delete_recipe(
    recipe_id: str,
    container: Annotated[Container, Depends(get_container)],
    principal: Annotated[Principal, Depends(require_writer)],
    hard: bool = Query(False, description="If true, physically remove; otherwise mark rejected."),
) -> None:
    existing = await container.get_recipe.execute(GetRecipeByIdQuery(recipe_id=recipe_id))
    if existing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recipe not found")
    await container.delete_recipe.execute(
        DeleteRecipeCommand(recipe_id=recipe_id, actor=principal.subject, hard_delete=hard)
    )


# ---------------------------------------------------------------------------
# Verification workflow
# ---------------------------------------------------------------------------
@router.post(
    "/recipes/{recipe_id}/submit-review",
    response_model=RecipeSummary,
    tags=["workflow"],
    summary="Submit a Draft recipe for peer review",
    responses={**_UNAUTHORIZED, **_FORBIDDEN, **_NOT_FOUND, **_CONFLICT},
)
async def submit_for_review(
    recipe_id: str,
    payload: SubmitReviewRequest,
    container: Annotated[Container, Depends(get_container)],
    principal: Annotated[Principal, Depends(require_writer)],
) -> RecipeSummary:
    try:
        result = await container.submit_for_review.execute(
            SubmitRecipeForReviewCommand(
                recipe_id=recipe_id,
                actor=payload.actor or principal.subject,
                comment=payload.comment,
            )
        )
    except ValueError as exc:
        if "not found" in str(exc).lower():
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _recipe_summary(result)


@router.post(
    "/recipes/{recipe_id}/verify",
    response_model=RecipeSummary,
    tags=["workflow"],
    summary="Add one peer verification to a recipe",
    responses={**_UNAUTHORIZED, **_FORBIDDEN, **_NOT_FOUND, **_CONFLICT},
)
async def verify_recipe(
    recipe_id: str,
    payload: VerifyRequest,
    container: Annotated[Container, Depends(get_container)],
    principal: Annotated[Principal, Depends(require_writer)],
) -> RecipeSummary:
    try:
        result = await container.verify_recipe.execute(
            VerifyRecipeCommand(
                recipe_id=recipe_id,
                verifier=payload.verifier or principal.subject,
                source_citation_id=payload.source_citation_id,
                comment=payload.comment,
            )
        )
    except ValueError as exc:
        if "not found" in str(exc).lower():
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _recipe_summary(result)


@router.post(
    "/recipes/{recipe_id}/reject",
    response_model=RecipeSummary,
    tags=["workflow"],
    summary="Reject a recipe (auditor / admin)",
    responses={**_UNAUTHORIZED, **_FORBIDDEN, **_NOT_FOUND},
)
async def reject_recipe(
    recipe_id: str,
    payload: RejectRequest,
    container: Annotated[Container, Depends(get_container)],
    principal: Annotated[Principal, Depends(require_writer)],
) -> RecipeSummary:
    try:
        result = await container.reject_recipe.execute(
            RejectRecipeCommand(
                recipe_id=recipe_id, actor=payload.actor or principal.subject, reason=payload.reason
            )
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return _recipe_summary(result)


__all__ = ["router"]
