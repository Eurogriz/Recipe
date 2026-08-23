"""Tests for the REACH / Annex XVII CSV loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from formulation_workbench.infrastructure.regulatory import (
    RegulatoryDataError,
    build_checker_from_data_dir,
    load_annex_xvii_from_csv,
    load_svhc_from_csv,
)

pytestmark = [pytest.mark.integration]

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "regulatory"


class TestShippedCsvs:
    def test_svhc_csv_parses(self) -> None:
        entries = load_svhc_from_csv(DATA_DIR / "reach_svhc.csv")
        assert len(entries) >= 40, f"expected 40+ SVHC entries, got {len(entries)}"
        cas_values = {e.cas_number for e in entries}
        assert "117-81-7" in cas_values  # DEHP
        assert "7439-92-1" in cas_values  # Lead

    def test_annex_xvii_csv_parses(self) -> None:
        entries = load_annex_xvii_from_csv(DATA_DIR / "reach_annex_xvii.csv")
        assert len(entries) >= 25
        lead = next(e for e in entries if e.cas_number == "7439-92-1")
        assert lead.max_concentration_percent == pytest.approx(0.03)
        arsenic = next(e for e in entries if e.cas_number == "7440-38-2")
        assert arsenic.max_concentration_percent == pytest.approx(0.0)

    def test_build_checker_lists_have_expected_totals(self) -> None:
        checker = build_checker_from_data_dir(DATA_DIR)
        # The checker doesn't expose the sizes directly, but we can
        # verify via a synthetic recipe that lookup works.
        from formulation_workbench.domain.entities.recipe import (
            Component,
            CompositionStage,
            ProcessParams,
            ProductClass,
            Recipe,
        )
        from formulation_workbench.domain.value_objects.citation import Citation
        from formulation_workbench.domain.value_objects.functions import ComponentFunction
        from formulation_workbench.domain.value_objects.isbn import Isbn

        cite = Citation(
            authors="Flick",
            title="WBPF",
            year=1995,
            publisher="Noyes Publications",
            isbn=Isbn("9780815513773"),
        )
        recipe = Recipe(
            category="Краски",
            subcategory="Водно-дисперсионные",
            binder_type="Acrylic",
            product_class=ProductClass.STANDARD,
            intended_use="Test",
            stages=(
                CompositionStage(
                    stage_number=1,
                    name="Mix",
                    description="",
                    components=(
                        Component(
                            name="Water",
                            cas_number="7732-18-5",
                            function="vehicle",
                            mass_percent=60.0,
                            functional_role=ComponentFunction.VEHICLE,
                        ),
                        Component(
                            name="Nickel salt",
                            cas_number="7440-02-0",
                            function="anticorrosive_pigment",
                            mass_percent=0.1,
                            functional_role=ComponentFunction.ANTICORROSIVE_PIGMENT,
                        ),
                        Component(
                            name="Acrylic",
                            cas_number="mixture",
                            function="binder",
                            mass_percent=39.9,
                            functional_role=ComponentFunction.BINDER,
                        ),
                    ),
                    process=ProcessParams(equipment="Disperser"),
                ),
            ),
            primary_source=cite,
        )
        findings = checker.check(recipe)
        # Nickel is on the SVHC candidate list — expect a warning.
        assert any(f.substance == "Nickel" for f in findings)


class TestMalformedInputs:
    def test_missing_file_raises(self) -> None:
        with pytest.raises(RegulatoryDataError):
            load_svhc_from_csv(Path("/nonexistent/path.csv"))

    def test_annex_xvii_blank_limit_treated_as_ban(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "annex.csv"
        csv_file.write_text(
            "cas_number,name,max_concentration_percent,scope,reference\n"
            "111-11-1,TestBanned,,general,internal\n",
            encoding="utf-8",
        )
        entries = load_annex_xvii_from_csv(csv_file)
        assert len(entries) == 1
        assert entries[0].max_concentration_percent is None

    def test_comment_lines_ignored(self, tmp_path: Path) -> None:
        csv_file = tmp_path / "svhc.csv"
        csv_file.write_text(
            "# comment header\ncas_number,name,reference\n222-22-2,TestSVHC,ECHA test\n",
            encoding="utf-8",
        )
        entries = load_svhc_from_csv(csv_file)
        assert len(entries) == 1
        assert entries[0].name == "TestSVHC"
