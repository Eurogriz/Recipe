"""Alembic environment configuration.

Runs migrations both offline (``alembic upgrade head --sql``) and online
(``alembic upgrade head``). The database URL is resolved in this order:

    1. ``sqlalchemy.url`` set on the alembic command line (``-x sqlalchemy.url=…``)
    2. ``FW_DATABASE_URL`` environment variable
    3. ``sqlalchemy.url`` from alembic.ini

For SQLite the URL is silently upgraded to the ``aiosqlite`` driver so
the online mode's async engine works out of the box.
"""

from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Ensure the package is importable when alembic is invoked outside the venv.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from formulation_workbench.infrastructure.db.models import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _resolve_url() -> str:
    url = context.get_x_argument(as_dictionary=True).get("sqlalchemy.url")
    if not url:
        url = os.environ.get("FW_DATABASE_URL")
    if not url:
        url = config.get_main_option("sqlalchemy.url") or "sqlite+aiosqlite:///./formulation.db"
    # Normalise SQLite URLs to the async driver expected by the online mode.
    if url.startswith("sqlite:///"):
        url = "sqlite+aiosqlite:///" + url[len("sqlite:///") :]
    return url


target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emits SQL, does not connect)."""
    url = _resolve_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode using an async engine."""
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _resolve_url()

    connectable = async_engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    try:
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for online migrations."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
