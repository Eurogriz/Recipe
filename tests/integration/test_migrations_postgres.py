"""Alembic drift check against a real PostgreSQL server.

Skipped locally unless ``FW_TEST_POSTGRES_URL`` points at a reachable
Postgres. In CI the ``postgres-integration`` job runs Postgres 16 as a
service container and sets the variable automatically.

The test uses the *sync* SQLAlchemy engine so we can drive the check
without dragging in extra runtime coupling.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine

from formulation_workbench.infrastructure.db.models import Base

pytestmark = [pytest.mark.integration]

REPO_ROOT = Path(__file__).resolve().parents[2]
_URL = os.environ.get("FW_TEST_POSTGRES_URL", "")

if not _URL:
    pytest.skip("FW_TEST_POSTGRES_URL not set", allow_module_level=True)


def _sync_url(url: str) -> str:
    """Turn the async URL into a sync-driver URL for inspection helpers."""
    return url.replace("+asyncpg", "").replace("postgresql+psycopg", "postgresql")


def _table_signature(engine: Engine) -> dict[str, set[str]]:
    inspector = inspect(engine)
    return {
        name: {col["name"] for col in inspector.get_columns(name)}
        for name in inspector.get_table_names()
        if name not in {"alembic_version"}
    }


def _reset_schema(engine: Engine) -> None:
    """Drop every non-system table so successive tests start clean."""
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP SCHEMA public CASCADE")
        conn.exec_driver_sql("CREATE SCHEMA public")


def _run_alembic() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        env={**os.environ, "FW_DATABASE_URL": _URL},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if result.returncode != 0:  # pragma: no cover
        raise AssertionError(
            f"alembic upgrade head failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )


def test_alembic_and_metadata_agree_on_postgres() -> None:
    engine = create_engine(_sync_url(_URL))

    # 1. Fresh DB → migrations.
    _reset_schema(engine)
    _run_alembic()
    migrated_sig = _table_signature(engine)

    # 2. Fresh DB → metadata.create_all.
    _reset_schema(engine)
    Base.metadata.create_all(engine)
    fresh_sig = _table_signature(engine)

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
