"""Tests for ComponentFunction taxonomy and envelopes."""

from __future__ import annotations

import pytest

from formulation_workbench.domain.value_objects.functions import (
    ComponentFunction,
    envelope_for,
)


class TestComponentFunction:
    def test_all_functions_have_envelope(self) -> None:
        # Every enum value must have a curated envelope so the
        # verification-rules layer never encounters an unknown function.
        for func in ComponentFunction:
            env = envelope_for(func)
            assert env is not None
            assert env.min_percent <= env.max_percent

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("binder", ComponentFunction.BINDER),
            ("Binder", ComponentFunction.BINDER),
            ("resin", ComponentFunction.BINDER),
            ("emulsion", ComponentFunction.BINDER),
            ("latex", ComponentFunction.BINDER),
            ("filler", ComponentFunction.EXTENDER),
            ("water", ComponentFunction.VEHICLE),
            ("surfactant", ComponentFunction.WETTING_AGENT),
            ("tio2", ComponentFunction.PIGMENT),
            ("nonsense-xyz", ComponentFunction.UNSPECIFIED),
            ("", ComponentFunction.UNSPECIFIED),
        ],
    )
    def test_parse_synonyms(self, raw: str, expected: ComponentFunction) -> None:
        assert ComponentFunction.parse(raw) is expected


class TestFunctionEnvelope:
    def test_contains(self) -> None:
        env = envelope_for(ComponentFunction.DEFOAMER)
        assert env.contains(0.3)
        assert not env.contains(2.0)  # above max

    def test_envelope_min_is_realistic(self) -> None:
        # Biocides should never be allowed to reach 5 % — that would be
        # a formulation error more than an in-can preservation choice.
        env = envelope_for(ComponentFunction.IN_CAN_BIOCIDE)
        assert env.max_percent < 1.0
