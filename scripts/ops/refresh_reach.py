"""Refresh the shipped REACH SVHC + Annex XVII CSV snapshots.

Sources:
    - ECHA SVHC candidate list  — https://echa.europa.eu/candidate-list-table
    - REACH Annex XVII           — https://echa.europa.eu/substances-restricted-under-reach

ECHA publishes both as HTML tables and as downloadable XLSX/CSV
exports.  The exact download URL rotates every so often, so this script
takes the *user-supplied* URLs as arguments — that keeps the code
resilient to ECHA URL migrations and makes the refresh reviewable
(the operator sees exactly what was fetched).

Usage
-----
    # Local file (already downloaded via a browser):
    python scripts/ops/refresh_reach.py \\
        --svhc-source /tmp/echa_svhc.xlsx \\
        --annex-source /tmp/echa_annex_xvii.xlsx

    # HTTPS URLs (adds ``urllib.request`` fetch step):
    python scripts/ops/refresh_reach.py \\
        --svhc-source https://echa.europa.eu/documents/…/svhc.xlsx \\
        --annex-source https://echa.europa.eu/documents/…/annex_xvii.xlsx

The script:
    1. Fetches / opens the source files.
    2. Extracts a canonical shape (cas, name, scope, limit, reference).
    3. Writes ``data/regulatory/reach_svhc.csv`` and
       ``data/regulatory/reach_annex_xvii.csv``.
    4. Prints a summary and — when running inside a git working tree —
       shows ``git diff --stat`` so the operator can eyeball the delta
       before committing.

Supported input formats: ``.csv``, ``.xlsx``, ``.tsv``.  The XLSX path
requires ``openpyxl`` (already a runtime dependency).

This script is deliberately *idempotent*: rerunning with the same input
yields byte-identical output.
"""

from __future__ import annotations

import argparse
import csv
import io
import logging
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "regulatory"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("refresh_reach")


CAS_PATTERN = re.compile(r"\b\d{2,7}-\d{2}-\d\b")


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------
def _fetch(source: str) -> tuple[bytes, str]:
    """Return ``(bytes, extension)`` for a URL or a local file path."""
    if source.startswith(("http://", "https://")):
        logger.info("downloading %s", source)
        with urllib.request.urlopen(source, timeout=60) as resp:  # noqa: S310 — CLI tool
            data = resp.read()
        ext = Path(urllib.request.url2pathname(source)).suffix.lower()
        return data, ext
    path = Path(source).expanduser()
    return path.read_bytes(), path.suffix.lower()


def _iter_rows(data: bytes, ext: str) -> list[dict[str, str]]:
    if ext in {".csv", ".tsv", ""}:
        text = data.decode("utf-8", errors="replace")
        dialect = csv.excel_tab if ext == ".tsv" else csv.excel
        return list(csv.DictReader(io.StringIO(text), dialect=dialect))
    if ext == ".xlsx":
        try:
            from openpyxl import load_workbook
        except ImportError as exc:
            raise SystemExit(
                "openpyxl required to read xlsx sources; pip install openpyxl"
            ) from exc
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.active
        if ws is None:
            return []
        rows_iter = ws.iter_rows(values_only=True)
        try:
            header = [str(c or "").strip() for c in next(rows_iter)]
        except StopIteration:
            return []
        result: list[dict[str, str]] = []
        for row in rows_iter:
            record: dict[str, str] = {}
            for idx, cell in enumerate(row):
                if idx >= len(header):
                    break
                record[header[idx]] = "" if cell is None else str(cell).strip()
            result.append(record)
        return result
    raise SystemExit(f"Unsupported extension: {ext}")


# ---------------------------------------------------------------------------
# Field mapping helpers — tolerant of ECHA column-name churn.
# ---------------------------------------------------------------------------
def _pick(row: dict[str, str], *candidates: str) -> str:
    lower = {k.lower(): v for k, v in row.items()}
    for cand in candidates:
        for key in lower:
            if cand.lower() in key:
                return lower[key].strip()
    return ""


def _canonical_svhc(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for row in rows:
        cas = _pick(row, "cas", "cas rn", "cas number") or _first_cas_in_dict(row)
        name = _pick(row, "substance name", "name")
        reference = _pick(row, "reason", "date", "reference", "inclusion date")
        if not cas or not name:
            continue
        # De-duplicate multiple CAS numbers per row.
        for cas_candidate in _split_cas(cas):
            result.append(
                {"cas_number": cas_candidate, "name": name, "reference": reference or "ECHA candidate list"}
            )
    return result


def _canonical_annex_xvii(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for row in rows:
        cas = _pick(row, "cas", "cas rn", "cas number") or _first_cas_in_dict(row)
        name = _pick(row, "substance name", "name")
        limit_raw = _pick(row, "limit", "concentration", "threshold")
        reference = _pick(row, "entry", "reference") or "REACH Annex XVII"
        scope = _pick(row, "scope") or "general"
        if not cas or not name:
            continue
        limit = _parse_limit(limit_raw)
        for cas_candidate in _split_cas(cas):
            result.append(
                {
                    "cas_number": cas_candidate,
                    "name": name,
                    "max_concentration_percent": "" if limit is None else str(limit),
                    "scope": scope,
                    "reference": reference,
                }
            )
    return result


def _first_cas_in_dict(row: dict[str, str]) -> str:
    for value in row.values():
        m = CAS_PATTERN.search(value or "")
        if m:
            return m.group(0)
    return ""


def _split_cas(value: str) -> list[str]:
    matches = CAS_PATTERN.findall(value)
    return matches or ([value] if value else [])


_PERCENT_PATTERN = re.compile(r"([\d.]+)\s*%")


def _parse_limit(raw: str) -> float | None:
    if not raw:
        return None
    m = _PERCENT_PATTERN.search(raw)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------
_SVHC_HEADER = ["cas_number", "name", "reference"]
_ANNEX_HEADER = ["cas_number", "name", "max_concentration_percent", "scope", "reference"]


def _write_csv(path: Path, header: list[str], rows: list[dict[str, str]], banner: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    seen: set[tuple[str, ...]] = set()
    unique_rows: list[dict[str, str]] = []
    for row in rows:
        key = tuple(row.get(h, "") for h in header)
        if key in seen:
            continue
        seen.add(key)
        unique_rows.append(row)
    unique_rows.sort(key=lambda r: (r.get("cas_number", ""), r.get("name", "")))
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write(banner)
        writer = csv.DictWriter(fh, fieldnames=header)
        writer.writeheader()
        writer.writerows(unique_rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--svhc-source", help="Path or URL of the SVHC candidate-list export")
    parser.add_argument(
        "--annex-source", help="Path or URL of the REACH Annex XVII export"
    )
    parser.add_argument(
        "--output-dir", default=str(DATA_DIR), help="Where to write the refreshed CSVs"
    )
    parser.add_argument(
        "--diff", action="store_true", help="Print `git diff --stat` on the output files"
    )
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir)
    updated: list[Path] = []

    if args.svhc_source:
        data, ext = _fetch(args.svhc_source)
        rows = _canonical_svhc(_iter_rows(data, ext))
        target = output_dir / "reach_svhc.csv"
        _write_csv(
            target,
            _SVHC_HEADER,
            rows,
            banner=(
                "# Refreshed ECHA SVHC candidate list.\n"
                f"# Source: {args.svhc_source}\n"
                f"# Rows: {len(rows)}\n"
            ),
        )
        updated.append(target)
        logger.info("wrote %d SVHC entries to %s", len(rows), target)

    if args.annex_source:
        data, ext = _fetch(args.annex_source)
        rows = _canonical_annex_xvii(_iter_rows(data, ext))
        target = output_dir / "reach_annex_xvii.csv"
        _write_csv(
            target,
            _ANNEX_HEADER,
            rows,
            banner=(
                "# Refreshed REACH Annex XVII list.\n"
                f"# Source: {args.annex_source}\n"
                f"# Rows: {len(rows)}\n"
            ),
        )
        updated.append(target)
        logger.info("wrote %d Annex XVII entries to %s", len(rows), target)

    if not updated:
        parser.error("nothing to do — supply at least --svhc-source or --annex-source")

    if args.diff:
        try:
            subprocess.run(  # noqa: S603 — CLI-supplied paths, no shell
                ["git", "diff", "--stat", *[str(p) for p in updated]],
                cwd=REPO_ROOT,
                check=False,
            )
        except FileNotFoundError:
            logger.warning("git not available; skipping --diff output")
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI entry point
    raise SystemExit(main(sys.argv[1:]))
