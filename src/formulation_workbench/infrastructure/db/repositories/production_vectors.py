"""Persistence for production feature-vector telemetry.

Small, self-contained repository — no domain aggregate, no port
interface (yet).  The drift-from-catalog endpoint reads the last N
rows for a recipe_id (or across all recipes); ingestion accepts one
or many rows in a single call.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import and_, desc, select

from ..connection import Database
from ..models import ProductionFeatureVectorModel


@dataclass(frozen=True, slots=True)
class ProductionVectorSample:
    """A single production sample as returned by the repository."""

    id: str
    recipe_id: str
    recorded_at: datetime
    source: str
    features: list[float]
    notes: str


class ProductionVectorRepository:
    """Thin CRUD over ``production_feature_vector``."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def add_many(
        self,
        samples: list[tuple[str, list[float], str, str]],
    ) -> list[str]:
        """Insert samples; each row is ``(recipe_id, features, source, notes)``.

        Returns the generated ids.
        """
        now = datetime.now(timezone.utc)
        ids: list[str] = []
        async with self._database.session() as session:
            for recipe_id, features, source, notes in samples:
                sample_id = uuid.uuid4().hex
                session.add(
                    ProductionFeatureVectorModel(
                        id=sample_id,
                        recipe_id=recipe_id,
                        recorded_at=now,
                        source=source or "lab",
                        features_json=json.dumps([float(v) for v in features]),
                        notes=notes or "",
                    )
                )
                ids.append(sample_id)
            await session.commit()
        return ids

    async def list_recent(
        self,
        *,
        recipe_id: str | None = None,
        source: str | None = None,
        limit: int = 500,
    ) -> list[ProductionVectorSample]:
        """Return the most recent samples first, optionally filtered."""
        async with self._database.session() as session:
            stmt = select(ProductionFeatureVectorModel).order_by(
                desc(ProductionFeatureVectorModel.recorded_at)
            )
            filters = []
            if recipe_id:
                filters.append(ProductionFeatureVectorModel.recipe_id == recipe_id)
            if source:
                filters.append(ProductionFeatureVectorModel.source == source)
            if filters:
                stmt = stmt.where(and_(*filters))
            stmt = stmt.limit(limit)

            rows = (await session.execute(stmt)).scalars().all()
        return [
            ProductionVectorSample(
                id=r.id,
                recipe_id=r.recipe_id,
                recorded_at=r.recorded_at,
                source=r.source,
                features=json.loads(r.features_json),
                notes=r.notes or "",
            )
            for r in rows
        ]

    async def count(self) -> int:
        async with self._database.session() as session:
            from sqlalchemy import func

            stmt = select(func.count()).select_from(ProductionFeatureVectorModel)
            return int((await session.execute(stmt)).scalar_one())


__all__ = ["ProductionVectorRepository", "ProductionVectorSample"]
