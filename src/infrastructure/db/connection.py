"""SQLite + SQLCipher database connection management.

Provides async SQLAlchemy session factory with encryption.

References:
    - SQLCipher 4 API: https://www.zetetic.net/sqlcipher/sqlcipher-api/
    - SQLAlchemy 2.0 async: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ...domain.exceptions import DomainError

logger = logging.getLogger(__name__)

# Default SQLCipher configuration (see Zetetic documentation)
DEFAULT_SQLCIPHER_PRAGMAS = [
    "PRAGMA cipher_page_size = 4096",
    "PRAGMA kdf_iter = 256000",  # PBKDF2 iterations (high for security)
    "PRAGMA cipher_hmac_algorithm = HMAC_SHA512",
    "PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512",
    "PRAGMA cipher_use_hmac = ON",
]


class DatabaseConnectionError(DomainError):
    """Raised when database connection or encryption fails."""


def _build_sqlcipher_url(
    db_path: Path,
    encryption_key_hex: str,
) -> str:
    """Build async SQLite URL with SQLCipher.

    Args:
        db_path: Path to the .db file.
        encryption_key_hex: 64-char hex string (32 bytes / 256-bit key).
    """
    # SQLite URL with hex-encoded key pragma
    # The key is set via PRAGMA key in on_connect pragma callback
    abs_path = db_path.absolute()
    return f"sqlite+aiosqlite:///{abs_path}"


class Database:
    """Async SQLAlchemy engine + session factory for encrypted SQLite (SQLCipher).

    Usage:
        db = Database(db_path=Path("formulation.db"), encryption_key_hex="...")
        await db.init()
        async with db.session() as session:
            ...
        await db.close()
    """

    def __init__(
        self,
        db_path: Path,
        encryption_key_hex: str,
        sqlcipher_pragmas: list[str] | None = None,
        echo: bool = False,
    ) -> None:
        if len(encryption_key_hex) != 64:
            raise DatabaseConnectionError(
                f"Encryption key must be 64 hex chars (32 bytes / 256-bit), "
                f"got {len(encryption_key_hex)} chars."
            )
        try:
            int(encryption_key_hex, 16)
        except ValueError as e:
            raise DatabaseConnectionError(
                f"Encryption key must be valid hexadecimal: {e}"
            ) from e

        self._db_path = db_path
        self._encryption_key_hex = encryption_key_hex
        self._sqlcipher_pragmas = sqlcipher_pragmas or DEFAULT_SQLCIPHER_PRAGMAS.copy()
        self._echo = echo
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    async def init(self) -> None:
        """Initialize the engine and session factory."""
        url = _build_sqlcipher_url(self._db_path, self._encryption_key_hex)

        self._engine = create_async_engine(
            url,
            echo=self._echo,
            future=True,
            connect_args={
                "check_same_thread": False,
            },
        )

        # Apply SQLCipher PRAGMAs on each connection
        from sqlalchemy import event

        @event.listens_for(self._engine.sync_engine, "connect")
        def set_sqlcipher_pragmas(dbapi_connection, connection_record):  # noqa: ARG001
            """Set SQLCipher key and configuration on each new connection."""
            cursor = dbapi_connection.cursor()
            try:
                # Set the encryption key first
                cursor.execute(f"PRAGMA key = \"x'{self._encryption_key_hex}'\"")
                # Then set other pragmas
                for pragma in self._sqlcipher_pragmas:
                    cursor.execute(pragma)
                dbapi_connection.commit()
            finally:
                cursor.close()

        self._session_factory = async_sessionmaker(
            self._engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )
        logger.info("Database initialized: %s", self._db_path)

    async def close(self) -> None:
        """Close the engine and release connections."""
        if self._engine is not None:
            await self._engine.dispose()
            logger.info("Database connection closed")

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Async context manager yielding a session."""
        if self._session_factory is None:
            raise DatabaseConnectionError("Database not initialized. Call init() first.")
        async with self._session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    @property
    def db_path(self) -> Path:
        return self._db_path


def derive_encryption_key_from_passphrase(passphrase: str, salt: bytes) -> str:
    """Derive a 32-byte encryption key from a passphrase using Argon2id.

    Returns 64-char hex string suitable for SQLCipher PRAGMA key.

    Args:
        passphrase: User's passphrase.
        salt: Cryptographically random salt (≥16 bytes).

    References:
        - Argon2id: https://github.com/P-H-C/phc-winner-argon2
        - OWASP Password Storage Cheat Sheet recommends Argon2id.
    """
    from argon2.low_level import hash_secret_raw, Type

    # Argon2id with OWASP-recommended parameters
    # Memory: 64 MB, Iterations: 3, Parallelism: 4, Output: 32 bytes
    raw_key = hash_secret_raw(
        secret=passphrase.encode("utf-8"),
        salt=salt,
        time_cost=3,
        memory_cost=65536,  # 64 MiB
        parallelism=4,
        hash_len=32,
        type=Type.ID,
    )
    return raw_key.hex()
