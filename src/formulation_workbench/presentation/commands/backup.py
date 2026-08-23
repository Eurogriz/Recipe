"""``formulation-backup`` — create, restore, verify and rotate SQLite backups.

Uses SQLite's online backup API via ``VACUUM INTO`` (safe against
concurrent writers) and produces a compressed archive suitable for
offsite storage.  Backups are transparent to SQLCipher: the destination
file inherits the same encryption key as the source.

Subcommands
-----------

- ``backup``   Create an online-consistent copy (default: gzipped +
               SHA-256 sidecar).
- ``restore``  Copy a ``.db`` / ``.db.gz`` archive back into place.
               Refuses to clobber unless ``--force`` is set.
- ``verify``   Check an archive's SHA-256 matches its sidecar AND run
               ``PRAGMA integrity_check`` on the decompressed content.
               A production runbook should call this on the tail of
               every backup script — a bit-flipped tarball is not a
               backup, it's a fiction.
- ``list``     Human/JSON summary of every backup in ``--dir``: name,
               age, size, whether the sidecar checksum matches.
- ``prune``    Rotate: keep the N most recent backups, delete the
               rest.  Optionally filter by age.  Dry-run supported.

Exit codes
    0 — success
    1 — user error (bad path, missing file, unreadable archive)
    2 — refuse to clobber destination (add --force)
    3 — verification failed (checksum mismatch or integrity_check
        surfaced ``ok`` != true)
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
import shutil
import sqlite3
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ...infrastructure.config import get_settings
from ...infrastructure.logging.setup import setup_logging

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- helpers


def _sqlite_path_from_url(url: str) -> Path:
    """Extract the on-disk path from a ``sqlite+aiosqlite:///…`` URL."""
    if not url.startswith("sqlite"):
        raise ValueError(f"Only SQLite URLs are supported for backup, got {url!r}")
    _, _, remainder = url.partition("///")
    if not remainder:
        raise ValueError(f"Could not resolve DB path from URL {url!r}")
    return Path(remainder)


def _sha256(path: Path) -> str:
    """Streaming SHA-256 hex digest — safe for multi-GB archives."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_sidecar_checksum(sidecar: Path) -> str | None:
    """Read the first hex token from a ``coreutils`` sha256sum-style file."""
    if not sidecar.is_file():
        return None
    try:
        text = sidecar.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text:
        return None
    # Format: "<hex>  <filename>" — mirrors what ``sha256sum`` writes.
    return text.split()[0].lower()


def _write_sidecar(archive: Path) -> str:
    """Compute and persist the SHA-256 sidecar next to an archive."""
    digest = _sha256(archive)
    sidecar = archive.with_suffix(archive.suffix + ".sha256")
    sidecar.write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    return digest


# --------------------------------------------------------------------------- backup / restore


def backup(db_path: Path, output: Path, compress: bool = True) -> Path:
    """Create an online-consistent copy of ``db_path`` at ``output``.

    Returns the path of the produced artefact (``output`` itself if
    ``compress=False``, else ``output.gz``).
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Database file does not exist: {db_path}")
    output.parent.mkdir(parents=True, exist_ok=True)

    # ``VACUUM INTO`` is atomic-per-database: SQLite acquires a shared
    # read lock long enough to snapshot the whole file, then releases
    # it.  Writers see no interruption longer than a checkpoint.
    tmp = output.with_suffix(output.suffix + ".partial")
    with sqlite3.connect(db_path) as conn:
        conn.execute("VACUUM INTO ?", (str(tmp),))
    tmp.replace(output)

    if compress:
        gz_path = output.with_suffix(output.suffix + ".gz")
        with output.open("rb") as src, gzip.open(gz_path, "wb", compresslevel=6) as dst:
            shutil.copyfileobj(src, dst)
        output.unlink()
        checksum = _write_sidecar(gz_path)
        logger.info(
            "backup_completed",
            extra={
                "source": str(db_path),
                "destination": str(gz_path),
                "sha256": checksum,
            },
        )
        return gz_path

    checksum = _write_sidecar(output)
    logger.info(
        "backup_completed",
        extra={
            "source": str(db_path),
            "destination": str(output),
            "sha256": checksum,
        },
    )
    return output


def restore(archive: Path, db_path: Path, *, force: bool = False) -> Path:
    """Restore a backup archive to ``db_path``.

    ``archive`` may be a plain ``.db`` file or a ``.db.gz`` file.  If
    the destination exists, ``force=True`` is required to overwrite.
    """
    if not archive.exists():
        raise FileNotFoundError(f"Backup archive not found: {archive}")

    if db_path.exists() and not force:
        raise FileExistsError(f"Destination exists and --force not given: {db_path}")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    if archive.suffix == ".gz":
        with gzip.open(archive, "rb") as src, db_path.open("wb") as dst:
            shutil.copyfileobj(src, dst)
    else:
        shutil.copyfile(archive, db_path)

    logger.info(
        "restore_completed",
        extra={"source": str(archive), "destination": str(db_path)},
    )
    return db_path


# --------------------------------------------------------------------------- verify / list / prune


@dataclass(frozen=True, slots=True)
class VerifyReport:
    """Structured result of a ``verify`` call."""

    archive: str
    checksum_expected: str | None
    checksum_actual: str
    checksum_ok: bool
    integrity_ok: bool
    integrity_message: str


def verify(archive: Path) -> VerifyReport:
    """Verify an archive is bit-identical to its sidecar AND that
    ``PRAGMA integrity_check`` still reports ``ok`` after decompression.

    A production runbook calls this immediately after ``backup`` — a
    bit-flipped tarball is not a backup, it's a fiction that quietly
    survives until you actually need it.
    """
    if not archive.is_file():
        raise FileNotFoundError(f"Archive not found: {archive}")

    actual = _sha256(archive)
    sidecar = archive.with_suffix(archive.suffix + ".sha256")
    expected = _read_sidecar_checksum(sidecar)
    checksum_ok = expected is not None and expected.lower() == actual.lower()

    # Decompress to a temp file for the integrity check.  Keeping the
    # decompressed image in memory is fine at v1 scale (~50 MB) but
    # a spool file is future-proof — SQLite refuses to open in-memory
    # blobs directly.
    with tempfile.TemporaryDirectory(prefix="fw-verify-") as tmp:
        db_tmp = Path(tmp) / "restored.db"
        integrity_ok = False
        integrity_message = ""
        try:
            if archive.suffix == ".gz":
                # ``gzip.BadGzipFile`` (subclass of OSError) fires when
                # the CRC/size in the gzip footer disagrees with the
                # decoded stream — i.e. someone tampered with the
                # archive.  Treat as "cannot decompress" without
                # crashing verify itself.
                with gzip.open(archive, "rb") as src, db_tmp.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
            else:
                shutil.copyfile(archive, db_tmp)
        except (gzip.BadGzipFile, OSError, EOFError) as exc:
            integrity_message = f"cannot decompress: {exc}"
        else:
            try:
                with sqlite3.connect(f"file:{db_tmp}?mode=ro", uri=True) as conn:
                    # ``integrity_check`` returns "ok" when the file
                    # is consistent; anything else lists the problems
                    # (one row per issue).  We collapse to the first
                    # row for a short log line.
                    row = conn.execute("PRAGMA integrity_check").fetchone()
                integrity_message = str(row[0]) if row else "no rows"
                integrity_ok = integrity_message == "ok"
            except sqlite3.DatabaseError as exc:
                integrity_message = f"cannot open as SQLite: {exc}"

    return VerifyReport(
        archive=str(archive),
        checksum_expected=expected,
        checksum_actual=actual,
        checksum_ok=checksum_ok,
        integrity_ok=integrity_ok,
        integrity_message=integrity_message,
    )


@dataclass(frozen=True, slots=True)
class BackupInfo:
    """One row of the ``list`` subcommand — one archive per record."""

    path: str
    size_bytes: int
    modified_at: str  # ISO-8601 UTC
    checksum_present: bool
    checksum_matches: bool | None


def _iter_backups(directory: Path) -> list[Path]:
    """Return every ``*.db`` and ``*.db.gz`` file in ``directory``."""
    if not directory.is_dir():
        return []
    seen: list[Path] = []
    # Sorted newest-first so ``list``/``prune`` produce a stable
    # ordering regardless of filesystem enumeration quirks.
    for p in sorted(
        directory.iterdir(),
        key=lambda x: x.stat().st_mtime if x.exists() else 0,
        reverse=True,
    ):
        if (p.suffix == ".gz" and p.stem.endswith(".db")) or p.suffix == ".db":
            seen.append(p)
    return seen


def list_backups(directory: Path) -> list[BackupInfo]:
    """Return metadata for every backup archive in ``directory``.

    Sidecar files (``*.sha256``) are read but never returned as
    top-level rows — they're an implementation detail.
    """
    rows: list[BackupInfo] = []
    for p in _iter_backups(directory):
        sidecar = p.with_suffix(p.suffix + ".sha256")
        expected = _read_sidecar_checksum(sidecar)
        checksum_matches: bool | None = (
            None if expected is None else _sha256(p).lower() == expected.lower()
        )
        stat = p.stat()
        rows.append(
            BackupInfo(
                path=str(p),
                size_bytes=stat.st_size,
                modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(
                    timespec="seconds"
                ),
                checksum_present=sidecar.exists(),
                checksum_matches=checksum_matches,
            )
        )
    return rows


@dataclass(frozen=True, slots=True)
class PruneReport:
    """Result of ``prune`` — which files went, which stayed."""

    deleted: list[str]
    kept: list[str]
    dry_run: bool


def prune(
    directory: Path,
    *,
    keep: int | None,
    older_than_days: int | None,
    dry_run: bool = False,
) -> PruneReport:
    """Rotate old backups.

    Rules (applied in this order):

    - When ``keep`` is set: retain the ``keep`` most recent archives,
      delete the rest.
    - When ``older_than_days`` is set: delete any archive whose mtime
      is older than the cutoff.  Combines with ``keep`` — an archive
      must survive BOTH filters to be kept.
    """
    archives = _iter_backups(directory)  # newest first
    to_delete: list[Path] = []
    to_keep: list[Path] = []

    cutoff: datetime | None = None
    if older_than_days is not None:
        if older_than_days < 0:
            raise ValueError("--older-than-days must be non-negative")
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=older_than_days)

    for i, archive in enumerate(archives):
        exceeds_keep = keep is not None and i >= keep
        stat = archive.stat()
        mtime_utc = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        exceeds_age = cutoff is not None and mtime_utc < cutoff
        if exceeds_keep or exceeds_age:
            to_delete.append(archive)
        else:
            to_keep.append(archive)

    if not dry_run:
        for archive in to_delete:
            try:
                archive.unlink()
                sidecar = archive.with_suffix(archive.suffix + ".sha256")
                if sidecar.exists():
                    sidecar.unlink()
            except OSError as exc:
                logger.warning(
                    "prune_delete_failed",
                    extra={"archive": str(archive), "error": str(exc)},
                )

    return PruneReport(
        deleted=[str(p) for p in to_delete],
        kept=[str(p) for p in to_keep],
        dry_run=dry_run,
    )


def _default_backup_name(db_path: Path) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{db_path.stem}-{stamp}.db"


# --------------------------------------------------------------------------- CLI dispatch


def _print_list_human(rows: list[BackupInfo]) -> None:
    if not rows:
        print("(no backups)")
        return
    cols = ("MODIFIED", "SIZE", "CHECKSUM", "PATH")
    fmt = "  ".join(("{:<20}", "{:>10}", "{:<10}", "{:<}"))
    print(fmt.format(*cols))
    print(fmt.format(*("-" * len(c) for c in cols)))
    for r in rows:
        size = _humanise_size(r.size_bytes)
        if not r.checksum_present:
            check = "missing"
        elif r.checksum_matches:
            check = "ok"
        else:
            check = "MISMATCH"
        print(fmt.format(r.modified_at, size, check, r.path))


def _humanise_size(n: int) -> str:
    """Compact size string — 1.2 MB, 340 kB, 8 B — for the ``list`` table."""
    for unit in ("B", "kB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n //= 1024
    return f"{n} TB"  # pragma: no cover — see loop guard


def _cmd_backup(args: argparse.Namespace, db_path: Path) -> int:
    output = args.output_dir / _default_backup_name(db_path)
    produced = backup(db_path, output, compress=not args.no_compress)
    if args.emit_json:
        print(
            json.dumps(
                {"archive": str(produced), "compressed": not args.no_compress},
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print(str(produced))
    return 0


def _cmd_restore(args: argparse.Namespace, db_path: Path) -> int:
    try:
        restored = restore(args.archive, db_path, force=args.force)
    except FileNotFoundError as exc:
        logger.error(str(exc))
        return 1
    except FileExistsError as exc:
        logger.error(str(exc))
        return 2
    if args.emit_json:
        print(json.dumps({"restored": str(restored)}, indent=2, ensure_ascii=False))
    else:
        print(str(restored))
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    try:
        report = verify(args.archive)
    except FileNotFoundError as exc:
        logger.error(str(exc))
        return 1
    if args.emit_json:
        print(json.dumps(asdict(report), indent=2, ensure_ascii=False))
    else:
        print(
            f"archive={report.archive}\n"
            f"  sha256_actual   = {report.checksum_actual}\n"
            f"  sha256_expected = {report.checksum_expected or '(sidecar missing)'}\n"
            f"  checksum_ok     = {report.checksum_ok}\n"
            f"  integrity_ok    = {report.integrity_ok}\n"
            f"  integrity_msg   = {report.integrity_message}"
        )
    if not (report.checksum_ok and report.integrity_ok):
        return 3
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    rows = list_backups(args.dir)
    if args.emit_json:
        print(
            json.dumps(
                {"backups": [asdict(r) for r in rows]},
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        _print_list_human(rows)
    return 0


def _cmd_prune(args: argparse.Namespace) -> int:
    if args.keep is None and args.older_than_days is None:
        logger.error("prune requires at least one of --keep or --older-than-days")
        return 1
    try:
        report = prune(
            args.dir,
            keep=args.keep,
            older_than_days=args.older_than_days,
            dry_run=args.dry_run,
        )
    except ValueError as exc:
        logger.error(str(exc))
        return 1
    if args.emit_json:
        print(json.dumps(asdict(report), indent=2, ensure_ascii=False))
    else:
        prefix = "[dry-run] " if args.dry_run else ""
        print(f"{prefix}deleted={len(report.deleted)}  kept={len(report.kept)}")
        for p in report.deleted:
            print(f"  {prefix}delete {p}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Backup / restore / verify / rotate the SQLite database.  "
            "See `formulation-backup <subcommand> --help` for details."
        ),
    )
    sub = p.add_subparsers(dest="command", required=True)

    b = sub.add_parser("backup", help="Create an online backup of the DB.")
    b.add_argument("--output-dir", type=Path, default=Path("./backups"))
    b.add_argument("--no-compress", action="store_true", help="Do not gzip the artefact.")
    b.add_argument("--db-path", type=Path, help="Override DB path (defaults from FW_DATABASE_URL).")
    b.add_argument("--json", dest="emit_json", action="store_true")

    r = sub.add_parser("restore", help="Restore a backup archive into the DB.")
    r.add_argument("archive", type=Path, help="Backup file (.db or .db.gz).")
    r.add_argument("--db-path", type=Path, help="Override DB path (defaults from FW_DATABASE_URL).")
    r.add_argument("--force", action="store_true", help="Overwrite existing DB.")
    r.add_argument("--json", dest="emit_json", action="store_true")

    v = sub.add_parser(
        "verify",
        help="Verify a backup's SHA-256 sidecar AND run PRAGMA integrity_check.",
    )
    v.add_argument("archive", type=Path, help="Backup file (.db or .db.gz).")
    v.add_argument("--json", dest="emit_json", action="store_true")

    ls = sub.add_parser("list", help="List every backup in a directory.")
    ls.add_argument("--dir", type=Path, default=Path("./backups"))
    ls.add_argument("--json", dest="emit_json", action="store_true")

    pr = sub.add_parser(
        "prune",
        help="Rotate old backups — keep the N most recent and/or drop old ones.",
    )
    pr.add_argument("--dir", type=Path, default=Path("./backups"))
    pr.add_argument(
        "--keep",
        type=int,
        default=None,
        metavar="N",
        help="Retain only the N most recent archives.",
    )
    pr.add_argument(
        "--older-than-days",
        type=int,
        default=None,
        metavar="D",
        help="Delete archives older than D days.",
    )
    pr.add_argument(
        "--dry-run", action="store_true", help="Show what would be deleted without touching disk."
    )
    pr.add_argument("--json", dest="emit_json", action="store_true")

    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    settings = get_settings()
    setup_logging(log_level=settings.log_level, json_logs=settings.log_json)

    if args.command in {"backup", "restore"}:
        db_path = args.db_path or _sqlite_path_from_url(settings.database_url)
        if args.command == "backup":
            return _cmd_backup(args, db_path)
        return _cmd_restore(args, db_path)
    if args.command == "verify":
        return _cmd_verify(args)
    if args.command == "list":
        return _cmd_list(args)
    if args.command == "prune":
        return _cmd_prune(args)
    return 2  # pragma: no cover — argparse guards this


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "BackupInfo",
    "PruneReport",
    "VerifyReport",
    "backup",
    "list_backups",
    "main",
    "prune",
    "restore",
    "verify",
]
