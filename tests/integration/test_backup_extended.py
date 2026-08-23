"""Tests for the v1.21 backup subcommands: verify, list, prune.

The core backup/restore path is already covered by test_backup.py —
here we exercise only the new bits.
"""

from __future__ import annotations

import gzip
import json
import sqlite3
import time
from pathlib import Path

import pytest

from formulation_workbench.presentation.commands.backup import (
    _write_sidecar,
    backup,
    list_backups,
    main,
    prune,
    verify,
)

pytestmark = [pytest.mark.integration]


# --------------------------------------------------------------------------- fixtures


def _make_sqlite(path: Path, rows: int = 3) -> None:
    """Create a small SQLite file with a marker table so PRAGMA
    integrity_check has something meaningful to look at."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE marker (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
        conn.executemany(
            "INSERT INTO marker (name) VALUES (?)",
            [(f"row-{i}",) for i in range(rows)],
        )
        conn.commit()


# --------------------------------------------------------------------------- verify


def test_verify_passes_for_good_backup(tmp_path: Path) -> None:
    src = tmp_path / "src.db"
    _make_sqlite(src)
    archive = backup(src, tmp_path / "backups" / "out.db", compress=True)
    report = verify(archive)
    assert report.checksum_ok is True
    assert report.integrity_ok is True
    assert report.integrity_message == "ok"


def test_verify_detects_tampered_archive(tmp_path: Path) -> None:
    src = tmp_path / "src.db"
    _make_sqlite(src)
    archive = backup(src, tmp_path / "backups" / "out.db", compress=True)

    # Corrupt one byte inside the gzipped body — checksum will drift
    # but integrity_check may still pass if the flip lands in the
    # gzip metadata rather than the sqlite payload.
    data = bytearray(archive.read_bytes())
    data[-8] ^= 0xFF  # tamper the very tail
    archive.write_bytes(bytes(data))

    report = verify(archive)
    # The sidecar was written before the tamper, so checksum must
    # mismatch.
    assert report.checksum_ok is False


def test_verify_reports_missing_sidecar(tmp_path: Path) -> None:
    src = tmp_path / "src.db"
    _make_sqlite(src)
    archive = backup(src, tmp_path / "backups" / "out.db", compress=True)
    # Delete the sidecar and re-verify.
    sidecar = archive.with_suffix(archive.suffix + ".sha256")
    sidecar.unlink()
    report = verify(archive)
    assert report.checksum_expected is None
    assert report.checksum_ok is False
    # But integrity_check still passes because the payload wasn't
    # touched.
    assert report.integrity_ok is True


def test_verify_missing_archive_raises_typed_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        verify(tmp_path / "does-not-exist.db.gz")


def test_verify_detects_broken_sqlite_payload(tmp_path: Path) -> None:
    """A gzipped junk file must fail integrity_check even if its
    sidecar matches (someone re-signed a broken archive)."""
    broken = tmp_path / "broken.db.gz"
    with gzip.open(broken, "wb") as fh:
        fh.write(b"this is not a sqlite file")
    # Re-sign so checksum matches.
    _write_sidecar(broken)
    report = verify(broken)
    assert report.checksum_ok is True
    assert report.integrity_ok is False


def test_verify_cli_exit_3_on_failure(tmp_path: Path) -> None:
    """The verify subcommand exits with 3 when either check fails."""
    broken = tmp_path / "broken.db"
    broken.write_bytes(b"not sqlite")
    _write_sidecar(broken)
    rc = main(["verify", str(broken)])
    assert rc == 3


# --------------------------------------------------------------------------- list


def test_list_returns_metadata_for_each_backup(tmp_path: Path) -> None:
    src = tmp_path / "src.db"
    _make_sqlite(src)
    dst_dir = tmp_path / "backups"
    a1 = backup(src, dst_dir / "one.db", compress=True)
    # Sleep so mtime ordering is deterministic.
    time.sleep(0.05)
    a2 = backup(src, dst_dir / "two.db", compress=False)

    rows = list_backups(dst_dir)
    assert len(rows) == 2
    paths = {r.path for r in rows}
    assert str(a1) in paths
    assert str(a2) in paths
    for r in rows:
        assert r.size_bytes > 0
        assert r.checksum_present is True
        assert r.checksum_matches is True


def test_list_detects_checksum_mismatch(tmp_path: Path) -> None:
    src = tmp_path / "src.db"
    _make_sqlite(src)
    dst_dir = tmp_path / "backups"
    a = backup(src, dst_dir / "one.db", compress=True)
    # Rewrite the sidecar with a wrong hash.
    sidecar = a.with_suffix(a.suffix + ".sha256")
    sidecar.write_text(f"{'0' * 64}  {a.name}\n", encoding="utf-8")
    rows = list_backups(dst_dir)
    assert len(rows) == 1
    assert rows[0].checksum_matches is False


def test_list_missing_directory_returns_empty(tmp_path: Path) -> None:
    assert list_backups(tmp_path / "nope") == []


def test_list_cli_json_output(tmp_path: Path, capsys) -> None:
    src = tmp_path / "src.db"
    _make_sqlite(src)
    dst_dir = tmp_path / "backups"
    backup(src, dst_dir / "one.db", compress=True)
    rc = main(["list", "--dir", str(dst_dir), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["backups"]) == 1


# --------------------------------------------------------------------------- prune


def _fake_old_backup(dst_dir: Path, name: str, days_old: int) -> Path:
    """Create a backup and stamp it as N days old on the filesystem."""
    src = dst_dir.parent / f"src-{name}.db"
    _make_sqlite(src)
    archive = backup(src, dst_dir / f"{name}.db", compress=True)
    if days_old:
        # ``os.utime`` accepts an (atime, mtime) tuple.  We shift both
        # so the mtime filter sees the archive as old.
        import os

        target = time.time() - days_old * 86400
        os.utime(archive, (target, target))
    return archive


def test_prune_keep_n_retains_newest(tmp_path: Path) -> None:
    dst = tmp_path / "backups"
    for i in range(4):
        _fake_old_backup(dst, f"b{i}", days_old=i)
        time.sleep(0.02)
    # After the loop b0 is newest (age 0), b3 is oldest (age 3d).
    report = prune(dst, keep=2, older_than_days=None)
    assert len(report.kept) == 2
    assert len(report.deleted) == 2


def test_prune_older_than_days_drops_stale(tmp_path: Path) -> None:
    dst = tmp_path / "backups"
    fresh = _fake_old_backup(dst, "fresh", days_old=0)
    stale = _fake_old_backup(dst, "stale", days_old=45)
    report = prune(dst, keep=None, older_than_days=30)
    assert str(stale) in report.deleted
    assert str(fresh) in report.kept


def test_prune_dry_run_does_not_delete(tmp_path: Path) -> None:
    dst = tmp_path / "backups"
    old = _fake_old_backup(dst, "old", days_old=10)
    report = prune(dst, keep=0, older_than_days=None, dry_run=True)
    # ``keep=0`` means "delete everything", so the archive appears in
    # ``deleted`` — but dry_run keeps it on disk.
    assert str(old) in report.deleted
    assert old.exists()
    assert report.dry_run is True


def test_prune_rejects_negative_age(tmp_path: Path) -> None:
    dst = tmp_path / "backups"
    dst.mkdir()
    with pytest.raises(ValueError, match="non-negative"):
        prune(dst, keep=None, older_than_days=-1)


def test_prune_cli_requires_at_least_one_filter(tmp_path: Path) -> None:
    """Running prune with no --keep and no --older-than-days is a
    footgun — refuse rather than silently deleting nothing."""
    rc = main(["prune", "--dir", str(tmp_path)])
    assert rc == 1


def test_prune_cli_deletes_sidecar_alongside_archive(tmp_path: Path) -> None:
    dst = tmp_path / "backups"
    _fake_old_backup(dst, "old", days_old=100)
    rc = main(["prune", "--dir", str(dst), "--older-than-days", "30"])
    assert rc == 0
    # Both the archive and its sidecar must be gone.
    remaining = list(dst.iterdir())
    assert remaining == []


# --------------------------------------------------------------------------- backup CLI json


def test_backup_cli_json_output(tmp_path: Path, capsys, monkeypatch) -> None:
    src = tmp_path / "src.db"
    _make_sqlite(src)
    dst_dir = tmp_path / "backups"

    # The backup subcommand normally reads FW_DATABASE_URL — override
    # via --db-path so the test doesn't depend on env leakage.
    rc = main(
        [
            "backup",
            "--db-path",
            str(src),
            "--output-dir",
            str(dst_dir),
            "--json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["compressed"] is True
    assert Path(payload["archive"]).exists()
