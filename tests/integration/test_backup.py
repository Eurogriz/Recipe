"""Integration tests for the backup/restore command."""

from __future__ import annotations

import gzip
import sqlite3
from pathlib import Path

import pytest

from formulation_workbench.presentation.commands.backup import (
    _sqlite_path_from_url,
    backup,
    restore,
)

pytestmark = [pytest.mark.integration]


def _make_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE demo (id INTEGER PRIMARY KEY, value TEXT)")
    conn.executemany("INSERT INTO demo(value) VALUES (?)", [("a",), ("b",), ("c",)])
    conn.commit()
    conn.close()


def _row_count(path: Path) -> int:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT COUNT(*) FROM demo").fetchone()[0]
    finally:
        conn.close()


def test_sqlite_path_from_url() -> None:
    p = _sqlite_path_from_url("sqlite+aiosqlite:///./data/demo.db")
    # Path may end up "./data/demo.db" on POSIX or "data/demo.db" after
    # normalisation depending on Python version; check the tail only.
    assert p.name == "demo.db"


def test_sqlite_path_from_url_rejects_non_sqlite() -> None:
    with pytest.raises(ValueError):
        _sqlite_path_from_url("postgresql+asyncpg://x/y")


def test_backup_creates_compressed_artefact_and_checksum(tmp_path: Path) -> None:
    src = tmp_path / "src.db"
    _make_db(src)

    out = tmp_path / "backups" / "src.db"
    produced = backup(src, out, compress=True)

    assert produced.exists()
    assert produced.suffix == ".gz"
    # Sidecar checksum file lives next to it.
    assert (produced.with_suffix(produced.suffix + ".sha256")).exists()

    # Decompress into a temp .db and check it's a functional SQLite database
    # with the original data intact. VACUUM INTO rewrites pages, so a
    # byte-for-byte comparison against the source is not appropriate.
    decompressed = tmp_path / "roundtrip.db"
    with gzip.open(produced, "rb") as src_file, decompressed.open("wb") as dst_file:
        dst_file.write(src_file.read())
    assert _row_count(decompressed) == _row_count(src)


def test_backup_uncompressed(tmp_path: Path) -> None:
    src = tmp_path / "src.db"
    _make_db(src)
    out = tmp_path / "backups" / "src.db"
    produced = backup(src, out, compress=False)

    assert produced == out
    assert produced.exists()
    assert (produced.with_suffix(produced.suffix + ".sha256")).exists()


def test_restore_roundtrips(tmp_path: Path) -> None:
    src = tmp_path / "src.db"
    _make_db(src)
    archive = backup(src, tmp_path / "b" / "src.db", compress=True)

    restored_dst = tmp_path / "restored.db"
    restore(archive, restored_dst)
    assert _row_count(restored_dst) == 3


def test_restore_refuses_to_clobber(tmp_path: Path) -> None:
    src = tmp_path / "src.db"
    _make_db(src)
    archive = backup(src, tmp_path / "b" / "src.db", compress=True)

    other = tmp_path / "other.db"
    _make_db(other)
    with pytest.raises(FileExistsError):
        restore(archive, other, force=False)


def test_backup_missing_source(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        backup(tmp_path / "nope.db", tmp_path / "out.db")
