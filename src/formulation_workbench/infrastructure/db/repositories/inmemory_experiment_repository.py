"""In-memory :class:`ExperimentRepository` implementation.

Used until the SQLAlchemy schema for experiments lands.  The
implementation is thread-unsafe on purpose — the FastAPI worker holds a
single instance behind a lock in the DI container and every operation
already runs inside the asyncio event loop.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from ....application.ports.experiment_repository import ExperimentRepository

if TYPE_CHECKING:
    from ....domain.entities.experiment import ExperimentRun


class InMemoryExperimentRepository(ExperimentRepository):
    def __init__(self) -> None:
        self._store: dict[str, ExperimentRun] = {}
        self._lock = asyncio.Lock()

    async def get_by_id(self, experiment_id: str) -> ExperimentRun | None:
        async with self._lock:
            return self._store.get(experiment_id)

    async def save(self, run: ExperimentRun) -> None:
        async with self._lock:
            self._store[run.id] = run

    async def list_for_recipe(self, recipe_id: str) -> list[ExperimentRun]:
        async with self._lock:
            return sorted(
                (r for r in self._store.values() if r.recipe_id == recipe_id),
                key=lambda r: r.created_at,
            )


__all__ = ["InMemoryExperimentRepository"]
