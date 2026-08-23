"""``formulation-backup`` — create and restore SQLite backups.

Uses SQLite's online backup API via ``VACUUM INTO`` (safe against concurrent
writers) and produces a compressed archive suitable for offsite storage.
Backups are transparent to SQLCipher: the destination file inherits the
same encryption key as the source.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import logging
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from ...infrastructure.config import get_settings
from ...infrastructure.logging.setup import setup_logging

logger = logging.getLogger(__name__)


def _sqlite_path_from_url(url: str) -> Path:
    """Extract the on-disk path from a ``sqlite+aiosqlite:///…`` URL."""
    if not url.startswith("sqlite"):
        raise ValueError(f"Only SQLite URLs are supported for backup, got {url!r}")
    _, _, remainder = url.partition("///")
    if not remainder:
        raise ValueError(f"Could not resolve DB path from URL {url!r}")
    return Path(remainder)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def backup(db_path: Path, output: Path, compress: bool = True) -> Path:
    """Create an online-consistent copy of ``db_path`` at ``output``.

    Returns the path of the produced artefact (``output`` itself if
    ``compress=False``, else ``output.gz``).
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Database file does not exist: {db_path}")
    output.parent.mkdir(parents=True, exist_ok=True)

    tmp = output.with_suffix(output.suffix + ".partial")
    with sqlite3.connect(db_path) as conn:
        conn.execute("VACUUM INTO ?", (str(tmp),))
    tmp.replace(output)

    if compress:
        gz_path = output.with_suffix(output.suffix + ".gz")
        with output.open("rb") as src, gzip.open(gz_path, "wb", compresslevel=6) as dst:
            shutil.copyfileobj(src, dst)
        output.unlink()
        checksum = _sha256(gz_path)
        (gz_path.with_suffix(gz_path.suffix + ".sha256")).write_text(
            f"{checksum}  {gz_path.name}\n", encoding="utf-8"
        )
        logger.info(
            "backup_completed",
            extra={"source": str(db_path), "destination": str(gz_path), "sha256": checksum},
        )
        return gz_path

    checksum = _sha256(output)
    (output.with_suffix(output.suffix + ".sha256")).write_text(
        f"{checksum}  {output.name}\n", encoding="utf-8"
    )
    logger.info(
        "backup_completed",
        extra={"source": str(db_path), "destination": str(output), "sha256": checksum},
    )
    return output


def restore(archive: Path, db_path: Path, *, force: bool = False) -> Path:
    """Restore a backup archive to ``db_path``.

    ``archive`` may be a plain ``.db`` file or a ``.db.gz`` file. If the
    destination exists, ``force=True`` is required to overwrite.
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


def _default_backup_name(db_path: Path) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{db_path.stem}-{stamp}.db"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Backup / restore the SQLite database.")
    sub = p.add_subparsers(dest="command", required=True)

    b = sub.add_parser("backup", help="Create an online backup of the DB.")
    b.add_argument("--output-dir", type=Path, default=Path("./backups"))
    b.add_argument("--no-compress", action="store_true", help="Do not gzip the artefact.")
    b.add_argument("--db-path", type=Path, help="Override DB path (defaults from FW_DATABASE_URL).")

    r = sub.add_parser("restore", help="Restore a backup archive into the DB.")
    r.add_argument("archive", type=Path, help="Backup file (.db or .db.gz).")
    r.add_argument("--db-path", type=Path, help="Override DB path (defaults from FW_DATABASE_URL).")
    r.add_argument("--force", action="store_true", help="Overwrite existing DB.")

    args = p.parse_args(argv or sys.argv[1:])

    settings = get_settings()
    setup_logging(log_level=settings.log_level, json_logs=settings.log_json)

    db_path = args.db_path or _sqlite_path_from_url(settings.database_url)

    if args.command == "backup":
        output = args.output_dir / _default_backup_name(db_path)
        produced = backup(db_path, output, compress=not args.no_compress)
        print(str(produced))
        return 0

    if args.command == "restore":
        restored = restore(args.archive, db_path, force=args.force)
        print(str(restored))
        return 0

    return 2  # pragma: no cover — argparse ensures a subcommand


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
