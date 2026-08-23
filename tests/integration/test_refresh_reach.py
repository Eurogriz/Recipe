"""ETL sanity tests for scripts/ops/refresh_reach.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration]

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "ops" / "refresh_reach.py"


def _load_module():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("refresh_reach", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_canonical_svhc_extracts_cas(tmp_path: Path) -> None:
    mod = _load_module()
    rows = mod._canonical_svhc(
        [
            {"CAS Number": "117-81-7", "Substance Name": "DEHP", "Inclusion Date": "2008"},
            {"cas rn": "84-74-2", "name": "DBP", "reason for inclusion": "toxic to reproduction"},
        ]
    )
    assert {r["cas_number"] for r in rows} == {"117-81-7", "84-74-2"}
    assert any(r["name"] == "DEHP" for r in rows)


def test_canonical_annex_xvii_parses_limits() -> None:
    mod = _load_module()
    rows = mod._canonical_annex_xvii(
        [
            {"CAS": "7439-92-1", "Substance name": "Lead", "Limit": "0.03 %", "Scope": "general"},
            {"cas": "7440-38-2", "name": "Arsenic", "Concentration": "banned", "scope": "general"},
        ]
    )
    lead = next(r for r in rows if r["cas_number"] == "7439-92-1")
    assert lead["max_concentration_percent"] == "0.03"
    arsenic = next(r for r in rows if r["cas_number"] == "7440-38-2")
    assert arsenic["max_concentration_percent"] == ""


def test_write_csv_is_deterministic(tmp_path: Path) -> None:
    mod = _load_module()
    rows = [
        {"cas_number": "222-22-2", "name": "B", "reference": "x"},
        {"cas_number": "111-11-1", "name": "A", "reference": "x"},
    ]
    target = tmp_path / "svhc.csv"
    mod._write_csv(target, mod._SVHC_HEADER, rows, banner="# test\n")
    first = target.read_text(encoding="utf-8")
    mod._write_csv(target, mod._SVHC_HEADER, rows, banner="# test\n")
    second = target.read_text(encoding="utf-8")
    assert first == second  # idempotent
    # Rows must be sorted by cas_number.
    body = "\n".join(first.splitlines()[2:])  # skip banner + header
    assert body.index("111-11-1") < body.index("222-22-2")


def test_parse_limit_extracts_percent() -> None:
    mod = _load_module()
    assert mod._parse_limit("0.03 %") == 0.03
    assert mod._parse_limit("<= 0.1%") == 0.1
    assert mod._parse_limit("banned") is None
    assert mod._parse_limit("") is None
