"""Alembic migration integration tests.

Two goals:

1. ``alembic upgrade head`` succeeds on a clean SQLite database.
2. The schema produced by migrations equals the schema produced by
   ``Base.metadata.create_all`` — i.e., migrations are not silently drifting
   from the ORM models. If this ever fails, generate a new revision with
   ``alembic revision --autogenerate -m "…"``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

from formulation_workbench.infrastructure.db.models import Base

pytestmark = [pytest.mark.integration]

REPO_ROOT = Path(__file__).resolve().parents[2]


def _alembic_bin() -> str:
    # Prefer the interpreter running the tests so we don't rely on PATH.
    import sys

    return sys.executable


def _run_alembic(db_url: str) -> None:
    import os

    result = subprocess.run(  # noqa: S603 — controlled args, no shell
        [_alembic_bin(), "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        env={**os.environ, "FW_DATABASE_URL": db_url},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:  # pragma: no cover — makes failure obvious
        raise AssertionError(
            f"alembic upgrade head failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )


def _table_signature(engine) -> dict[str, set[str]]:
    """Return {table_name: {column_name, …}} for every table in the DB."""
    inspector = inspect(engine)
    return {
        name: {col["name"] for col in inspector.get_columns(name)}
        for name in inspector.get_table_names()
        if name != "alembic_version"
    }


def test_alembic_upgrade_head_creates_all_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "migrated.db"
    _run_alembic(f"sqlite+aiosqlite:///{db_path}")

    engine = create_engine(f"sqlite:///{db_path}")
    tables = _table_signature(engine)
    expected_subset = {
        "user",
        "raw_material",
        "supplier",
        "source_citation",
        "recipe",
        "composition_stage",
        "component",
        "recipe_source_reference",
        "audit_log_entry",
    }
    assert expected_subset.issubset(tables.keys()), (
        f"missing tables: {expected_subset - tables.keys()}"
    )


def test_migrations_match_models(tmp_path: Path) -> None:
    """Schema produced by migrations must match Base.metadata."""
    # 1. Apply migrations.
    migrated = tmp_path / "migrated.db"
    _run_alembic(f"sqlite+aiosqlite:///{migrated}")
    migrated_engine = create_engine(f"sqlite:///{migrated}")
    migrated_sig = _table_signature(migrated_engine)

    # 2. Create the same DB from ORM metadata directly.
    fresh = tmp_path / "fresh.db"
    fresh_engine = create_engine(f"sqlite:///{fresh}")
    Base.metadata.create_all(fresh_engine)
    fresh_sig = _table_signature(fresh_engine)

    missing = set(fresh_sig) - set(migrated_sig)
    extra = set(migrated_sig) - set(fresh_sig)
    assert not missing, f"tables in models but not in migrations: {missing}"
    assert not extra, f"tables in migrations but not in models: {extra}"

    for table, cols in fresh_sig.items():
        migrated_cols = migrated_sig[table]
        col_missing = cols - migrated_cols
        col_extra = migrated_cols - cols
        assert not col_missing, f"{table}: missing columns in migrations: {col_missing}"
        assert not col_extra, f"{table}: extra columns in migrations: {col_extra}"
