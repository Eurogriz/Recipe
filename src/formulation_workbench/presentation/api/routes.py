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
from ...application.use_cases.assess_recipe import AssessRecipeQuery
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
    ApplyLabResultsIn,
    ApplyLabResultsOut,
    CatalogStats,
    CostLineOut,
    CostRequest,
    CreateRecipeRequest,
    DeviationOut,
    ErrorResponse,
    ExperimentCompletionIn,
    ExperimentOut,
    ExperimentPlanIn,
    HealthResponse,
    ProcessMeasuredIn,
    RecipeAssessmentOut,
    RecipeCostOut,
    RecipeSummary,
    RegulatoryFindingOut,
    RejectRequest,
    RuleFindingOut,
    SearchResponse,
    SubmitReviewRequest,
    UpdateRecipeRequest,
    ValidationErrorResponse,
    VerificationViolationOut,
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


@router.get(
    "/recipes/{recipe_id}/assessment",
    response_model=RecipeAssessmentOut,
    tags=["recipes", "assessment"],
    dependencies=[Depends(require_reader)],
    summary="Full technological + bibliographic quality assessment",
    responses={**_UNAUTHORIZED, **_NOT_FOUND},
)
async def assess_recipe(
    recipe_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> RecipeAssessmentOut:
    assessment = await container.assess_recipe.execute(AssessRecipeQuery(recipe_id=recipe_id))
    if assessment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recipe not found")
    return RecipeAssessmentOut(
        recipe_id=recipe_id,
        score=assessment.score,
        maturity=assessment.maturity.value,
        findings=[
            RuleFindingOut(
                rule_id=f.rule_id,
                severity=f.severity.value,
                message=f.message,
                reference=f.reference,
            )
            for f in assessment.findings
        ],
        verification_violations=[
            VerificationViolationOut(rule=v.rule, message=v.message)
            for v in assessment.verification_violations
        ],
        regulatory_findings=[
            RegulatoryFindingOut(
                rule_id=r.rule_id,
                severity=r.severity.value,
                substance=r.substance,
                cas_number=r.cas_number,
                message=r.message,
                reference=r.reference,
            )
            for r in assessment.regulatory_findings
        ],
        summary=assessment.summary(),
    )


# ---------------------------------------------------------------------------
# Cost
# ---------------------------------------------------------------------------
@router.post(
    "/recipes/{recipe_id}/cost",
    response_model=RecipeCostOut,
    tags=["recipes", "cost"],
    dependencies=[Depends(require_reader)],
    summary="Calculate per-kg / per-litre cost for a supplied price list",
    responses={**_UNAUTHORIZED, **_NOT_FOUND, **_VALIDATION},
)
async def cost_recipe(
    recipe_id: str,
    payload: CostRequest,
    container: Annotated[Container, Depends(get_container)],
) -> RecipeCostOut:
    from ...application.use_cases.calculate_cost import CalculateRecipeCostCommand
    from ...domain.value_objects.cost import InvalidPriceError, Price

    prices: dict[str, Price] = {}
    for item in payload.prices:
        try:
            prices[item.component_name] = Price(
                amount=item.amount, currency=item.currency, unit=item.unit
            )
        except InvalidPriceError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    cost = await container.calculate_cost.execute(
        CalculateRecipeCostCommand(recipe_id=recipe_id, prices=prices)
    )
    if cost is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recipe not found")

    return RecipeCostOut(
        recipe_id=recipe_id,
        currency=cost.currency,
        cost_per_kg=round(cost.total_cost_per_kg, 6),
        cost_per_litre=(round(cost.total_cost_per_litre, 6) if cost.total_cost_per_litre else None),
        priced_fraction=cost.priced_fraction,
        lines=[
            CostLineOut(
                component_name=ln.component_name,
                mass_percent=ln.mass_percent,
                unit_price_amount=(ln.unit_price.amount if ln.unit_price else None),
                unit_price_currency=(ln.unit_price.currency if ln.unit_price else None),
                unit_price_unit=(ln.unit_price.unit if ln.unit_price else None),
                cost_per_kg_recipe=ln.cost_per_kg_recipe,
            )
            for ln in cost.lines
        ],
        missing_prices=list(cost.missing_prices),
    )


# ---------------------------------------------------------------------------
# Experiments
# ---------------------------------------------------------------------------
@router.post(
    "/experiments",
    response_model=ExperimentOut,
    status_code=status.HTTP_201_CREATED,
    tags=["experiments"],
    dependencies=[Depends(require_writer)],
    summary="Plan a new experiment against a recipe version",
    responses={**_UNAUTHORIZED, **_FORBIDDEN, **_VALIDATION},
)
async def plan_experiment(
    payload: ExperimentPlanIn,
    container: Annotated[Container, Depends(get_container)],
) -> ExperimentOut:
    from ...domain.entities.experiment import ExperimentRun

    run = ExperimentRun(
        recipe_id=payload.recipe_id,
        recipe_version=payload.recipe_version,
        title=payload.title,
        hypothesis=payload.hypothesis,
        operator=payload.operator,
    )
    await container.experiment_repository.save(run)
    return _experiment_out(run)


@router.get(
    "/experiments/{experiment_id}",
    response_model=ExperimentOut,
    tags=["experiments"],
    dependencies=[Depends(require_reader)],
    responses={**_UNAUTHORIZED, **_NOT_FOUND},
)
async def get_experiment(
    experiment_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> ExperimentOut:
    run = await container.experiment_repository.get_by_id(experiment_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Experiment not found")
    return _experiment_out(run)


@router.post(
    "/experiments/{experiment_id}/complete",
    response_model=ExperimentOut,
    tags=["experiments"],
    dependencies=[Depends(require_writer)],
    summary="Record batch + measured properties, compute verdict",
    responses={**_UNAUTHORIZED, **_FORBIDDEN, **_NOT_FOUND, **_CONFLICT, **_VALIDATION},
)
async def complete_experiment(
    experiment_id: str,
    payload: ExperimentCompletionIn,
    container: Annotated[Container, Depends(get_container)],
) -> ExperimentOut:
    from ...application.use_cases.get_recipe import GetRecipeByIdQuery
    from ...domain.entities.experiment import BatchInfo, InvalidExperimentError, MeasuredValue

    run = await container.experiment_repository.get_by_id(experiment_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Experiment not found")
    # Backfill target_properties from the recipe if the experiment was
    # planned without them (which we allow for free-form exploratory runs).
    if not run.target_properties:
        recipe = await container.get_recipe.execute(GetRecipeByIdQuery(recipe_id=run.recipe_id))
        if recipe is not None:
            run = run.__class__(  # type: ignore[misc]
                recipe_id=run.recipe_id,
                recipe_version=run.recipe_version,
                id=run.id,
                title=run.title,
                hypothesis=run.hypothesis,
                status=run.status,
                target_properties=recipe.target_properties,
                operator=run.operator,
                created_at=run.created_at,
            )
    try:
        completed = run.complete(
            BatchInfo(
                batch_number=payload.batch.batch_number,
                target_mass_kg=payload.batch.target_mass_kg,
                actual_mass_kg=payload.batch.actual_mass_kg,
                lot_numbers=payload.batch.lot_numbers,
                equipment_used=payload.batch.equipment_used,
            ),
            tuple(
                MeasuredValue(
                    property_code=m.property_code,
                    value=m.value,
                    unit=m.unit,
                    operator=m.operator,
                    notes=m.notes,
                )
                for m in payload.measured_properties
            ),
        )
    except InvalidExperimentError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    await container.experiment_repository.save(completed)
    return _experiment_out(completed)


@router.post(
    "/experiments/{experiment_id}/apply",
    response_model=ApplyLabResultsOut,
    tags=["experiments"],
    dependencies=[Depends(require_writer)],
    summary="Apply lab results to the recipe (annotate / branch / promote)",
    responses={**_UNAUTHORIZED, **_FORBIDDEN, **_NOT_FOUND, **_CONFLICT},
)
async def apply_lab_results(
    experiment_id: str,
    payload: ApplyLabResultsIn,
    container: Annotated[Container, Depends(get_container)],
    principal: Annotated[Principal, Depends(require_writer)],
) -> ApplyLabResultsOut:
    from ...application.use_cases.apply_lab_results import (
        ApplyLabResultsCommand,
        ApplyLabResultsError,
        ApplyMode,
    )

    try:
        mode = ApplyMode(payload.mode)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    try:
        result = await container.apply_lab_results.execute(
            ApplyLabResultsCommand(
                experiment_id=experiment_id,
                actor=payload.actor or principal.subject,
                mode=mode,
                change_note=payload.change_note,
            )
        )
    except ApplyLabResultsError as exc:
        # Distinguish 404 vs 409.
        detail = str(exc)
        if "not found" in detail.lower():
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail) from exc
        raise HTTPException(status.HTTP_409_CONFLICT, detail) from exc

    return ApplyLabResultsOut(
        original_recipe_id=result.original_recipe_id,
        resulting_recipe_id=result.resulting_recipe_id,
        verdict=result.verdict.value,
        mode=result.mode.value,
        deviations=[
            DeviationOut(
                property_code=d.property_code,
                target_value=d.target_value,
                measured_value=d.measured_value,
                unit=d.unit,
            )
            for d in result.deviations
        ],
    )


def _experiment_out(run) -> ExperimentOut:  # type: ignore[no-untyped-def]
    return ExperimentOut(
        id=run.id,
        recipe_id=run.recipe_id,
        recipe_version=run.recipe_version,
        title=run.title,
        status=run.status.value,
        verdict=run.verdict.value if run.verdict is not None else None,
        operator=run.operator,
        measured_properties=[
            ProcessMeasuredIn(
                property_code=mv.property_code,
                value=mv.value,
                unit=mv.unit,
                operator=mv.operator,
                notes=mv.notes,
            )
            for mv in run.measured_properties
        ],
    )


__all__ = ["router"]
