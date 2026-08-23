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
    BatchAnalysisOut,
    BatchAnalysisRequest,
    BatchCostLineOut,
    BatchCostOut,
    CalibrationBatchOut,
    CalibrationBatchRequest,
    CalibrationMatrixOut,
    CalibrationMatrixRowOut,
    CalibrationOut,
    CalibrationRequest,
    CatalogStats,
    CitationOut,
    ComponentOut,
    CompositionStageOut,
    CostLineOut,
    CostRequest,
    CreateRecipeRequest,
    DeviationOut,
    DriftAlertOut,
    DriftAlertRequest,
    DriftCheckOut,
    DriftCheckRequest,
    DriftFullOut,
    DriftFullRequest,
    DriftReportOut,
    ErrorResponse,
    ExperimentCompletionIn,
    ExperimentOut,
    ExperimentPlanIn,
    FeatureImpactOutBase,
    HealthResponse,
    JobRecordOut,
    JobsListOut,
    MassBalanceOut,
    ModelMetadataOut,
    OptimisationRequestIn,
    OptimisationResultOut,
    ParetoPointOut,
    ParetoRequestIn,
    ParetoResultOut,
    PredictionsOut,
    ProcessMeasuredIn,
    ProcessParamsOut,
    PropertyPredictionOut,
    RecipeAssessmentOut,
    RecipeCostOut,
    RecipeFullOut,
    RecipeSummary,
    RegulatoryFindingOut,
    RejectRequest,
    RuleFindingOut,
    SearchResponse,
    SimilarRecipeOut,
    SimilarRecipesOut,
    StoichiometryFindingOut,
    StoichiometryOut,
    SubmitReviewRequest,
    TrainingResultOut,
    TrainModelsRequest,
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


def _citation_to_out(citation: Any) -> CitationOut:
    return CitationOut(
        authors=citation.authors,
        title=citation.title,
        year=citation.year,
        publisher=citation.publisher,
        isbn=(str(citation.isbn) if citation.isbn else None),
        doi=(str(citation.doi) if citation.doi else None),
        url=getattr(citation, "url", "") or "",
        page_or_formula=getattr(citation, "page_or_formula", "") or "",
    )


@router.get(
    "/recipes/{recipe_id}/full",
    response_model=RecipeFullOut,
    tags=["recipes"],
    dependencies=[Depends(require_reader)],
    summary="Full recipe payload including composition tree — used by the UI",
    responses={**_UNAUTHORIZED, **_NOT_FOUND},
)
async def get_recipe_full(
    recipe_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> RecipeFullOut:
    recipe = await container.get_recipe.execute(GetRecipeByIdQuery(recipe_id=recipe_id))
    if recipe is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recipe not found")

    stages_out = [
        CompositionStageOut(
            stage_number=stage.stage_number,
            name=stage.name,
            description=stage.description,
            components=[
                ComponentOut(
                    name=c.name,
                    cas_number=c.cas_number,
                    function=c.function,
                    mass_percent=c.mass_percent,
                    tolerance_percent=c.tolerance_percent,
                    inci_name=c.inci_name,
                    manufacturer_reference=c.manufacturer_reference,
                    notes=c.notes,
                )
                for c in stage.components
            ],
            process=(
                ProcessParamsOut(
                    equipment=stage.process.equipment,
                    rotational_speed_rpm=stage.process.rotational_speed_rpm,
                    peripheral_speed_m_per_s=stage.process.peripheral_speed_m_per_s,
                    temperature_c=stage.process.temperature_c,
                    duration_min=stage.process.duration_min,
                )
                if stage.process is not None
                else None
            ),
        )
        for stage in recipe.stages
    ]

    return RecipeFullOut(
        id=recipe.id,
        category=recipe.category,
        subcategory=recipe.subcategory,
        binder_type=recipe.binder_type,
        product_class=recipe.product_class.value,
        intended_use=recipe.intended_use,
        finish=recipe.finish,
        color=recipe.color,
        status=recipe.status.state.value,
        verification_count=recipe.status.verification_count,
        verification_required=recipe.status.required_verifications,
        version=recipe.version,
        tags=list(recipe.tags),
        stages=stages_out,
        primary_source=_citation_to_out(recipe.primary_source),
        cross_references=[_citation_to_out(c) for c in recipe.cross_references],
    )


@router.get(
    "/recipes/{recipe_id}/similar",
    response_model=SimilarRecipesOut,
    tags=["recipes"],
    dependencies=[Depends(require_reader)],
    summary="List recipes with the most similar composition-feature vector",
    responses={**_UNAUTHORIZED, **_NOT_FOUND},
)
async def get_similar_recipes(
    recipe_id: str,
    container: Annotated[Container, Depends(get_container)],
    top_k: int = Query(default=5, ge=1, le=50),
    same_category_only: bool = Query(default=True),
    min_similarity: float = Query(default=0.0, ge=-1.0, le=1.0),
) -> SimilarRecipesOut:
    from ...application.use_cases.similar_recipes import FindSimilarQuery

    matches = await container.find_similar_recipes.execute(
        FindSimilarQuery(
            recipe_id=recipe_id,
            top_k=top_k,
            same_category_only=same_category_only,
            min_similarity=min_similarity,
        )
    )
    if matches is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recipe not found")
    return SimilarRecipesOut(
        reference_recipe_id=recipe_id,
        same_category_only=same_category_only,
        matches=[
            SimilarRecipeOut(
                recipe_id=m.recipe_id,
                category=m.category,
                subcategory=m.subcategory,
                binder_type=m.binder_type,
                product_class=m.product_class,
                similarity=round(m.similarity, 6),
            )
            for m in matches
        ],
    )


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
        stoichiometry=(
            StoichiometryOut(
                detected_system=assessment.stoichiometry.detected_system,
                reactive_equivalents_per_100g=assessment.stoichiometry.reactive_equivalents,
                co_reactive_equivalents_per_100g=assessment.stoichiometry.co_reactive_equivalents,
                ratio_reactive_to_co=assessment.stoichiometry.ratio_reactive_to_co,
                recommended_ratio_low=assessment.stoichiometry.recommended_ratio_low,
                recommended_ratio_high=assessment.stoichiometry.recommended_ratio_high,
                is_balanced=assessment.stoichiometry.is_balanced,
                findings=[
                    StoichiometryFindingOut(
                        rule_id=f.rule_id,
                        severity=f.severity.value,
                        message=f.message,
                        reference=f.reference,
                    )
                    for f in assessment.stoichiometry.findings
                ],
            )
            if assessment.stoichiometry is not None
            else None
        ),
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


# ---------------------------------------------------------------------------
# ML — training + prediction + registry
# ---------------------------------------------------------------------------
@router.post(
    "/ml/train",
    response_model=TrainingResultOut,
    tags=["ml"],
    dependencies=[Depends(require_writer)],
    summary="Train / retrain per-property regressors from experiment data",
    responses={**_UNAUTHORIZED, **_FORBIDDEN},
)
async def train_models(
    payload: TrainModelsRequest,
    container: Annotated[Container, Depends(get_container)],
) -> TrainingResultOut:
    from ...application.use_cases.ml_train import TrainPropertyModelsCommand

    try:
        result = await container.train_property_models.execute(
            TrainPropertyModelsCommand(
                recipe_ids=tuple(payload.recipe_ids),
                property_codes=tuple(payload.property_codes),
            )
        )
    except Exception as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return TrainingResultOut(
        trained=[_model_metadata_out(m) for m in result.trained],
        skipped=result.skipped,
    )


def _model_metadata_out(m: Any) -> ModelMetadataOut:
    """Serialise a :class:`ModelMetadata` into the API DTO."""
    return ModelMetadataOut(
        property_code=m.property_code,
        version=m.version,
        n_samples=m.n_samples,
        n_features=m.n_features,
        feature_names=list(m.feature_names),
        cv_mean_r2=round(m.cv_mean_r2, 4),
        cv_std_r2=round(m.cv_std_r2, 4),
        training_recipe_ids=list(m.training_recipe_ids),
        algorithm=m.algorithm,
        fingerprint=m.fingerprint,
        holdout_r2=(round(m.holdout_r2, 4) if m.holdout_r2 is not None else None),
        holdout_mae=(round(m.holdout_mae, 4) if m.holdout_mae is not None else None),
        holdout_size=m.holdout_size,
    )


@router.get(
    "/ml/models",
    response_model=list[ModelMetadataOut],
    tags=["ml"],
    dependencies=[Depends(require_reader)],
    summary="List regression models currently registered",
    responses={**_UNAUTHORIZED},
)
async def list_models(
    container: Annotated[Container, Depends(get_container)],
) -> list[ModelMetadataOut]:
    return [_model_metadata_out(m) for m in container.property_regressor.list_models()]


@router.get(
    "/recipes/{recipe_id}/predict",
    response_model=PredictionsOut,
    tags=["ml", "recipes"],
    dependencies=[Depends(require_reader)],
    summary="Predict property values for a recipe using trained models",
    responses={**_UNAUTHORIZED, **_NOT_FOUND},
)
async def predict_recipe(
    recipe_id: str,
    container: Annotated[Container, Depends(get_container)],
    property_code: list[str] = Query(default_factory=list),
    explain_top_k: int = Query(
        0,
        ge=0,
        le=10,
        description=(
            "If > 0, attach SHAP-style attributions for the top-k features driving each prediction."
        ),
    ),
) -> PredictionsOut:
    from ...application.use_cases.ml_predict import PredictPropertyQuery

    result = await container.predict_properties.execute(
        PredictPropertyQuery(
            recipe_id=recipe_id,
            property_codes=tuple(property_code),
            explain_top_k=(explain_top_k or None),
        )
    )
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recipe not found")
    return PredictionsOut(
        recipe_id=recipe_id,
        predictions=[
            PropertyPredictionOut(
                property_code=p.property_code,
                predicted_value=p.predicted_value,
                model_version=p.model_version,
                model_cv_r2=p.model_cv_r2,
                unit=p.unit,
                lower_bound=p.lower_bound,
                upper_bound=p.upper_bound,
                interval_alpha=p.interval_alpha,
                top_features=[
                    FeatureImpactOutBase(
                        feature_name=fi.feature_name,
                        contribution=round(fi.contribution, 6),
                        baseline_value=round(fi.baseline_value, 6),
                        global_importance=round(fi.global_importance, 6),
                    )
                    for fi in p.top_features
                ],
            )
            for p in result
        ],
    )


# ---------------------------------------------------------------------------
# Batch analysis
# ---------------------------------------------------------------------------
@router.post(
    "/experiments/{experiment_id}/batch-report",
    response_model=BatchAnalysisOut,
    tags=["experiments", "cost"],
    dependencies=[Depends(require_reader)],
    summary="Batch-level cost + mass balance + regulatory report",
    responses={**_UNAUTHORIZED, **_NOT_FOUND, **_VALIDATION},
)
async def batch_report(
    experiment_id: str,
    payload: BatchAnalysisRequest,
    container: Annotated[Container, Depends(get_container)],
) -> BatchAnalysisOut:
    from ...application.use_cases.get_recipe import GetRecipeByIdQuery
    from ...domain.services.batch_analysis import analyse_batch
    from ...domain.value_objects.cost import InvalidPriceError, Price

    run = await container.experiment_repository.get_by_id(experiment_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Experiment not found")
    if run.batch is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Experiment has no batch data — complete it first.",
        )
    recipe = await container.get_recipe.execute(GetRecipeByIdQuery(recipe_id=run.recipe_id))
    if recipe is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recipe not found")

    prices: dict[str, Price] = {}
    for item in payload.prices:
        try:
            prices[item.component_name] = Price(
                amount=item.amount, currency=item.currency, unit=item.unit
            )
        except InvalidPriceError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    report = analyse_batch(recipe, run.batch, prices)
    return BatchAnalysisOut(
        experiment_id=experiment_id,
        recipe_id=recipe.id,
        cost=BatchCostOut(
            batch_number=report.cost.batch_number,
            currency=report.cost.currency,
            total_cost=round(report.cost.total_cost, 6),
            priced_fraction=report.cost.priced_fraction,
            lines=[
                BatchCostLineOut(
                    component_name=ln.component_name,
                    mass_kg=round(ln.mass_kg, 6),
                    lot_number=ln.lot_number,
                    cost=(round(ln.cost, 6) if ln.cost is not None else None),
                )
                for ln in report.cost.lines
            ],
            missing_prices=list(report.cost.missing_prices),
        ),
        mass_balance=MassBalanceOut(
            batch_number=report.mass_balance.batch_number,
            target_mass_kg=report.mass_balance.target_mass_kg,
            actual_mass_kg=report.mass_balance.actual_mass_kg,
            yield_percent=(
                round(report.mass_balance.yield_percent, 3)
                if report.mass_balance.yield_percent is not None
                else None
            ),
            is_within_tolerance=report.mass_balance.is_within_tolerance,
        ),
        regulatory_findings=[
            RegulatoryFindingOut(
                rule_id=r.rule_id,
                severity=r.severity.value,
                substance=r.substance,
                cas_number=r.cas_number,
                message=r.message,
                reference=r.reference,
            )
            for r in report.regulatory.findings
        ],
    )


# ---------------------------------------------------------------------------
# ML — optimisation & drift
# ---------------------------------------------------------------------------
@router.post(
    "/recipes/{recipe_id}/optimise",
    response_model=OptimisationResultOut,
    tags=["ml", "recipes"],
    dependencies=[Depends(require_writer)],
    summary="Inverse-search: adjust the recipe to hit property targets",
    responses={**_UNAUTHORIZED, **_FORBIDDEN, **_NOT_FOUND, **_VALIDATION},
)
async def optimise_recipe(
    recipe_id: str,
    payload: OptimisationRequestIn,
    container: Annotated[Container, Depends(get_container)],
) -> OptimisationResultOut:
    from ...application.use_cases.optimise_recipe import (
        OptimiseRecipeCommand,
        RecipeNotFoundError,
    )
    from ...infrastructure.ml.optimiser import ComponentBounds, PropertyTarget

    try:
        result = await container.optimise_recipe.execute(
            OptimiseRecipeCommand(
                recipe_id=recipe_id,
                targets=tuple(
                    PropertyTarget(
                        property_code=t.property_code,
                        target_value=t.target_value,
                        tolerance=t.tolerance,
                        direction=t.direction,
                        weight=t.weight,
                    )
                    for t in payload.targets
                ),
                bounds=tuple(
                    ComponentBounds(
                        component_name=b.component_name,
                        min_percent=b.min_percent,
                        max_percent=b.max_percent,
                    )
                    for b in payload.bounds
                ),
                max_iterations=payload.max_iterations,
                population_size=payload.population_size,
                seed=payload.seed,
            )
        )
    except RecipeNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except RuntimeError as exc:  # scipy missing
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    return OptimisationResultOut(
        base_recipe_id=result.base_recipe_id,
        optimised_mass_percent={k: round(v, 4) for k, v in result.optimised_mass_percent.items()},
        predicted_values={k: round(v, 4) for k, v in result.predicted_values.items()},
        final_loss=round(result.final_loss, 6),
        converged=result.converged,
        iterations_used=result.iterations_used,
        notes=list(result.notes),
    )


@router.post(
    "/ml/models/{property_code}/drift",
    response_model=DriftCheckOut,
    tags=["ml"],
    dependencies=[Depends(require_reader)],
    summary="PSI + KS drift check against the model's training distribution",
    responses={**_UNAUTHORIZED, **_NOT_FOUND},
)
async def drift_check(
    property_code: str,
    payload: DriftCheckRequest,
    container: Annotated[Container, Depends(get_container)],
) -> DriftCheckOut:
    from ...infrastructure.ml.drift import compare_distributions
    from ...infrastructure.ml.features import FEATURE_NAMES

    training_vectors = container.property_regressor.get_training_vectors(payload.property_code)
    if training_vectors is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"No training snapshot for property_code={payload.property_code!r}",
        )

    # We currently receive a flat list of *target* values; the drift
    # test is per-feature.  For a target-value distribution we compare
    # against the historical measured targets by convention (index 0
    # of the last column is not stored; so we just compare the caller
    # sample to the *first* feature — mass_percent_vehicle — as a smoke
    # test).  Real callers can extend this to full-vector comparison.
    reference_first_feature = [row[0] for row in training_vectors if row]
    report = compare_distributions(
        reference_first_feature,
        payload.current_values,
        feature_name=FEATURE_NAMES[0],
    )
    return DriftCheckOut(
        property_code=payload.property_code,
        reports=[
            DriftReportOut(
                feature_name=report.feature_name,
                psi=round(report.psi, 6),
                ks_statistic=round(report.ks_statistic, 6),
                ks_p_value=(round(report.ks_p_value, 6) if report.ks_p_value is not None else None),
                level=report.level.value,
                n_reference=report.n_reference,
                n_current=report.n_current,
            )
        ],
    )


# ---------------------------------------------------------------------------
# ML — drift-full, calibrate, pareto
# ---------------------------------------------------------------------------
@router.post(
    "/ml/models/{property_code}/drift-full",
    response_model=DriftFullOut,
    tags=["ml"],
    dependencies=[Depends(require_reader)],
    summary="Per-feature drift across all model inputs",
    responses={**_UNAUTHORIZED, **_NOT_FOUND, **_VALIDATION},
)
async def drift_full(
    property_code: str,
    payload: DriftFullRequest,
    container: Annotated[Container, Depends(get_container)],
) -> DriftFullOut:
    from ...infrastructure.ml.drift import (
        DriftLevel,
        compare_feature_matrices,
    )
    from ...infrastructure.ml.features import FEATURE_NAMES

    reference = container.property_regressor.get_training_vectors(property_code)
    if reference is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"No training snapshot for property_code={property_code!r}",
        )
    if any(len(row) != len(FEATURE_NAMES) for row in payload.current_vectors):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"every current_vectors row must have {len(FEATURE_NAMES)} entries",
        )

    reports = compare_feature_matrices(
        reference, payload.current_vectors, feature_names=list(FEATURE_NAMES)
    )
    # Aggregate worst level for a quick banner in the UI.
    order = {DriftLevel.NO_DRIFT: 0, DriftLevel.MODERATE_DRIFT: 1, DriftLevel.SEVERE_DRIFT: 2}
    worst = DriftLevel.NO_DRIFT
    for report in reports:
        if order[report.level] > order[worst]:
            worst = report.level

    return DriftFullOut(
        property_code=property_code,
        reports=[
            DriftReportOut(
                feature_name=r.feature_name,
                psi=round(r.psi, 6),
                ks_statistic=round(r.ks_statistic, 6),
                ks_p_value=(round(r.ks_p_value, 6) if r.ks_p_value is not None else None),
                level=r.level.value,
                n_reference=r.n_reference,
                n_current=r.n_current,
            )
            for r in reports
        ],
        worst_level=worst.value,
    )


@router.get(
    "/ml/models/{property_code}/drift-from-catalog",
    response_model=DriftFullOut,
    tags=["ml"],
    dependencies=[Depends(require_reader)],
    summary=(
        "Per-feature drift comparing the model's training snapshot against "
        "the composition-feature vectors of the current recipes in the catalog"
    ),
    responses={**_UNAUTHORIZED, **_NOT_FOUND},
)
async def drift_from_catalog(
    property_code: str,
    container: Annotated[Container, Depends(get_container)],
    limit: int = Query(
        default=100,
        ge=5,
        le=1000,
        description="How many catalog recipes to sample for the current distribution.",
    ),
    category: str | None = Query(
        default=None,
        description="Restrict the sample to recipes in this category (optional).",
    ),
) -> DriftFullOut:
    """Convenience endpoint: no client-side feature engineering needed.

    Callers just pick a property_code, we do everything else — pull the
    reference snapshot the model was fitted on, pull the current
    catalog rows, extract the same 37-column feature vector we use
    everywhere, and hand back a per-feature PSI + KS report.
    """
    from ...infrastructure.ml.drift import (
        DriftLevel,
        compare_feature_matrices,
    )
    from ...infrastructure.ml.features import FEATURE_NAMES, to_vector

    reference = container.property_regressor.get_training_vectors(property_code)
    if reference is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"No training snapshot for property_code={property_code!r}",
        )

    catalog = await container.recipe_repository.find_by_criteria(
        category=category,
        limit=limit,
        offset=0,
    )
    if not catalog:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "No recipes in the catalog to compare against.",
        )
    current_vectors = [to_vector(r) for r in catalog]

    reports = compare_feature_matrices(
        reference, current_vectors, feature_names=list(FEATURE_NAMES)
    )
    order = {
        DriftLevel.NO_DRIFT: 0,
        DriftLevel.MODERATE_DRIFT: 1,
        DriftLevel.SEVERE_DRIFT: 2,
    }
    worst = DriftLevel.NO_DRIFT
    for report in reports:
        if order[report.level] > order[worst]:
            worst = report.level

    return DriftFullOut(
        property_code=property_code,
        reports=[
            DriftReportOut(
                feature_name=r.feature_name,
                psi=round(r.psi, 6),
                ks_statistic=round(r.ks_statistic, 6),
                ks_p_value=(round(r.ks_p_value, 6) if r.ks_p_value is not None else None),
                level=r.level.value,
                n_reference=r.n_reference,
                n_current=r.n_current,
            )
            for r in reports
        ],
        worst_level=worst.value,
    )


@router.post(
    "/ml/models/{property_code}/calibrate",
    response_model=CalibrationOut,
    tags=["ml"],
    dependencies=[Depends(require_writer)],
    summary="Fit isotonic + interval calibration for a trained model",
    responses={**_UNAUTHORIZED, **_FORBIDDEN, **_NOT_FOUND, **_VALIDATION},
)
async def calibrate_model(
    property_code: str,
    payload: CalibrationRequest,
    container: Annotated[Container, Depends(get_container)],
) -> CalibrationOut:
    from ...infrastructure.ml.calibration import CalibrationError

    raw = [s.raw_prediction for s in payload.samples]
    actual = [s.actual for s in payload.samples]
    lowers = [s.lower for s in payload.samples if s.lower is not None]
    uppers = [s.upper for s in payload.samples if s.upper is not None]
    include_interval = len(lowers) == len(payload.samples) and len(uppers) == len(payload.samples)

    try:
        bundle = container.property_regressor.calibrate(
            property_code,
            raw_predictions=raw,
            actual_values=actual,
            lowers=(lowers if include_interval else None),
            uppers=(uppers if include_interval else None),
            target_coverage=payload.target_coverage,
        )
    except CalibrationError as exc:
        # 404 when there's no matching model, 422 otherwise.
        if "No model" in str(exc):
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    return CalibrationOut(
        property_code=bundle.property_code,
        version=bundle.version,
        n_samples=bundle.calibration_n,
        has_isotonic=bundle.isotonic is not None,
        has_interval=bundle.interval is not None,
        empirical_coverage=(
            round(bundle.interval.empirical_coverage, 4) if bundle.interval is not None else None
        ),
        target_coverage=(bundle.interval.target_coverage if bundle.interval is not None else None),
        factor=(round(bundle.interval.factor, 4) if bundle.interval is not None else None),
        notes=list(bundle.notes),
    )


@router.post(
    "/recipes/{recipe_id}/pareto",
    response_model=ParetoResultOut,
    tags=["ml", "recipes"],
    dependencies=[Depends(require_writer)],
    summary="Multi-objective (Pareto) optimisation across property targets",
    responses={**_UNAUTHORIZED, **_FORBIDDEN, **_NOT_FOUND},
)
async def pareto_optimise(
    recipe_id: str,
    payload: ParetoRequestIn,
    container: Annotated[Container, Depends(get_container)],
) -> ParetoResultOut:
    from ...application.use_cases.get_recipe import GetRecipeByIdQuery
    from ...infrastructure.ml.optimiser import ComponentBounds, PropertyTarget
    from ...infrastructure.ml.pareto import ParetoOptimiser, ParetoRequest

    recipe = await container.get_recipe.execute(GetRecipeByIdQuery(recipe_id=recipe_id))
    if recipe is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recipe not found")

    def _predict(candidate, code):  # type: ignore[no-untyped-def]
        prediction = container.property_regressor.predict(candidate, code, alpha=None)
        return prediction.predicted_value if prediction else None

    optimiser = ParetoOptimiser(predictor=_predict)
    result = optimiser.optimise(
        recipe,
        ParetoRequest(
            targets=tuple(
                PropertyTarget(
                    property_code=t.property_code,
                    target_value=t.target_value,
                    tolerance=t.tolerance,
                    direction=t.direction,
                    weight=t.weight,
                )
                for t in payload.targets
            ),
            bounds=tuple(
                ComponentBounds(
                    component_name=b.component_name,
                    min_percent=b.min_percent,
                    max_percent=b.max_percent,
                )
                for b in payload.bounds
            ),
            population_size=payload.population_size,
            generations=payload.generations,
            mutation_std=payload.mutation_std,
            seed=payload.seed,
        ),
    )
    return ParetoResultOut(
        base_recipe_id=result.base_recipe_id,
        front=[
            ParetoPointOut(
                mass_percent={k: round(v, 4) for k, v in p.mass_percent.items()},
                objectives={k: round(v, 4) for k, v in p.objectives.items()},
                rank=p.rank,
                crowding_distance=round(p.crowding_distance, 6),
            )
            for p in result.front
        ],
        generations=result.generations,
    )


# ---------------------------------------------------------------------------
# ML — batch calibration + coverage matrix
# ---------------------------------------------------------------------------
@router.post(
    "/ml/calibrate",
    response_model=CalibrationBatchOut,
    tags=["ml"],
    dependencies=[Depends(require_writer)],
    summary="Calibrate isotonic + interval bounds for many models in one call",
    responses={**_UNAUTHORIZED, **_FORBIDDEN, **_VALIDATION},
)
async def calibrate_models_batch(
    payload: CalibrationBatchRequest,
    container: Annotated[Container, Depends(get_container)],
) -> CalibrationBatchOut:
    from ...infrastructure.ml.calibration import CalibrationError

    calibrated: list[CalibrationOut] = []
    skipped: dict[str, str] = {}

    for entry in payload.entries:
        code = entry.property_code
        raw = [s.raw_prediction for s in entry.samples]
        actual = [s.actual for s in entry.samples]
        lowers = [s.lower for s in entry.samples if s.lower is not None]
        uppers = [s.upper for s in entry.samples if s.upper is not None]
        include_interval = len(lowers) == len(entry.samples) and len(uppers) == len(entry.samples)
        try:
            bundle = container.property_regressor.calibrate(
                code,
                raw_predictions=raw,
                actual_values=actual,
                lowers=(lowers if include_interval else None),
                uppers=(uppers if include_interval else None),
                target_coverage=payload.target_coverage,
            )
        except CalibrationError as exc:
            skipped[code] = str(exc)
            continue

        calibrated.append(
            CalibrationOut(
                property_code=bundle.property_code,
                version=bundle.version,
                n_samples=bundle.calibration_n,
                has_isotonic=bundle.isotonic is not None,
                has_interval=bundle.interval is not None,
                empirical_coverage=(
                    round(bundle.interval.empirical_coverage, 4)
                    if bundle.interval is not None
                    else None
                ),
                target_coverage=(
                    bundle.interval.target_coverage if bundle.interval is not None else None
                ),
                factor=(round(bundle.interval.factor, 4) if bundle.interval is not None else None),
                notes=list(bundle.notes),
            )
        )

    return CalibrationBatchOut(calibrated=calibrated, skipped=skipped)


@router.get(
    "/ml/calibration-matrix",
    response_model=CalibrationMatrixOut,
    tags=["ml"],
    dependencies=[Depends(require_reader)],
    summary="Coverage matrix across every registered model (model + calibration side-by-side)",
    responses={**_UNAUTHORIZED},
)
async def calibration_matrix(
    container: Annotated[Container, Depends(get_container)],
) -> CalibrationMatrixOut:
    rows: list[CalibrationMatrixRowOut] = []
    n_calibrated = 0
    n_under_covered = 0

    for metadata in container.property_regressor.list_models():
        bundle = container.property_regressor.get_calibration(metadata.property_code)
        has_calibration = bundle is not None
        has_iso = bool(bundle and bundle.isotonic)
        has_interval = bool(bundle and bundle.interval)
        target_cov: float | None = None
        empirical_cov: float | None = None
        factor: float | None = None
        cal_n: int | None = None
        gap: float | None = None
        if bundle is not None:
            n_calibrated += 1
            cal_n = bundle.calibration_n
            if bundle.interval is not None:
                target_cov = bundle.interval.target_coverage
                empirical_cov = round(bundle.interval.empirical_coverage, 4)
                factor = round(bundle.interval.factor, 4)
                gap = round(empirical_cov - target_cov, 4)
                # More than 5 percentage points below target = under-covering.
                if gap <= -0.05:
                    n_under_covered += 1

        rows.append(
            CalibrationMatrixRowOut(
                property_code=metadata.property_code,
                model_version=metadata.version,
                cv_mean_r2=round(metadata.cv_mean_r2, 4),
                n_samples=metadata.n_samples,
                has_calibration=has_calibration,
                has_isotonic=has_iso,
                has_interval=has_interval,
                target_coverage=target_cov,
                empirical_coverage=empirical_cov,
                coverage_gap=gap,
                factor=factor,
                calibration_n=cal_n,
            )
        )

    return CalibrationMatrixOut(
        rows=rows,
        n_models=len(rows),
        n_calibrated=n_calibrated,
        n_under_covered=n_under_covered,
    )


# ---------------------------------------------------------------------------
# ML — drift + alert dispatch
# ---------------------------------------------------------------------------
@router.post(
    "/ml/models/{property_code}/drift-full/alert",
    response_model=DriftAlertOut,
    tags=["ml"],
    dependencies=[Depends(require_writer)],
    summary="Run per-feature drift and dispatch an alert when severe drift is detected",
    responses={**_UNAUTHORIZED, **_FORBIDDEN, **_NOT_FOUND, **_VALIDATION},
)
async def drift_full_alert(
    property_code: str,
    payload: DriftAlertRequest,
    container: Annotated[Container, Depends(get_container)],
) -> DriftAlertOut:
    from ...infrastructure.ml.drift import (
        DriftLevel,
        compare_feature_matrices,
    )
    from ...infrastructure.ml.features import FEATURE_NAMES
    from ...infrastructure.notifications import Alert

    reference = container.property_regressor.get_training_vectors(property_code)
    if reference is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"No training snapshot for property_code={property_code!r}",
        )
    if any(len(row) != len(FEATURE_NAMES) for row in payload.current_vectors):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"every current_vectors row must have {len(FEATURE_NAMES)} entries",
        )

    reports = compare_feature_matrices(
        reference, payload.current_vectors, feature_names=list(FEATURE_NAMES)
    )
    order = {DriftLevel.NO_DRIFT: 0, DriftLevel.MODERATE_DRIFT: 1, DriftLevel.SEVERE_DRIFT: 2}
    worst = DriftLevel.NO_DRIFT
    for report in reports:
        if order[report.level] > order[worst]:
            worst = report.level

    accepted_levels = {"no_drift", "moderate_drift", "severe_drift"}
    if payload.dispatch_min_level not in accepted_levels:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"dispatch_min_level must be one of {sorted(accepted_levels)}",
        )
    threshold = order[DriftLevel(payload.dispatch_min_level)]

    dispatched = False
    reason = "below-threshold"
    if order[worst] >= threshold:
        top = sorted(
            reports,
            key=lambda r: (order[r.level], r.psi, r.ks_statistic),
            reverse=True,
        )[:5]
        alert = Alert(
            kind="ml.drift",
            severity="critical" if worst == DriftLevel.SEVERE_DRIFT else "warning",
            title=f"Feature drift detected for {property_code}",
            summary=(
                f"Worst level: {worst.value}. "
                f"{len(reports)} features compared "
                f"({len(payload.current_vectors)} current vs "
                f"{len(reference)} reference samples)."
            ),
            fields={
                "property_code": property_code,
                "worst_level": worst.value,
                "n_reference": len(reference),
                "n_current": len(payload.current_vectors),
                "top_features": [
                    {
                        "feature": r.feature_name,
                        "level": r.level.value,
                        "psi": round(r.psi, 4),
                        "ks": round(r.ks_statistic, 4),
                    }
                    for r in top
                ],
                **payload.context,
            },
        )
        dispatched = await container.alert_notifier.notify(alert)
        reason = "dispatched" if dispatched else "notifier-rejected"

    return DriftAlertOut(
        property_code=property_code,
        worst_level=worst.value,
        reports=[
            DriftReportOut(
                feature_name=r.feature_name,
                psi=round(r.psi, 6),
                ks_statistic=round(r.ks_statistic, 6),
                ks_p_value=(round(r.ks_p_value, 6) if r.ks_p_value is not None else None),
                level=r.level.value,
                n_reference=r.n_reference,
                n_current=r.n_current,
            )
            for r in reports
        ],
        alert_dispatched=dispatched,
        dispatch_reason=reason,
    )


# ---------------------------------------------------------------------------
# ML — async training + job registry
# ---------------------------------------------------------------------------
def _job_to_out(record: Any) -> JobRecordOut:
    return JobRecordOut(
        id=record.id,
        kind=record.kind,
        status=record.status,
        created_at=record.created_at,
        started_at=record.started_at,
        finished_at=record.finished_at,
        duration_seconds=record.duration_seconds,
        metadata=dict(record.metadata),
        result=record.result,
        error=record.error,
    )


@router.post(
    "/ml/train/async",
    response_model=JobRecordOut,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["ml"],
    dependencies=[Depends(require_writer)],
    summary="Submit a non-blocking training job; poll /ml/jobs/{job_id} for status",
    responses={**_UNAUTHORIZED, **_FORBIDDEN},
)
async def train_models_async(
    payload: TrainModelsRequest,
    container: Annotated[Container, Depends(get_container)],
) -> JobRecordOut:
    from ...application.use_cases.ml_train import TrainPropertyModelsCommand

    async def _run() -> dict[str, Any]:
        result = await container.train_property_models.execute(
            TrainPropertyModelsCommand(
                recipe_ids=tuple(payload.recipe_ids),
                property_codes=tuple(payload.property_codes),
            )
        )
        return {
            "trained": [
                {
                    "property_code": m.property_code,
                    "version": m.version,
                    "n_samples": m.n_samples,
                    "cv_mean_r2": round(m.cv_mean_r2, 4),
                    "cv_std_r2": round(m.cv_std_r2, 4),
                    "fingerprint": m.fingerprint,
                }
                for m in result.trained
            ],
            "skipped": dict(result.skipped),
        }

    record = await container.job_registry.submit(
        kind="ml.train",
        coro_factory=_run,
        metadata={
            "recipe_ids": list(payload.recipe_ids),
            "property_codes": list(payload.property_codes),
        },
    )
    return _job_to_out(record)


@router.get(
    "/ml/jobs",
    response_model=JobsListOut,
    tags=["ml"],
    dependencies=[Depends(require_reader)],
    summary="List recent ML jobs (most recent first, up to 100)",
    responses={**_UNAUTHORIZED},
)
async def list_jobs(
    container: Annotated[Container, Depends(get_container)],
    status_filter: str | None = Query(
        default=None,
        alias="status",
        description="Filter by status: queued|running|succeeded|failed|cancelled",
    ),
    kind: str | None = Query(default=None, description="Filter by job kind (e.g. ml.train)."),
    limit: int = Query(default=100, ge=1, le=500),
) -> JobsListOut:
    records = container.job_registry.list(
        status=status_filter,  # type: ignore[arg-type]
        kind=kind,
        limit=limit,
    )
    return JobsListOut(jobs=[_job_to_out(r) for r in records])


@router.get(
    "/ml/jobs/{job_id}",
    response_model=JobRecordOut,
    tags=["ml"],
    dependencies=[Depends(require_reader)],
    summary="Fetch a single job by id",
    responses={**_UNAUTHORIZED, **_NOT_FOUND},
)
async def get_job(
    job_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> JobRecordOut:
    record = container.job_registry.get(job_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return _job_to_out(record)


@router.delete(
    "/ml/jobs/{job_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["ml"],
    dependencies=[Depends(require_writer)],
    summary="Cancel a queued or running job (no-op for terminal jobs)",
    responses={**_UNAUTHORIZED, **_FORBIDDEN, **_NOT_FOUND},
)
async def cancel_job(
    job_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> None:
    ok = await container.job_registry.cancel(job_id)
    if not ok:
        # Distinguish "unknown id" (404) from "already-terminal" (409).
        if container.job_registry.get(job_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
        raise HTTPException(status.HTTP_409_CONFLICT, "Job is already in a terminal state")


__all__ = ["router"]
