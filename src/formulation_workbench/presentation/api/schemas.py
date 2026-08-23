"""Pydantic schemas for the REST API.

These mirror the application-layer DTOs but are separated so that the
HTTP contract can evolve without touching internal domain code.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    """Simple readiness probe payload."""

    status: str = Field(default="ok", examples=["ok"])
    version: str
    environment: str


class AppInfo(BaseModel):
    """Build + runtime information (Spring-Boot ``/actuator/info``-style)."""

    name: str
    version: str
    environment: str
    python: str
    platform: str
    git_sha: str
    build_date: str


class RecipeSummary(BaseModel):
    """Lightweight recipe representation for list endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    category: str
    subcategory: str
    binder_type: str
    product_class: str
    intended_use: str
    status: str
    verification_count: int
    verification_required: int
    version: int


class SearchResponse(BaseModel):
    items: list[RecipeSummary]
    total_count: int
    limit: int
    offset: int
    has_more: bool


class CatalogStats(BaseModel):
    total: int
    by_status: dict[str, int]


class ErrorResponse(BaseModel):
    detail: str
    code: str | None = None


__all__ = [
    "AppInfo",
    "CatalogStats",
    "ErrorResponse",
    "HealthResponse",
    "RecipeSummary",
    "SearchResponse",
]
