"""HTTP routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ... import __version__
from ...application.dto.recipe_dto import RecipeSummaryDto
from ...application.use_cases.search_recipes import (
    GetCatalogStatisticsQuery,
    SearchFilter,
)
from ...infrastructure.config import AppSettings
from ...infrastructure.di import Container
from .dependencies import get_container, get_settings, require_api_token
from .schemas import CatalogStats, HealthResponse, RecipeSummary, SearchResponse

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    tags=["ops"],
    summary="Liveness/readiness probe",
)
async def health(settings: Annotated[AppSettings, Depends(get_settings)]) -> HealthResponse:
    return HealthResponse(version=__version__, environment=settings.environment)


@router.get(
    "/recipes",
    response_model=SearchResponse,
    tags=["recipes"],
    dependencies=[Depends(require_api_token)],
    summary="Search / list recipes",
)
async def list_recipes(
    container: Annotated[Container, Depends(get_container)],
    q: str = Query("", description="Free-text query"),
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
        RecipeSummary.model_validate(RecipeSummaryDto.from_recipe(r).__dict__)
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
    dependencies=[Depends(require_api_token)],
    responses={404: {"description": "Recipe not found"}},
)
async def get_recipe(
    recipe_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> RecipeSummary:
    from ...application.use_cases.get_recipe import GetRecipeByIdQuery

    recipe = await container.get_recipe.execute(GetRecipeByIdQuery(recipe_id=recipe_id))
    if recipe is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recipe not found")
    return RecipeSummary.model_validate(RecipeSummaryDto.from_recipe(recipe).__dict__)


@router.get(
    "/catalog/stats",
    response_model=CatalogStats,
    tags=["catalog"],
    dependencies=[Depends(require_api_token)],
)
async def catalog_stats(
    container: Annotated[Container, Depends(get_container)],
) -> CatalogStats:
    result = await container.catalog_stats.execute(GetCatalogStatisticsQuery())
    return CatalogStats(
        total=result.total,
        by_status={s.value: n for s, n in result.by_status.items()},
    )


__all__ = ["router"]
