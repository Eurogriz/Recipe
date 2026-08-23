"""Experiment repository port."""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...domain.entities.experiment import ExperimentRun


class ExperimentRepository(abc.ABC):
    """Async interface for persisting :class:`ExperimentRun` aggregates."""

    @abc.abstractmethod
    async def get_by_id(self, experiment_id: str) -> ExperimentRun | None: ...

    @abc.abstractmethod
    async def save(self, run: ExperimentRun) -> None: ...

    @abc.abstractmethod
    async def list_for_recipe(self, recipe_id: str) -> list[ExperimentRun]: ...


__all__ = ["ExperimentRepository"]
