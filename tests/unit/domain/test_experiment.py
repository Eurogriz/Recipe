"""Tests for the ExperimentRun / BatchInfo / MeasuredValue aggregate."""

from __future__ import annotations

import pytest

from formulation_workbench.domain.entities.experiment import (
    BatchInfo,
    ExperimentRun,
    ExperimentStatus,
    InvalidExperimentError,
    MeasuredValue,
    Verdict,
)
from formulation_workbench.domain.value_objects.target_properties import (
    TargetSpecification,
    ToleranceMode,
)


def _batch() -> BatchInfo:
    return BatchInfo(batch_number="B-001", target_mass_kg=10.0, actual_mass_kg=9.9)


def _specs() -> tuple[TargetSpecification, ...]:
    return (
        TargetSpecification(property_code="gloss_60", target_value=80.0, tolerance=5.0),
        TargetSpecification(
            property_code="voc_content",
            target_value=30.0,
            tolerance_mode=ToleranceMode.MAX,
        ),
    )


def _plan() -> ExperimentRun:
    return ExperimentRun(
        recipe_id="recipe-1",
        recipe_version=1,
        title="Trial 1",
        hypothesis="Increase coalescent should raise gloss",
        target_properties=_specs(),
        operator="alice",
    )


class TestConstructor:
    def test_planned_is_default(self) -> None:
        exp = _plan()
        assert exp.status is ExperimentStatus.PLANNED
        assert exp.verdict is None
        assert exp.recipe_id == "recipe-1"

    def test_completed_without_batch_rejected(self) -> None:
        with pytest.raises(InvalidExperimentError):
            ExperimentRun(
                recipe_id="r1",
                recipe_version=1,
                status=ExperimentStatus.COMPLETED,
                measured_properties=(MeasuredValue(property_code="gloss_60", value=80.0),),
            )

    def test_completed_without_measurements_rejected(self) -> None:
        with pytest.raises(InvalidExperimentError):
            ExperimentRun(
                recipe_id="r1",
                recipe_version=1,
                status=ExperimentStatus.COMPLETED,
                batch=_batch(),
                measured_properties=(),
            )

    def test_verdict_only_for_completed(self) -> None:
        with pytest.raises(InvalidExperimentError):
            ExperimentRun(
                recipe_id="r1",
                recipe_version=1,
                verdict=Verdict.PASSED,
            )


class TestStateTransitions:
    def test_start(self) -> None:
        exp = _plan().start()
        assert exp.status is ExperimentStatus.IN_PROGRESS

    def test_double_start_rejected(self) -> None:
        exp = _plan().start()
        with pytest.raises(InvalidExperimentError):
            exp.start()

    def test_cancel_from_planned(self) -> None:
        exp = _plan().cancel("changed_priorities")
        assert exp.status is ExperimentStatus.CANCELLED

    def test_cancel_from_in_progress(self) -> None:
        exp = _plan().start().cancel("safety_incident")
        assert exp.status is ExperimentStatus.CANCELLED


class TestCompletion:
    def test_complete_passing(self) -> None:
        exp = (
            _plan()
            .start()
            .complete(
                _batch(),
                (
                    MeasuredValue(property_code="gloss_60", value=82.0),
                    MeasuredValue(property_code="voc_content", value=25.0),
                ),
            )
        )
        assert exp.status is ExperimentStatus.COMPLETED
        assert exp.verdict is Verdict.PASSED
        assert exp.batch is not None
        assert exp.completed_at is not None

    def test_complete_failing(self) -> None:
        exp = (
            _plan()
            .start()
            .complete(
                _batch(),
                (
                    MeasuredValue(property_code="gloss_60", value=50.0),  # out
                    MeasuredValue(property_code="voc_content", value=200.0),  # out
                ),
            )
        )
        assert exp.verdict is Verdict.FAILED

    def test_complete_deviation_when_mostly_pass(self) -> None:
        # 2 pass + 1 miss → passed_with_deviation
        specs = (
            TargetSpecification(property_code="gloss_60", target_value=80.0, tolerance=5.0),
            TargetSpecification(property_code="ph", target_value=8.5, tolerance=0.5),
            TargetSpecification(
                property_code="voc_content", target_value=30.0, tolerance_mode=ToleranceMode.MAX
            ),
        )
        exp = (
            ExperimentRun(
                recipe_id="r1",
                recipe_version=1,
                target_properties=specs,
            )
            .start()
            .complete(
                _batch(),
                (
                    MeasuredValue(property_code="gloss_60", value=82.0),
                    MeasuredValue(property_code="ph", value=8.4),
                    MeasuredValue(property_code="voc_content", value=45.0),  # miss
                ),
            )
        )
        assert exp.verdict is Verdict.PASSED_WITH_DEVIATION

    def test_complete_without_specs_inconclusive(self) -> None:
        exp = (
            ExperimentRun(recipe_id="r1", recipe_version=1)
            .start()
            .complete(
                _batch(),
                (MeasuredValue(property_code="gloss_60", value=80.0),),
            )
        )
        assert exp.verdict is Verdict.INCONCLUSIVE


class TestBatchInfoInvariants:
    def test_batch_number_required(self) -> None:
        with pytest.raises(ValueError):
            BatchInfo(batch_number="", target_mass_kg=1.0)

    def test_target_mass_positive(self) -> None:
        with pytest.raises(ValueError):
            BatchInfo(batch_number="B-1", target_mass_kg=0.0)


class TestMeasuredValueSatisfies:
    def test_within_tolerance(self) -> None:
        mv = MeasuredValue(property_code="gloss_60", value=82.0)
        spec = TargetSpecification(property_code="gloss_60", target_value=80.0, tolerance=5.0)
        assert mv.satisfies(spec)

    def test_outside_tolerance(self) -> None:
        mv = MeasuredValue(property_code="gloss_60", value=95.0)
        spec = TargetSpecification(property_code="gloss_60", target_value=80.0, tolerance=5.0)
        assert not mv.satisfies(spec)
