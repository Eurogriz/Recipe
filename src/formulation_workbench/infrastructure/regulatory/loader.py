"""CSV loader for the REACH SVHC + Annex XVII reference tables.

Public entry points:

- :func:`load_svhc_from_csv`         — returns ``tuple[SubstanceRestriction, ...]``
- :func:`load_annex_xvii_from_csv`   — same shape, but rows with a
  ``max_concentration_percent`` cell may be blank (``None``) meaning
  "outright ban".
- :func:`build_checker_from_data_dir` — combines both into a ready-to-use
  :class:`RegulatoryComplianceChecker`.

The CSVs are shipped under ``data/regulatory/`` in the repository; a
production deployment can override the path via
``FW_REGULATORY_DATA_DIR``.  Comment lines that start with ``#`` and
empty lines are ignored, so operators can safely maintain the files by
hand.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from ...domain.services.regulatory import (
    RegulatoryComplianceChecker,
    SubstanceRestriction,
)

logger = logging.getLogger(__name__)


class RegulatoryDataError(Exception):
    """Raised when a CSV file is malformed or unreadable."""


def _iter_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise RegulatoryDataError(f"Regulatory data file not found: {path}")
    with path.open("r", encoding="utf-8", newline="") as fh:
        raw_lines = [ln for ln in fh if ln.strip() and not ln.lstrip().startswith("#")]
    if not raw_lines:
        return []
    reader = csv.DictReader(raw_lines)
    return list(reader)


def _clean_cas(value: str) -> str:
    return (value or "").strip()


def _optional_float(value: str) -> float | None:
    v = (value or "").strip()
    if v == "" or v.lower() in {"none", "null", "n/a"}:
        return None
    try:
        return float(v)
    except ValueError as exc:
        raise RegulatoryDataError(f"invalid float value {value!r}") from exc


def load_svhc_from_csv(path: Path) -> tuple[SubstanceRestriction, ...]:
    """Parse the ECHA SVHC candidate-list CSV."""
    rows = _iter_rows(path)
    entries: list[SubstanceRestriction] = []
    for row in rows:
        cas = _clean_cas(row.get("cas_number", ""))
        name = (row.get("name") or "").strip()
        reference = (row.get("reference") or "").strip()
        if not cas or not name:
            logger.warning("skipping malformed SVHC row: %s", row)
            continue
        entries.append(
            SubstanceRestriction(
                cas_number=cas,
                name=name,
                max_concentration_percent=None,  # SVHC = information duty, not a limit
                scope="general",
                reference=reference,
            )
        )
    return tuple(entries)


def load_annex_xvii_from_csv(path: Path) -> tuple[SubstanceRestriction, ...]:
    """Parse the REACH Annex XVII CSV."""
    rows = _iter_rows(path)
    entries: list[SubstanceRestriction] = []
    for row in rows:
        cas = _clean_cas(row.get("cas_number", ""))
        name = (row.get("name") or "").strip()
        reference = (row.get("reference") or "").strip()
        scope = (row.get("scope") or "general").strip() or "general"
        try:
            limit = _optional_float(row.get("max_concentration_percent", ""))
        except RegulatoryDataError as exc:
            logger.warning("skipping Annex XVII row %s: %s", row, exc)
            continue
        if not cas or not name:
            logger.warning("skipping malformed Annex XVII row: %s", row)
            continue
        entries.append(
            SubstanceRestriction(
                cas_number=cas,
                name=name,
                max_concentration_percent=limit,
                scope=scope,
                reference=reference,
            )
        )
    return tuple(entries)


def build_checker_from_data_dir(
    data_dir: Path,
    *,
    svhc_filename: str = "reach_svhc.csv",
    annex_filename: str = "reach_annex_xvii.csv",
) -> RegulatoryComplianceChecker:
    """Load both CSVs and return a ready-to-use compliance checker."""
    svhc_path = data_dir / svhc_filename
    annex_path = data_dir / annex_filename
    svhc = load_svhc_from_csv(svhc_path)
    annex = load_annex_xvii_from_csv(annex_path)
    logger.info(
        "regulatory_data_loaded",
        extra={
            "svhc_entries": len(svhc),
            "annex_xvii_entries": len(annex),
            "data_dir": str(data_dir),
        },
    )
    return RegulatoryComplianceChecker(svhc_list=svhc, annex_xvii_list=annex)


__all__ = [
    "RegulatoryDataError",
    "build_checker_from_data_dir",
    "load_annex_xvii_from_csv",
    "load_svhc_from_csv",
]
