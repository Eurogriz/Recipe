"""``formulation-init-db`` — create the database schema."""

from __future__ import annotations

import argparse
import asyncio
import logging
import secrets
import sys
from pathlib import Path

from ...infrastructure.config import get_settings, reset_settings_cache
from ...infrastructure.db.connection import Database
from ...infrastructure.db.models import Base
from ...infrastructure.logging.setup import setup_logging

logger = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Initialise the formulation database schema.")
    p.add_argument("--db-path", type=Path, default=None, help="Path to the SQLite file.")
    p.add_argument("--url", type=str, default=None, help="Full SQLAlchemy URL.")
    p.add_argument(
        "--create-encryption-key",
        action="store_true",
        help="Generate a fresh 32-byte SQLCipher key and print it to stdout.",
    )
    p.add_argument("--drop-first", action="store_true", help="Drop existing tables first.")
    return p.parse_args(argv)


async def _run(args: argparse.Namespace) -> None:
    settings = get_settings()
    setup_logging(log_level=settings.log_level, json_logs=settings.log_json)

    key = settings.encryption_key_hex or None
    if args.create_encryption_key:
        key = secrets.token_hex(32)
        print(f"# Generated encryption key (store securely!):\nFW_ENCRYPTION_KEY_HEX={key}")

    if args.url:
        url = args.url
    elif args.db_path:
        args.db_path.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite+aiosqlite:///{args.db_path.absolute()}"
    else:
        url = settings.database_url

    db = Database.from_url(url=url, encryption_key_hex=key, echo=settings.database_echo)
    await db.init()
    try:
        async with db.engine.begin() as conn:
            if args.drop_first:
                logger.warning("Dropping existing tables (--drop-first)")
                await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    finally:
        await db.close()
    logger.info("Database schema created successfully")


def main(argv: list[str] | None = None) -> int:
    reset_settings_cache()
    args = _parse_args(argv or sys.argv[1:])
    try:
        asyncio.run(_run(args))
    except Exception as exc:  # pragma: no cover — CLI last resort
        logger.error("init-db failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
