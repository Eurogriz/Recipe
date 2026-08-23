"""SQLAlchemy implementation of RecipeRepository port.

Maps between domain entities (Recipe) and SQLAlchemy models (RecipeModel).
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ....domain.entities.recipe import (
    Component,
    CompositionStage,
    ProcessParams,
    ProductClass,
    Recipe,
)
from ....domain.value_objects.citation import Citation
from ....domain.value_objects.doi import Doi
from ....domain.value_objects.isbn import Isbn
from ....domain.value_objects.verification_status import VerificationState, VerificationStatus
from ..models import (
    ComponentModel,
    CompositionStageModel,
    RecipeModel,
    RecipeSourceReferenceModel,
    SourceCitationModel,
)

if TYPE_CHECKING:
    from ..ports.recipe_repository import RecipeRepository  # noqa: F401

logger = logging.getLogger(__name__)


class SqlAlchemyRecipeRepository:
    """SQLAlchemy implementation of RecipeRepository.

    Maps domain ↔ persistence models.
    Uses async sessions and eager loading to avoid N+1 queries.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, recipe_id: str) -> Recipe | None:
        model = await self._session.get(
            RecipeModel,
            recipe_id,
            options=[
                selectinload(RecipeModel.stages).selectinload(CompositionStageModel.components)
            ],
        )
        if model is None:
            return None
        return await self._to_entity(model)

    async def save(self, recipe: Recipe) -> None:
        """Save (insert or update) a recipe.

        For MVP, we do full replace: delete old stages/components and insert new ones.
        For production, we'd do more granular change detection.
        """
        existing = await self._session.get(RecipeModel, recipe.id)
        if existing is None:
            model = self._to_model(recipe)
            self._session.add(model)
        else:
            # Update in-place
            self._update_model_from_entity(existing, recipe)
        await self._session.flush()

    async def delete(self, recipe_id: str) -> None:
        model = await self._session.get(RecipeModel, recipe_id)
        if model is not None:
            await self._session.delete(model)
            await self._session.flush()

    async def search_by_text(self, query: str, limit: int = 50) -> list[Recipe]:
        """Simple LIKE search for MVP. FTS5 will be added in next iteration."""
        stmt = (
            select(RecipeModel)
            .where(
                (RecipeModel.category.contains(query))
                | (RecipeModel.subcategory.contains(query))
                | (RecipeModel.intended_use.contains(query))
                | (RecipeModel.binder_type.contains(query))
            )
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        models = result.scalars().all()
        return [await self._to_entity(m) for m in models]

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
        stmt = select(RecipeModel)
        if category:
            stmt = stmt.where(RecipeModel.category == category)
        if subcategory:
            stmt = stmt.where(RecipeModel.subcategory == subcategory)
        if product_class:
            stmt = stmt.where(RecipeModel.product_class == product_class)
        if status:
            stmt = stmt.where(RecipeModel.status == status.value)
        if tags:
            # Tags are stored in metadata_json; simplistic JSON search
            for tag in tags:
                stmt = stmt.where(RecipeModel.metadata_json.contains(f'"{tag}"'))
        stmt = stmt.limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        models = result.scalars().all()
        return [await self._to_entity(m) for m in models]

    async def count_by_status(self) -> dict[VerificationState, int]:
        from sqlalchemy import func

        stmt = select(RecipeModel.status, func.count(RecipeModel.id)).group_by(RecipeModel.status)
        result = await self._session.execute(stmt)
        rows = result.all()
        counts: dict[VerificationState, int] = dict.fromkeys(VerificationState, 0)
        for status_value, count in rows:
            try:
                counts[VerificationState(status_value)] = count
            except ValueError:
                logger.warning("Unknown status value in DB: %s", status_value)
        return counts

    async def get_all_versions(self, recipe_id: str) -> list[Recipe]:
        # Walk back via previous_version_id chain
        result: list[Recipe] = []
        current_id: str | None = recipe_id
        while current_id is not None:
            recipe = await self.get_by_id(current_id)
            if recipe is None:
                break
            result.append(recipe)
            current_id = recipe.previous_version_id
        return result

    # ============================================================================
    # Mapping helpers
    # ============================================================================

    def _to_model(self, recipe: Recipe) -> RecipeModel:
        """Convert Recipe domain entity to RecipeModel."""
        model = RecipeModel(
            id=recipe.id,
            schema_version=recipe.schema_version,
            category=recipe.category,
            subcategory=recipe.subcategory,
            binder_type=recipe.binder_type,
            product_class=recipe.product_class.value,
            intended_use=recipe.intended_use,
            finish=recipe.finish,
            color=recipe.color,
            created_by=recipe.created_by,
            created_at=recipe.created_at,
            updated_at=recipe.created_at,
            version=recipe.version,
            previous_version_id=recipe.previous_version_id,
            status=recipe.status.state.value,
            verification_count=recipe.status.verification_count,
            required_verifications=recipe.status.required_verifications,
            metadata_json=json.dumps({"tags": list(recipe.tags)}),
        )
        # Stages + components
        for stage in recipe.stages:
            stage_model = CompositionStageModel(
                stage_number=stage.stage_number,
                name=stage.name,
                description=stage.description,
                equipment=stage.process.equipment if stage.process else None,
                rotational_speed_rpm=stage.process.rotational_speed_rpm if stage.process else None,
                peripheral_speed_m_per_s=stage.process.peripheral_speed_m_per_s
                if stage.process
                else None,
                temperature_c=stage.process.temperature_c if stage.process else None,
                duration_min=stage.process.duration_min if stage.process else None,
                control_points_json=json.dumps(list(stage.process.control_points))
                if stage.process
                else None,
            )
            for comp in stage.components:
                comp_model = ComponentModel(
                    name=comp.name,
                    cas_number=comp.cas_number,
                    inci_name=comp.inci_name,
                    function=comp.function,
                    manufacturer_reference=comp.manufacturer_reference,
                    mass_percent=comp.mass_percent,
                    tolerance_percent=comp.tolerance_percent,
                    order_in_stage=0,  # TODO: add order to Component
                    notes=comp.notes,
                    is_predicted=comp.is_predicted,
                )
                stage_model.components.append(comp_model)
            model.stages.append(stage_model)

        # Source reference (primary)
        # For MVP, only persist primary; cross-references would need separate handling
        primary_citation = self._to_citation_model(recipe.primary_source)
        ref = RecipeSourceReferenceModel(
            citation=primary_citation,
            is_primary=True,
            page_or_formula=recipe.primary_source.page_or_formula,
            section=recipe.primary_source.section,
        )
        model.primary_source = ref
        return model

    def _to_citation_model(self, citation: Citation) -> SourceCitationModel:
        return SourceCitationModel(
            authors=citation.authors,
            title=citation.title,
            edition=citation.edition or None,
            publisher=citation.publisher,
            year=citation.year,
            isbn=str(citation.isbn) if citation.isbn else None,
            doi=str(citation.doi) if citation.doi else None,
            url=citation.url,
        )

    def _update_model_from_entity(self, model: RecipeModel, recipe: Recipe) -> None:
        model.schema_version = recipe.schema_version
        model.category = recipe.category
        model.subcategory = recipe.subcategory
        model.binder_type = recipe.binder_type
        model.product_class = recipe.product_class.value
        model.intended_use = recipe.intended_use
        model.finish = recipe.finish
        model.color = recipe.color
        model.status = recipe.status.state.value
        model.verification_count = recipe.status.verification_count
        model.required_verifications = recipe.status.required_verifications
        model.metadata_json = json.dumps({"tags": list(recipe.tags)})
        # Stages/components replace (simplified for MVP)
        model.stages.clear()
        for stage in recipe.stages:
            stage_model = CompositionStageModel(
                stage_number=stage.stage_number,
                name=stage.name,
                description=stage.description,
                equipment=stage.process.equipment if stage.process else None,
                rotational_speed_rpm=stage.process.rotational_speed_rpm if stage.process else None,
                peripheral_speed_m_per_s=stage.process.peripheral_speed_m_per_s
                if stage.process
                else None,
                temperature_c=stage.process.temperature_c if stage.process else None,
                duration_min=stage.process.duration_min if stage.process else None,
                control_points_json=json.dumps(list(stage.process.control_points))
                if stage.process
                else None,
            )
            for comp in stage.components:
                comp_model = ComponentModel(
                    name=comp.name,
                    cas_number=comp.cas_number,
                    inci_name=comp.inci_name,
                    function=comp.function,
                    manufacturer_reference=comp.manufacturer_reference,
                    mass_percent=comp.mass_percent,
                    tolerance_percent=comp.tolerance_percent,
                    order_in_stage=0,
                    notes=comp.notes,
                    is_predicted=comp.is_predicted,
                )
                stage_model.components.append(comp_model)
            model.stages.append(stage_model)

    async def _to_entity(self, model: RecipeModel) -> Recipe:
        """Convert RecipeModel to Recipe domain entity."""
        # Primary source citation
        primary_source: Citation
        if model.primary_source is not None:
            primary_source = self._citation_from_model(
                model.primary_source.citation,
                page_or_formula=model.primary_source.page_or_formula or "",
                section=model.primary_source.section or "",
            )
        else:
            # Fallback — should never happen due to validation
            raise ValueError(f"Recipe {model.id} has no primary source reference")

        # Cross-references — for MVP, we treat primary only
        cross_references: tuple[Citation, ...] = ()

        # Stages
        stages: list[CompositionStage] = []
        for stage_model in sorted(model.stages, key=lambda s: s.stage_number):
            process = None
            if stage_model.equipment:
                control_points: tuple[dict[str, str], ...] = ()
                if stage_model.control_points_json:
                    control_points = tuple(json.loads(stage_model.control_points_json))
                process = ProcessParams(
                    equipment=stage_model.equipment,
                    rotational_speed_rpm=stage_model.rotational_speed_rpm,
                    peripheral_speed_m_per_s=stage_model.peripheral_speed_m_per_s,
                    temperature_c=stage_model.temperature_c,
                    duration_min=stage_model.duration_min,
                    control_points=control_points,
                )
            components = tuple(
                Component(
                    name=c.name,
                    cas_number=c.cas_number,
                    function=c.function,
                    mass_percent=c.mass_percent,
                    tolerance_percent=c.tolerance_percent,
                    inci_name=c.inci_name or "",
                    manufacturer_reference=c.manufacturer_reference or "",
                    notes=c.notes or "",
                )
                for c in stage_model.components
            )
            stages.append(
                CompositionStage(
                    stage_number=stage_model.stage_number,
                    name=stage_model.name,
                    description=stage_model.description or "",
                    components=components,
                    process=process,
                )
            )

        status = VerificationStatus(
            state=VerificationState(model.status),
            verification_count=model.verification_count,
            required_verifications=model.required_verifications,
        )

        tags: tuple[str, ...] = ()
        if model.metadata_json:
            try:
                meta = json.loads(model.metadata_json)
                tags = tuple(meta.get("tags", []))
            except json.JSONDecodeError:
                pass

        return Recipe(
            id=model.id,
            category=model.category,
            subcategory=model.subcategory,
            binder_type=model.binder_type,
            product_class=ProductClass(model.product_class),
            intended_use=model.intended_use,
            stages=tuple(stages),
            primary_source=primary_source,
            cross_references=cross_references,
            status=status,
            created_at=model.created_at,
            created_by=model.created_by,
            version=model.version,
            previous_version_id=model.previous_version_id,
            tags=tags,
            finish=model.finish or "",
            color=model.color or "",
        )

    def _citation_from_model(
        self, model: SourceCitationModel, page_or_formula: str = "", section: str = ""
    ) -> Citation:
        isbn = None
        if model.isbn:
            try:
                isbn = Isbn(model.isbn)
            except Exception:
                isbn = None  # Fallback for legacy data

        doi = None
        if model.doi:
            try:
                doi = Doi(model.doi)
            except Exception:
                doi = None

        return Citation(
            authors=model.authors,
            title=model.title,
            year=model.year,
            publisher=model.publisher,
            edition=model.edition or "",
            isbn=isbn,
            doi=doi,
            url=model.url,
            page_or_formula=page_or_formula,
            section=section,
        )
