"""Mappers between HTTP schemas and domain entities.

The HTTP surface is deliberately decoupled from the domain model: this
module is the *single* place where a request body is turned into a
:class:`Recipe`. The application layer never sees a Pydantic model.
"""

from __future__ import annotations

from ...domain.entities.recipe import (
    Component,
    CompositionStage,
    ProcessParams,
    ProductClass,
    Recipe,
)
from ...domain.value_objects.citation import Citation
from ...domain.value_objects.doi import Doi
from ...domain.value_objects.isbn import Isbn
from .schemas import CitationIn, CreateRecipeRequest


def _to_citation(dto: CitationIn) -> Citation:
    return Citation(
        authors=dto.authors,
        title=dto.title,
        year=dto.year,
        publisher=dto.publisher,
        isbn=Isbn(dto.isbn) if dto.isbn else None,
        doi=Doi(dto.doi) if dto.doi else None,
        url=dto.url or "",
        page_or_formula=dto.page_or_formula,
    )


def to_recipe(dto: CreateRecipeRequest, *, recipe_id: str | None = None) -> Recipe:
    """Build a :class:`Recipe` aggregate from the request body.

    ``recipe_id`` overrides ``dto.id`` when non-null (used by ``PUT``
    handlers so the caller can't pin a different id in the body).
    """
    try:
        product_class = ProductClass(dto.product_class)
    except ValueError as e:
        allowed = ", ".join(c.value for c in ProductClass)
        raise ValueError(f"Unknown product_class '{dto.product_class}'. Allowed: {allowed}") from e

    stages: list[CompositionStage] = []
    for stage in dto.stages:
        components = tuple(
            Component(
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
        )
        process = (
            ProcessParams(
                equipment=stage.process.equipment,
                rotational_speed_rpm=stage.process.rotational_speed_rpm,
                peripheral_speed_m_per_s=stage.process.peripheral_speed_m_per_s,
                temperature_c=stage.process.temperature_c,
                duration_min=stage.process.duration_min,
            )
            if stage.process
            else None
        )
        stages.append(
            CompositionStage(
                stage_number=stage.stage_number,
                name=stage.name,
                description=stage.description,
                components=components,
                process=process,
            )
        )

    return Recipe(
        id=recipe_id or dto.id,
        category=dto.category,
        subcategory=dto.subcategory,
        binder_type=dto.binder_type,
        product_class=product_class,
        intended_use=dto.intended_use,
        finish=dto.finish,
        color=dto.color,
        tags=tuple(dto.tags),
        stages=tuple(stages),
        primary_source=_to_citation(dto.primary_source),
        cross_references=tuple(_to_citation(c) for c in dto.cross_references),
    )


__all__ = ["to_recipe"]
