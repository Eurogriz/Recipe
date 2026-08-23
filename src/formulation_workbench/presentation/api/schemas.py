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
    "CatalogStats",
    "CitationIn",
    "ComponentIn",
    "CompositionStageIn",
    "CreateRecipeRequest",
    "ErrorResponse",
    "HealthResponse",
    "ProcessParamsIn",
    "RecipeSummary",
    "RejectRequest",
    "SearchResponse",
    "SubmitReviewRequest",
    "UpdateRecipeRequest",
    "ValidationErrorResponse",
    "VerifyRequest",
]
