"""Laboratory experiment aggregate.

Bridges *predicted* properties (calculators) and *measured* properties
(lab bench) so that a recipe's evolution — v1 → v2 → v3 — is captured
as a first-class object.

An :class:`ExperimentRun` represents one physical batch, tests, and
verdict.  A :class:`RecipeIteration` chains iterations of the same
recipe with the deltas the formulator wants to explore next.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from ..value_objects.target_properties import TargetSpecification, TestMethod


class ExperimentStatus(str, Enum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Verdict(str, Enum):
    PASSED = "passed"
    PASSED_WITH_DEVIATION = "passed_with_deviation"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True, slots=True)
class MeasuredValue:
    """One measured value from the lab."""

    property_code: str
    value: float
    unit: str = ""
    method: TestMethod | None = None
    measured_at: datetime | None = None
    operator: str = ""
    notes: str = ""

    def satisfies(self, spec: TargetSpecification) -> bool:
        return spec.is_satisfied_by(self.value)


@dataclass(frozen=True, slots=True)
class BatchInfo:
    """Physical batch produced for an experiment."""

    batch_number: str
    target_mass_kg: float
    actual_mass_kg: float | None = None
    produced_at: datetime | None = None
    lot_numbers: dict[str, str] = field(default_factory=dict)  # component name → supplier lot
    equipment_used: str = ""

    def __post_init__(self) -> None:
        if not self.batch_number or not self.batch_number.strip():
            raise ValueError("BatchInfo.batch_number must be non-empty")
        if self.target_mass_kg <= 0:
            raise ValueError("target_mass_kg must be positive")
        if self.actual_mass_kg is not None and self.actual_mass_kg <= 0:
            raise ValueError("actual_mass_kg must be positive")


class InvalidExperimentError(ValueError):
    """Raised when an experiment aggregate is constructed incorrectly."""


class ExperimentRun:
    """One physical experiment run against a recipe version.

    Immutable-in-practice: mutating helpers return a new instance so we
    can safely share an :class:`ExperimentRun` between threads / tasks.
    """

    def __init__(
        self,
        recipe_id: str,
        recipe_version: int,
        *,
        id: str | None = None,
        title: str = "",
        hypothesis: str = "",
        status: ExperimentStatus = ExperimentStatus.PLANNED,
        verdict: Verdict | None = None,
        batch: BatchInfo | None = None,
        target_properties: tuple[TargetSpecification, ...] = (),
        measured_properties: tuple[MeasuredValue, ...] = (),
        operator: str = "",
        created_at: datetime | None = None,
        completed_at: datetime | None = None,
        notes: str = "",
    ) -> None:
        if not recipe_id:
            raise InvalidExperimentError("recipe_id required")
        if recipe_version < 1:
            raise InvalidExperimentError("recipe_version must be >= 1")

        if status is ExperimentStatus.COMPLETED and batch is None:
            raise InvalidExperimentError("Completed experiment must have a BatchInfo")
        if status is ExperimentStatus.COMPLETED and not measured_properties:
            raise InvalidExperimentError(
                "Completed experiment must record at least one measured value"
            )
        if status is not ExperimentStatus.COMPLETED and verdict is not None:
            raise InvalidExperimentError("Verdict is only meaningful for completed experiments")

        self._id = id or str(uuid.uuid4())
        self._recipe_id = recipe_id
        self._recipe_version = recipe_version
        self._title = title.strip()
        self._hypothesis = hypothesis
        self._status = status
        self._verdict = verdict
        self._batch = batch
        self._target_properties = tuple(target_properties)
        self._measured_properties = tuple(measured_properties)
        self._operator = operator
        self._created_at = created_at or datetime.now(timezone.utc)
        self._completed_at = completed_at
        self._notes = notes

    # -------- read-only accessors ------------------------------------------
    @property
    def id(self) -> str:
        return self._id

    @property
    def recipe_id(self) -> str:
        return self._recipe_id

    @property
    def recipe_version(self) -> int:
        return self._recipe_version

    @property
    def title(self) -> str:
        return self._title

    @property
    def hypothesis(self) -> str:
        return self._hypothesis

    @property
    def status(self) -> ExperimentStatus:
        return self._status

    @property
    def verdict(self) -> Verdict | None:
        return self._verdict

    @property
    def batch(self) -> BatchInfo | None:
        return self._batch

    @property
    def target_properties(self) -> tuple[TargetSpecification, ...]:
        return self._target_properties

    @property
    def measured_properties(self) -> tuple[MeasuredValue, ...]:
        return self._measured_properties

    @property
    def operator(self) -> str:
        return self._operator

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def completed_at(self) -> datetime | None:
        return self._completed_at

    @property
    def notes(self) -> str:
        return self._notes

    # -------- domain operations --------------------------------------------
    def start(self) -> ExperimentRun:
        if self._status is not ExperimentStatus.PLANNED:
            raise InvalidExperimentError(
                f"Only PLANNED experiments can be started (current: {self._status.value})"
            )
        return self._copy(status=ExperimentStatus.IN_PROGRESS)

    def cancel(self, note: str = "") -> ExperimentRun:
        if self._status in {ExperimentStatus.COMPLETED, ExperimentStatus.CANCELLED}:
            raise InvalidExperimentError("Experiment already terminated")
        return self._copy(status=ExperimentStatus.CANCELLED, notes=note or self._notes)

    def complete(
        self,
        batch: BatchInfo,
        measured_properties: tuple[MeasuredValue, ...],
    ) -> ExperimentRun:
        if self._status not in {ExperimentStatus.PLANNED, ExperimentStatus.IN_PROGRESS}:
            raise InvalidExperimentError(
                f"Cannot complete an experiment in state {self._status.value}"
            )
        if not measured_properties:
            raise InvalidExperimentError("Completing requires at least one measured value")

        verdict = self._compute_verdict(measured_properties)
        return self._copy(
            status=ExperimentStatus.COMPLETED,
            verdict=verdict,
            batch=batch,
            measured_properties=tuple(measured_properties),
            completed_at=datetime.now(timezone.utc),
        )

    def _compute_verdict(self, measured: tuple[MeasuredValue, ...]) -> Verdict:
        """Pass/fail across ``target_properties`` using measured values."""
        specs_by_code = {t.property_code: t for t in self._target_properties}
        if not specs_by_code:
            return Verdict.INCONCLUSIVE

        passes = 0
        deviations = 0
        checked = 0
        for mv in measured:
            spec = specs_by_code.get(mv.property_code)
            if spec is None:
                continue
            checked += 1
            if mv.satisfies(spec):
                passes += 1
            else:
                deviations += 1

        if checked == 0:
            return Verdict.INCONCLUSIVE
        if deviations == 0:
            return Verdict.PASSED
        if passes >= deviations * 2:
            return Verdict.PASSED_WITH_DEVIATION
        return Verdict.FAILED

    # -------- helpers -------------------------------------------------------
    def _copy(self, **overrides) -> ExperimentRun:  # type: ignore[no-untyped-def]
        return ExperimentRun(
            recipe_id=self._recipe_id,
            recipe_version=self._recipe_version,
            id=self._id,
            title=self._title,
            hypothesis=self._hypothesis,
            status=overrides.get("status", self._status),
            verdict=overrides.get("verdict", self._verdict),
            batch=overrides.get("batch", self._batch),
            target_properties=overrides.get("target_properties", self._target_properties),
            measured_properties=overrides.get("measured_properties", self._measured_properties),
            operator=self._operator,
            created_at=self._created_at,
            completed_at=overrides.get("completed_at", self._completed_at),
            notes=overrides.get("notes", self._notes),
        )

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ExperimentRun) and self._id == other._id

    def __hash__(self) -> int:
        return hash(self._id)

    def __repr__(self) -> str:
        return (
            f"ExperimentRun(id='{self._id[:8]}...', "
            f"recipe='{self._recipe_id[:8]}...', "
            f"v{self._recipe_version}, {self._status.value}"
            f"{', ' + self._verdict.value if self._verdict else ''})"
        )


__all__ = [
    "BatchInfo",
    "ExperimentRun",
    "ExperimentStatus",
    "InvalidExperimentError",
    "MeasuredValue",
    "Verdict",
]
