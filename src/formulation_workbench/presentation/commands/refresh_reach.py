"""``formulation-refresh-reach`` — install REACH SVHC + Annex XVII CSVs.

Two operating modes:

1. **Snapshot mode** (default, no flags): dumps the compiled-in
   ``_SVHC_CANDIDATES`` and ``_ANNEX_XVII`` tables from
   :mod:`formulation_workbench.domain.services.regulatory` into
   ``FW_REGULATORY_DATA_DIR/reach_svhc.csv`` and
   ``FW_REGULATORY_DATA_DIR/reach_annex_xvii.csv``.

   Purpose: unblock a fresh installation whose logs are full of
   ``regulatory_csv_unavailable`` — instead of hunting down an ECHA
   download and running the (bigger) ``scripts/ops/refresh_reach.py``
   wrapper, one command drops a working — if conservative — snapshot
   into place.

2. **Fetch mode** (``--svhc-source`` and/or ``--annex-source``):
   delegates to the wrapper script (``scripts/ops/refresh_reach.py``)
   for the real ECHA XLSX/CSV parse.  Same CSV format on disk so
   downstream code doesn't care which mode wrote it.

Reads ``FW_REGULATORY_DATA_DIR`` from the environment so a staging
deploy can install the same seed into a per-env path.

Flags::

    --svhc-source PATH      Fetch SVHC list from URL/file (delegates
                            to scripts/ops/refresh_reach.py).
    --annex-source PATH     Same, for Annex XVII.
    --output-dir PATH       Override FW_REGULATORY_DATA_DIR.
    --force                 Overwrite existing CSVs (default: refuse
                            when target already exists).
    --json                  Emit a machine-readable summary.

Exit codes:
    0 — files written (or already present without --force).
    1 — user error (bad flag, source not readable).
    2 — refused to overwrite existing files (add --force).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from ...domain.services.regulatory import (
    _ANNEX_XVII,
    _SVHC_CANDIDATES,
    SubstanceRestriction,
)
from ...infrastructure.config import get_settings
from ...infrastructure.logging.setup import setup_logging

logger = logging.getLogger(__name__)


# Header columns must match ``infrastructure.regulatory.loader`` which
# reads ``cas_number`` (not ``cas``) — otherwise every row would be
# logged as "malformed" and silently dropped.
_SVHC_HEADER = ("cas_number", "name", "reference", "notes")
_ANNEX_HEADER = (
    "cas_number",
    "name",
    "scope",
    "max_concentration_percent",
    "reference",
    "notes",
)


@dataclass(frozen=True, slots=True)
class WriteReport:
    """What actually landed on disk after this call."""

    svhc_path: str
    svhc_rows: int
    svhc_written: bool
    annex_path: str
    annex_rows: int
    annex_written: bool
    source: str  # "snapshot" | "fetch"


# --------------------------------------------------------------------------- writers


def _write_svhc(path: Path, rows: tuple[SubstanceRestriction, ...]) -> None:
    """Write the SVHC list as a stable, sorted-by-CAS CSV."""
    ordered = sorted(rows, key=lambda r: r.cas_number)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(_SVHC_HEADER)
        for r in ordered:
            writer.writerow((r.cas_number, r.name, r.reference or "", ""))


def _write_annex(path: Path, rows: tuple[SubstanceRestriction, ...]) -> None:
    """Write Annex XVII entries, preserving the numeric fields."""
    ordered = sorted(rows, key=lambda r: (r.cas_number, r.scope or ""))
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(_ANNEX_HEADER)
        for r in ordered:
            writer.writerow(
                (
                    r.cas_number,
                    r.name,
                    r.scope or "general",
                    (
                        f"{r.max_concentration_percent:.6g}"
                        if r.max_concentration_percent is not None
                        else ""
                    ),
                    r.reference or "",
                    "",
                )
            )


# --------------------------------------------------------------------------- actions


def _snapshot(
    *,
    output_dir: Path,
    force: bool,
) -> WriteReport:
    """Dump the built-in snapshot to ``output_dir``.

    Existing files are left alone unless ``force`` is set — the CLI
    surfaces an error in that case rather than silently keeping a
    stale copy.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    svhc_path = output_dir / "reach_svhc.csv"
    annex_path = output_dir / "reach_annex_xvii.csv"

    svhc_written = False
    annex_written = False

    if svhc_path.exists() and not force:
        logger.warning(
            "svhc file already exists, keeping current copy (pass --force to overwrite): %s",
            svhc_path,
        )
    else:
        _write_svhc(svhc_path, _SVHC_CANDIDATES)
        svhc_written = True
        logger.info("wrote %s (%d rows)", svhc_path, len(_SVHC_CANDIDATES))

    if annex_path.exists() and not force:
        logger.warning(
            "annex file already exists, keeping current copy (pass --force to overwrite): %s",
            annex_path,
        )
    else:
        _write_annex(annex_path, _ANNEX_XVII)
        annex_written = True
        logger.info("wrote %s (%d rows)", annex_path, len(_ANNEX_XVII))

    return WriteReport(
        svhc_path=str(svhc_path),
        svhc_rows=len(_SVHC_CANDIDATES),
        svhc_written=svhc_written,
        annex_path=str(annex_path),
        annex_rows=len(_ANNEX_XVII),
        annex_written=annex_written,
        source="snapshot",
    )


def _fetch_via_ops_script(
    *,
    svhc_source: str | None,
    annex_source: str | None,
    output_dir: Path,
) -> WriteReport:
    """Delegate to the operations wrapper for real ECHA parsing.

    Kept out-of-process so a stale/broken ``openpyxl`` at the operator
    site cannot take the CLI import path down with it.  Any failure
    in the child process bubbles up as a non-zero exit.
    """
    import subprocess  # local import — keeps startup fast for snapshot mode

    script_path = _find_ops_script()
    if script_path is None:
        raise FileNotFoundError(
            "cannot find scripts/ops/refresh_reach.py; either run from a "
            "checkout or use snapshot mode (no --*-source flags)"
        )

    cmd = [sys.executable, str(script_path)]
    if svhc_source:
        cmd += ["--svhc-source", svhc_source]
    if annex_source:
        cmd += ["--annex-source", annex_source]
    cmd += ["--output-dir", str(output_dir)]

    logger.info("delegating to ops script: %s", " ".join(cmd))
    # We do NOT swallow the exit code — the wrapper prints its own
    # summary + git-diff, which is exactly what the operator wants.
    subprocess.check_call(cmd)  # noqa: S603 — argv is fully controlled

    # After the child finishes we count the rows on disk so the JSON
    # summary is consistent with snapshot mode.
    svhc_path = output_dir / "reach_svhc.csv"
    annex_path = output_dir / "reach_annex_xvii.csv"
    svhc_rows = _count_data_rows(svhc_path)
    annex_rows = _count_data_rows(annex_path)
    return WriteReport(
        svhc_path=str(svhc_path),
        svhc_rows=svhc_rows,
        svhc_written=svhc_source is not None,
        annex_path=str(annex_path),
        annex_rows=annex_rows,
        annex_written=annex_source is not None,
        source="fetch",
    )


def _find_ops_script() -> Path | None:
    """Search a small set of likely locations for the ops wrapper.

    - When running from a source checkout: ``../scripts/ops/refresh_reach.py``.
    - When installed as a wheel: the script isn't shipped, so we
      return ``None`` and let the caller fall back to snapshot mode.
    """
    here = Path(__file__).resolve()
    for candidate in (
        here.parents[4] / "scripts" / "ops" / "refresh_reach.py",
        here.parents[3] / "scripts" / "ops" / "refresh_reach.py",
        Path.cwd() / "scripts" / "ops" / "refresh_reach.py",
    ):
        if candidate.is_file():
            return candidate
    return None


def _count_data_rows(path: Path) -> int:
    if not path.is_file():
        return 0
    with path.open("r", encoding="utf-8", newline="") as fh:
        # Subtract 1 for the header row; handle a truly empty file
        # gracefully.
        total = sum(1 for _ in fh)
    return max(0, total - 1)


# --------------------------------------------------------------------------- CLI


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="formulation-refresh-reach",
        description=(
            "Install REACH SVHC + Annex XVII CSVs into "
            "FW_REGULATORY_DATA_DIR (default: ./data/regulatory).  "
            "Runs in snapshot mode by default — pass --svhc-source / "
            "--annex-source for a real ECHA fetch."
        ),
    )
    parser.add_argument(
        "--svhc-source",
        default=None,
        help=(
            "URL or path to an ECHA SVHC candidate list export "
            "(.csv/.xlsx/.tsv).  When omitted, dumps the compiled-in "
            "snapshot instead."
        ),
    )
    parser.add_argument(
        "--annex-source",
        default=None,
        help="URL or path to an ECHA Annex XVII export.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Override FW_REGULATORY_DATA_DIR.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Overwrite existing CSVs instead of keeping the current "
            "copy.  Snapshot-mode-only — fetch mode always overwrites."
        ),
    )
    parser.add_argument(
        "--json",
        dest="emit_json",
        action="store_true",
        help="Emit a JSON summary on stdout.",
    )
    return parser


async def _main_async(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    settings = get_settings()
    setup_logging(log_level=settings.log_level, json_logs=False)

    output_dir = args.output_dir or settings.regulatory_data_dir
    output_dir = Path(output_dir).expanduser().resolve()

    is_fetch_mode = args.svhc_source is not None or args.annex_source is not None

    try:
        if is_fetch_mode:
            report = _fetch_via_ops_script(
                svhc_source=args.svhc_source,
                annex_source=args.annex_source,
                output_dir=output_dir,
            )
        else:
            svhc_path = output_dir / "reach_svhc.csv"
            annex_path = output_dir / "reach_annex_xvii.csv"
            if not args.force and svhc_path.exists() and annex_path.exists():
                logger.error(
                    "both files already exist (%s, %s); pass --force to overwrite",
                    svhc_path,
                    annex_path,
                )
                return 2
            report = _snapshot(output_dir=output_dir, force=args.force)
    except FileNotFoundError as exc:
        logger.error(str(exc))
        return 1
    except Exception as exc:  # pragma: no cover — depends on env
        logger.error("refresh failed: %s", exc)
        return 1

    if args.emit_json:
        print(json.dumps(asdict(report), indent=2, ensure_ascii=False))
    else:
        print(
            f"mode={report.source}  "
            f"svhc={report.svhc_rows} rows @ {report.svhc_path}  "
            f"annex={report.annex_rows} rows @ {report.annex_path}"
        )

    return 0


def main(argv: list[str] | None = None) -> int:
    """Sync entry point for the console script."""
    return asyncio.run(_main_async(argv))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["WriteReport", "_main_async", "main"]
