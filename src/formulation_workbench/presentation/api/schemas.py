"""Pydantic schemas for the REST API.

These mirror the application-layer DTOs but are separated so that the
HTTP contract can evolve without touching internal domain code.

Every schema carries JSON-schema examples so the OpenAPI documentation is
usable as a live reference (Swagger's "Try it out" pre-fills real values).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Ops
# ---------------------------------------------------------------------------
class HealthResponse(BaseModel):
    """Simple readiness probe payload."""

    status: str = Field(default="ok", examples=["ok"])
    version: str = Field(examples=["1.1.3"])
    environment: str = Field(examples=["production"])


class AppInfo(BaseModel):
    """Build + runtime information (Spring-Boot ``/actuator/info``-style)."""

    name: str = Field(examples=["formulation-workbench"])
    version: str = Field(examples=["1.1.3"])
    environment: str = Field(examples=["production"])
    python: str = Field(examples=["3.11.9"])
    platform: str = Field(examples=["Linux-6.1.0-x86_64-with-glibc2.36"])
    git_sha: str = Field(examples=["a1b2c3d4"])
    build_date: str = Field(examples=["2026-08-23"])


# ---------------------------------------------------------------------------
# Recipes — read
# ---------------------------------------------------------------------------
class RecipeSummary(BaseModel):
    """Lightweight recipe representation for list endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(examples=["3f7c1e4a-15e1-4c9d-8f39-8e4b5a0f5b9d"])
    category: str = Field(examples=["Краски"])
    subcategory: str = Field(examples=["Водно-дисперсионные"])
    binder_type: str = Field(examples=["Стирол-акриловая дисперсия"])
    product_class: str = Field(examples=["Premium"])
    intended_use: str = Field(examples=["Interior matte wall paint"])
    status: str = Field(examples=["Verified"])
    verification_count: int = Field(examples=[3])
    verification_required: int = Field(examples=[3])
    version: int = Field(examples=[1])


class SearchResponse(BaseModel):
    items: list[RecipeSummary]
    total_count: int = Field(examples=[42])
    limit: int = Field(examples=[50])
    offset: int = Field(examples=[0])
    has_more: bool = Field(examples=[False])


class CatalogStats(BaseModel):
    total: int = Field(examples=[500])
    by_status: dict[str, int] = Field(
        examples=[{"Draft": 30, "PendingReview": 12, "Verified": 450, "Rejected": 8}]
    )


# ---------------------------------------------------------------------------
# Recipes — write (POST / PATCH)
# ---------------------------------------------------------------------------
_COMPONENT_EXAMPLE: dict[str, Any] = {
    "name": "Titanium dioxide",
    "cas_number": "13463-67-7",
    "function": "pigment",
    "mass_percent": 22.0,
    "tolerance_percent": 0.5,
    "inci_name": "",
    "manufacturer_reference": "",
    "notes": "",
}

_STAGE_EXAMPLE: dict[str, Any] = {
    "stage_number": 1,
    "name": "Mixing",
    "description": "Pre-disperse pigment in water",
    "components": [_COMPONENT_EXAMPLE],
    "process": {
        "equipment": "Disperser",
        "rotational_speed_rpm": 1500,
        "temperature_c": 23.0,
        "duration_min": 30,
    },
}

_CITATION_EXAMPLE: dict[str, Any] = {
    "authors": "Flick, E. W.",
    "title": "Water-Based Paint Formulations, Vol. 3",
    "year": 1995,
    "publisher": "Noyes Publications",
    "isbn": "9780815513773",
    "doi": None,
    "url": None,
    "page_or_formula": "pp. 78-82",
}


class ProcessParamsIn(BaseModel):
    equipment: str = Field(examples=["Disperser"])
    rotational_speed_rpm: float | None = None
    peripheral_speed_m_per_s: float | None = None
    temperature_c: float | None = None
    duration_min: int | None = None


class ComponentIn(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": _COMPONENT_EXAMPLE})

    name: str = Field(min_length=1, max_length=256)
    cas_number: str = Field(min_length=1, max_length=64, examples=["13463-67-7"])
    function: str = Field(min_length=1, max_length=64)
    mass_percent: float = Field(ge=0.0, le=100.0)
    tolerance_percent: float = Field(default=0.0, ge=0.0, le=100.0)
    inci_name: str = ""
    manufacturer_reference: str = ""
    notes: str = ""


class CompositionStageIn(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": _STAGE_EXAMPLE})

    stage_number: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    components: list[ComponentIn] = Field(min_length=1)
    process: ProcessParamsIn | None = None


class CitationIn(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": _CITATION_EXAMPLE})

    authors: str = Field(min_length=1)
    title: str = Field(min_length=1)
    year: int = Field(ge=1800, le=2100)
    publisher: str = Field(min_length=1)
    isbn: str | None = None
    doi: str | None = None
    url: str | None = None
    page_or_formula: str = ""


class CreateRecipeRequest(BaseModel):
    """Payload for ``POST /recipes``.

    ``id`` is optional — the server generates a UUID if omitted. All other
    fields are validated against domain invariants when the aggregate is
    built (mass percents must sum to 100 ± 0.5, stage numbering must be
    sequential from 1, at least one primary source must be present).
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": None,
                "category": "Краски",
                "subcategory": "Водно-дисперсионные",
                "binder_type": "Стирол-акриловая дисперсия",
                "product_class": "Premium",
                "intended_use": "Interior matte wall paint",
                "finish": "matte",
                "color": "white",
                "tags": ["interior", "washable"],
                "stages": [_STAGE_EXAMPLE],
                "primary_source": _CITATION_EXAMPLE,
                "cross_references": [],
            }
        }
    )

    id: str | None = None
    category: str = Field(min_length=1)
    subcategory: str = Field(min_length=1)
    binder_type: str = Field(min_length=1)
    product_class: str = Field(default="Standard")
    intended_use: str = Field(min_length=1)
    finish: str = ""
    color: str = ""
    tags: list[str] = Field(default_factory=list)
    stages: list[CompositionStageIn] = Field(min_length=1)
    primary_source: CitationIn
    cross_references: list[CitationIn] = Field(default_factory=list)


class UpdateRecipeRequest(CreateRecipeRequest):
    """Payload for ``PUT /recipes/{id}`` — same shape as create."""


class VerifyRequest(BaseModel):
    verifier: str = Field(min_length=1, examples=["alice"])
    source_citation_id: str = Field(default="manual", examples=["cite-7"])
    comment: str = ""


class SubmitReviewRequest(BaseModel):
    actor: str = Field(min_length=1, examples=["alice"])
    comment: str = ""


class RejectRequest(BaseModel):
    actor: str = Field(min_length=1, examples=["auditor-1"])
    reason: str = Field(min_length=1, examples=["Sum of pigment volumes exceeds CPVC."])


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ErrorResponse(BaseModel):
    detail: str
    code: str | None = None


class RuleFindingOut(BaseModel):
    """One finding in a recipe assessment (technological rule)."""

    rule_id: str = Field(examples=["T3"])
    severity: str = Field(examples=["warning"])
    message: str
    reference: str = ""


class VerificationViolationOut(BaseModel):
    rule: str = Field(examples=["R1"])
    message: str


class RegulatoryFindingOut(BaseModel):
    """One regulatory (REACH / Annex XVII) finding."""

    rule_id: str = Field(examples=["REACH-XVII"])
    severity: str = Field(examples=["error"])
    substance: str
    cas_number: str = Field(examples=["7439-92-1"])
    message: str
    reference: str = ""


class StoichiometryFindingOut(BaseModel):
    rule_id: str = Field(examples=["S3"])
    severity: str = Field(examples=["warning"])
    message: str
    reference: str = ""


class StoichiometryOut(BaseModel):
    detected_system: str = Field(examples=["polyurethane"])
    reactive_equivalents_per_100g: float
    co_reactive_equivalents_per_100g: float
    ratio_reactive_to_co: float | None = None
    recommended_ratio_low: float
    recommended_ratio_high: float
    is_balanced: bool
    findings: list[StoichiometryFindingOut] = Field(default_factory=list)


class RecipeAssessmentOut(BaseModel):
    """Full quality report of one recipe."""

    recipe_id: str
    score: float = Field(examples=[87.5], ge=0, le=100)
    maturity: str = Field(examples=["production_ready"])
    findings: list[RuleFindingOut]
    verification_violations: list[VerificationViolationOut] = Field(default_factory=list)
    regulatory_findings: list[RegulatoryFindingOut] = Field(default_factory=list)
    stoichiometry: StoichiometryOut | None = None
    summary: dict[str, int | float | str | bool | None]


# ---------------------------------------------------------------------------
# Cost
# ---------------------------------------------------------------------------
class PriceIn(BaseModel):
    """Price of a raw material (POST body element)."""

    component_name: str = Field(examples=["Water"])
    amount: float = Field(examples=[3.00])
    currency: str = Field(examples=["EUR"], min_length=3, max_length=3)
    unit: str = Field(examples=["kg"], pattern=r"^(kg|g|t|l|ml|m3)$")


class CostRequest(BaseModel):
    """POST body for /recipes/{id}/cost."""

    prices: list[PriceIn]


class CostLineOut(BaseModel):
    component_name: str
    mass_percent: float
    unit_price_amount: float | None = None
    unit_price_currency: str | None = None
    unit_price_unit: str | None = None
    cost_per_kg_recipe: float | None = None


class RecipeCostOut(BaseModel):
    recipe_id: str
    currency: str
    cost_per_kg: float
    cost_per_litre: float | None = None
    priced_fraction: float
    lines: list[CostLineOut]
    missing_prices: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Experiments
# ---------------------------------------------------------------------------
class ProcessMeasuredIn(BaseModel):
    property_code: str = Field(examples=["gloss_60"])
    value: float
    unit: str = ""
    operator: str = ""
    notes: str = ""


class BatchInfoIn(BaseModel):
    batch_number: str = Field(examples=["B-2026-001"])
    target_mass_kg: float = Field(gt=0)
    actual_mass_kg: float | None = None
    lot_numbers: dict[str, str] = Field(default_factory=dict)
    equipment_used: str = ""


class ExperimentPlanIn(BaseModel):
    recipe_id: str
    recipe_version: int = Field(ge=1)
    title: str = ""
    hypothesis: str = ""
    operator: str = ""


class ExperimentCompletionIn(BaseModel):
    batch: BatchInfoIn
    measured_properties: list[ProcessMeasuredIn]


class ExperimentOut(BaseModel):
    id: str
    recipe_id: str
    recipe_version: int
    title: str
    status: str
    verdict: str | None
    operator: str
    measured_properties: list[ProcessMeasuredIn] = Field(default_factory=list)


class ApplyLabResultsIn(BaseModel):
    actor: str = Field(examples=["editor@example.com"])
    mode: str = Field(default="annotate", pattern=r"^(annotate|branch|promote)$")
    change_note: str = ""


class DeviationOut(BaseModel):
    property_code: str
    target_value: float
    measured_value: float
    unit: str = ""


class ApplyLabResultsOut(BaseModel):
    original_recipe_id: str
    resulting_recipe_id: str
    verdict: str
    mode: str
    deviations: list[DeviationOut] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# ML
# ---------------------------------------------------------------------------
class TrainModelsRequest(BaseModel):
    recipe_ids: list[str] = Field(
        default_factory=list,
        description="Recipe IDs whose experiments feed the training set. "
        "Empty = no cross-recipe training (repository does not expose 'list all').",
    )
    property_codes: list[str] = Field(
        default_factory=list,
        description="Restrict training to a subset of property codes. Empty = all.",
    )


class ModelMetadataOut(BaseModel):
    property_code: str
    version: str = Field(examples=["20260823T103011Z"])
    n_samples: int
    n_features: int
    feature_names: list[str]
    cv_mean_r2: float = Field(examples=[0.87])
    cv_std_r2: float = Field(examples=[0.04])
    training_recipe_ids: list[str] = Field(default_factory=list)
    algorithm: str
    fingerprint: str


class TrainingResultOut(BaseModel):
    trained: list[ModelMetadataOut]
    skipped: dict[str, str] = Field(default_factory=dict)


class FeatureImpactOutBase(BaseModel):
    feature_name: str
    contribution: float
    baseline_value: float
    global_importance: float


class PropertyPredictionOut(BaseModel):
    property_code: str
    predicted_value: float
    model_version: str
    model_cv_r2: float
    unit: str = ""
    lower_bound: float | None = None
    upper_bound: float | None = None
    interval_alpha: float | None = None
    top_features: list[FeatureImpactOutBase] = Field(default_factory=list)


class PredictionsOut(BaseModel):
    recipe_id: str
    predictions: list[PropertyPredictionOut]


# ---------------------------------------------------------------------------
# Batch analysis
# ---------------------------------------------------------------------------
class BatchCostLineOut(BaseModel):
    component_name: str
    mass_kg: float
    lot_number: str = ""
    cost: float | None = None


class BatchCostOut(BaseModel):
    batch_number: str
    currency: str
    total_cost: float
    priced_fraction: float
    lines: list[BatchCostLineOut]
    missing_prices: list[str] = Field(default_factory=list)


class MassBalanceOut(BaseModel):
    batch_number: str
    target_mass_kg: float
    actual_mass_kg: float | None
    yield_percent: float | None
    is_within_tolerance: bool


class BatchAnalysisRequest(BaseModel):
    """POST body for /experiments/{id}/batch-report."""

    prices: list[PriceIn] = Field(default_factory=list)


class BatchAnalysisOut(BaseModel):
    experiment_id: str
    recipe_id: str
    cost: BatchCostOut
    mass_balance: MassBalanceOut
    regulatory_findings: list[RegulatoryFindingOut] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Optimisation
# ---------------------------------------------------------------------------
class PropertyTargetIn(BaseModel):
    property_code: str = Field(examples=["gloss_60"])
    target_value: float
    tolerance: float = 0.0
    direction: str = Field(default="match", pattern=r"^(match|minimise|maximise)$")
    weight: float = 1.0


class ComponentBoundsIn(BaseModel):
    component_name: str
    min_percent: float = Field(ge=0.0, le=100.0)
    max_percent: float = Field(ge=0.0, le=100.0)


class OptimisationRequestIn(BaseModel):
    targets: list[PropertyTargetIn]
    bounds: list[ComponentBoundsIn] = Field(default_factory=list)
    max_iterations: int = Field(default=30, ge=1, le=200)
    population_size: int = Field(default=15, ge=4, le=100)
    seed: int | None = 42


class OptimisationResultOut(BaseModel):
    base_recipe_id: str
    optimised_mass_percent: dict[str, float]
    predicted_values: dict[str, float]
    final_loss: float
    converged: bool
    iterations_used: int
    notes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Drift
# ---------------------------------------------------------------------------
class DriftReportOut(BaseModel):
    feature_name: str
    psi: float
    ks_statistic: float
    ks_p_value: float | None
    level: str
    n_reference: int
    n_current: int


class DriftCheckRequest(BaseModel):
    """POST body: distribution of a numeric quantity to compare to training data."""

    property_code: str
    current_values: list[float] = Field(min_length=2)


class DriftCheckOut(BaseModel):
    property_code: str
    reports: list[DriftReportOut]


class DriftFullRequest(BaseModel):
    """Full-feature drift check — send fresh feature vectors."""

    current_vectors: list[list[float]] = Field(
        min_length=2,
        description=(
            "One row per fresh sample.  Length must match FEATURE_NAMES "
            "returned by the /ml/models registry."
        ),
    )


class DriftFullOut(BaseModel):
    property_code: str
    reports: list[DriftReportOut]
    worst_level: str


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------
class CalibrationSample(BaseModel):
    raw_prediction: float
    actual: float
    lower: float | None = None
    upper: float | None = None


class CalibrationRequest(BaseModel):
    samples: list[CalibrationSample] = Field(min_length=2)
    target_coverage: float = Field(default=0.9, gt=0.0, lt=1.0)


class CalibrationOut(BaseModel):
    property_code: str
    version: str
    n_samples: int
    has_isotonic: bool
    has_interval: bool
    empirical_coverage: float | None = None
    target_coverage: float | None = None
    factor: float | None = None
    notes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Explainability — alias so callers importing FeatureImpactOut still work.
# ---------------------------------------------------------------------------
FeatureImpactOut = FeatureImpactOutBase


# ---------------------------------------------------------------------------
# Pareto
# ---------------------------------------------------------------------------
class ParetoRequestIn(BaseModel):
    targets: list[PropertyTargetIn]
    bounds: list[ComponentBoundsIn] = Field(default_factory=list)
    population_size: int = Field(default=24, ge=8, le=200)
    generations: int = Field(default=20, ge=1, le=200)
    mutation_std: float = Field(default=0.5, gt=0.0, le=5.0)
    seed: int | None = 42


class ParetoPointOut(BaseModel):
    mass_percent: dict[str, float]
    objectives: dict[str, float]
    rank: int
    crowding_distance: float


class ParetoResultOut(BaseModel):
    base_recipe_id: str
    front: list[ParetoPointOut]
    generations: int


class ValidationErrorResponse(BaseModel):
    detail: list[dict[str, Any]] = Field(
        examples=[
            [
                {
                    "loc": ["body", "stages", 0, "components", 2, "mass_percent"],
                    "msg": "Input should be less than or equal to 100",
                    "type": "less_than_equal",
                }
            ]
        ]
    )


__all__ = [
    "AppInfo",
    "ApplyLabResultsIn",
    "ApplyLabResultsOut",
    "BatchAnalysisOut",
    "BatchAnalysisRequest",
    "BatchCostLineOut",
    "BatchCostOut",
    "BatchInfoIn",
    "CalibrationOut",
    "CalibrationRequest",
    "CalibrationSample",
    "CatalogStats",
    "CitationIn",
    "ComponentBoundsIn",
    "ComponentIn",
    "CompositionStageIn",
    "CostLineOut",
    "CostRequest",
    "CreateRecipeRequest",
    "DeviationOut",
    "DriftCheckOut",
    "DriftCheckRequest",
    "DriftFullOut",
    "DriftFullRequest",
    "DriftReportOut",
    "ErrorResponse",
    "ExperimentCompletionIn",
    "ExperimentOut",
    "ExperimentPlanIn",
    "FeatureImpactOut",
    "FeatureImpactOutBase",
    "HealthResponse",
    "MassBalanceOut",
    "ModelMetadataOut",
    "OptimisationRequestIn",
    "OptimisationResultOut",
    "ParetoPointOut",
    "ParetoRequestIn",
    "ParetoResultOut",
    "PredictionsOut",
    "PriceIn",
    "ProcessMeasuredIn",
    "ProcessParamsIn",
    "PropertyPredictionOut",
    "PropertyTargetIn",
    "RecipeAssessmentOut",
    "RecipeCostOut",
    "RecipeSummary",
    "RegulatoryFindingOut",
    "RejectRequest",
    "RuleFindingOut",
    "SearchResponse",
    "StoichiometryFindingOut",
    "StoichiometryOut",
    "SubmitReviewRequest",
    "TrainModelsRequest",
    "TrainingResultOut",
    "UpdateRecipeRequest",
    "ValidationErrorResponse",
    "VerificationViolationOut",
    "VerifyRequest",
]
