"""SQLAlchemy implementation of :class:`ExperimentRepository`.

Maps :class:`ExperimentRun` <-> :class:`ExperimentRunModel` +
:class:`MeasuredValueModel`.  Uses session-per-operation wiring for the
same reason as the recipe repository (see ``session_scoped.py``).
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ....application.ports.experiment_repository import ExperimentRepository
from ....domain.entities.experiment import (
    BatchInfo,
    ExperimentRun,
    ExperimentStatus,
    MeasuredValue,
    Verdict,
)
from ....domain.value_objects.target_properties import (
    TargetSpecification,
    ToleranceMode,
)
from ..models import ExperimentRunModel, MeasuredValueModel

if TYPE_CHECKING:
    from ..connection import Database

logger = logging.getLogger(__name__)


class SqlAlchemyExperimentRepository:
    """Persistence for :class:`ExperimentRun` inside a single session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, experiment_id: str) -> ExperimentRun | None:
        model = await self._session.get(
            ExperimentRunModel,
            experiment_id,
            options=[selectinload(ExperimentRunModel.measured_values)],
        )
        if model is None:
            return None
        return _to_entity(model)

    async def save(self, run: ExperimentRun) -> None:
        existing = await self._session.get(
            ExperimentRunModel,
            run.id,
            options=[selectinload(ExperimentRunModel.measured_values)],
        )
        if existing is None:
            model = _to_model(run)
            self._session.add(model)
            await self._session.flush()
        else:
            # Replace scalar fields.
            _update_scalars(existing, run)
            # Replace measured values.  We flush *between* delete + insert
            # so SQLite's UNIQUE(run_id, property_code) doesn't fire on
            # replays with the same property codes.
            existing.measured_values.clear()
            await self._session.flush()
            for mv in run.measured_properties:
                existing.measured_values.append(_measured_to_model(mv))
            await self._session.flush()

    async def list_for_recipe(self, recipe_id: str) -> list[ExperimentRun]:
        stmt = (
            select(ExperimentRunModel)
            .options(selectinload(ExperimentRunModel.measured_values))
            .where(ExperimentRunModel.recipe_id == recipe_id)
            .order_by(ExperimentRunModel.created_at)
        )
        result = await self._session.execute(stmt)
        return [_to_entity(m) for m in result.scalars().all()]


# ---------------------------------------------------------------------------
# Session-scoped adapter (same idiom as the recipe repo).
# ---------------------------------------------------------------------------
class ScopedExperimentRepository(ExperimentRepository):
    """Session-per-operation wrapper suitable for the DI container."""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def get_by_id(self, experiment_id: str) -> ExperimentRun | None:
        async with self._db.session() as session:
            return await SqlAlchemyExperimentRepository(session).get_by_id(experiment_id)

    async def save(self, run: ExperimentRun) -> None:
        async with self._db.session() as session:
            await SqlAlchemyExperimentRepository(session).save(run)
            await session.commit()

    async def list_for_recipe(self, recipe_id: str) -> list[ExperimentRun]:
        async with self._db.session() as session:
            return await SqlAlchemyExperimentRepository(session).list_for_recipe(recipe_id)


# ---------------------------------------------------------------------------
# Mapping helpers
# ---------------------------------------------------------------------------
def _dump_target_specs(specs: tuple[TargetSpecification, ...]) -> str | None:
    if not specs:
        return None
    payload = [
        {
            "property_code": s.property_code,
            "target_value": s.target_value,
            "tolerance": s.tolerance,
            "tolerance_mode": s.tolerance_mode.value,
            "unit": s.unit,
            "notes": s.notes,
        }
        for s in specs
    ]
    return json.dumps(payload)


def _load_target_specs(raw: str | None) -> tuple[TargetSpecification, ...]:
    if not raw:
        return ()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Could not decode target_properties_json — treating as empty")
        return ()
    specs: list[TargetSpecification] = []
    for item in payload:
        try:
            specs.append(
                TargetSpecification(
                    property_code=item["property_code"],
                    target_value=float(item["target_value"]),
                    tolerance=float(item.get("tolerance", 0.0)),
                    tolerance_mode=ToleranceMode(item.get("tolerance_mode", "absolute")),
                    unit=item.get("unit", ""),
                    notes=item.get("notes", ""),
                )
            )
        except (KeyError, ValueError):
            logger.warning("Skipping malformed target spec: %s", item)
    return tuple(specs)


def _to_model(run: ExperimentRun) -> ExperimentRunModel:
    batch = run.batch
    return ExperimentRunModel(
        id=run.id,
        recipe_id=run.recipe_id,
        recipe_version=run.recipe_version,
        title=run.title,
        hypothesis=run.hypothesis,
        status=run.status.value,
        verdict=run.verdict.value if run.verdict is not None else None,
        operator=run.operator,
        notes=run.notes,
        batch_number=batch.batch_number if batch else None,
        batch_target_mass_kg=batch.target_mass_kg if batch else None,
        batch_actual_mass_kg=batch.actual_mass_kg if batch else None,
        batch_equipment_used=batch.equipment_used if batch else None,
        batch_lot_numbers_json=json.dumps(batch.lot_numbers)
        if batch and batch.lot_numbers
        else None,
        target_properties_json=_dump_target_specs(run.target_properties),
        created_at=run.created_at,
        completed_at=run.completed_at,
        measured_values=[_measured_to_model(mv) for mv in run.measured_properties],
    )


def _update_scalars(model: ExperimentRunModel, run: ExperimentRun) -> None:
    batch = run.batch
    model.title = run.title
    model.hypothesis = run.hypothesis
    model.status = run.status.value
    model.verdict = run.verdict.value if run.verdict is not None else None
    model.operator = run.operator
    model.notes = run.notes
    model.batch_number = batch.batch_number if batch else None
    model.batch_target_mass_kg = batch.target_mass_kg if batch else None
    model.batch_actual_mass_kg = batch.actual_mass_kg if batch else None
    model.batch_equipment_used = batch.equipment_used if batch else None
    model.batch_lot_numbers_json = (
        json.dumps(batch.lot_numbers) if batch and batch.lot_numbers else None
    )
    model.target_properties_json = _dump_target_specs(run.target_properties)
    model.completed_at = run.completed_at


def _measured_to_model(mv: MeasuredValue) -> MeasuredValueModel:
    return MeasuredValueModel(
        property_code=mv.property_code,
        value=mv.value,
        unit=mv.unit,
        method_standard=mv.method.standard if mv.method is not None else None,
        measured_at=mv.measured_at,
        operator=mv.operator,
        notes=mv.notes,
    )


def _to_entity(model: ExperimentRunModel) -> ExperimentRun:
    batch: BatchInfo | None = None
    if model.batch_number and model.batch_target_mass_kg is not None:
        try:
            lot_numbers = (
                json.loads(model.batch_lot_numbers_json) if model.batch_lot_numbers_json else {}
            )
        except json.JSONDecodeError:
            lot_numbers = {}
        batch = BatchInfo(
            batch_number=model.batch_number,
            target_mass_kg=model.batch_target_mass_kg,
            actual_mass_kg=model.batch_actual_mass_kg,
            equipment_used=model.batch_equipment_used or "",
            lot_numbers=lot_numbers,
        )

    measured = tuple(
        MeasuredValue(
            property_code=mv.property_code,
            value=mv.value,
            unit=mv.unit,
            measured_at=mv.measured_at,
            operator=mv.operator,
            notes=mv.notes,
        )
        for mv in model.measured_values
    )

    verdict = Verdict(model.verdict) if model.verdict else None

    return ExperimentRun(
        recipe_id=model.recipe_id,
        recipe_version=model.recipe_version,
        id=model.id,
        title=model.title,
        hypothesis=model.hypothesis,
        status=ExperimentStatus(model.status),
        verdict=verdict,
        batch=batch,
        target_properties=_load_target_specs(model.target_properties_json),
        measured_properties=measured,
        operator=model.operator,
        created_at=model.created_at,
        completed_at=model.completed_at,
        notes=model.notes,
    )


__all__ = [
    "ScopedExperimentRepository",
    "SqlAlchemyExperimentRepository",
]
