"""SQLAlchemy async engine + session management, with optional SQLCipher.

The connection layer intentionally accepts both plain SQLite (for dev,
CI and small deployments) and SQLCipher-encrypted SQLite (for
regulated environments). Non-SQLite databases (PostgreSQL, MySQL, …)
are supported as well; encryption is then delegated to the underlying
storage layer and the ``encryption_key_hex`` parameter is ignored.

References:
    - SQLCipher API: https://www.zetetic.net/sqlcipher/sqlcipher-api/
    - SQLAlchemy async: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ...domain.exceptions import DomainError

logger = logging.getLogger(__name__)

# SQLCipher configuration (Zetetic defaults for v4)
DEFAULT_SQLCIPHER_PRAGMAS: tuple[str, ...] = (
    "PRAGMA cipher_page_size = 4096",
    "PRAGMA kdf_iter = 256000",
    "PRAGMA cipher_hmac_algorithm = HMAC_SHA512",
    "PRAGMA cipher_kdf_algorithm = PBKDF2_HMAC_SHA512",
    "PRAGMA cipher_use_hmac = ON",
)


class DatabaseConnectionError(DomainError):
    """Raised when database connection or encryption setup fails."""


def _validate_hex_key(key: str) -> None:
    if len(key) != 64:
        raise DatabaseConnectionError(
            f"Encryption key must be 64 hex chars (32 bytes / 256-bit), got {len(key)}."
        )
    try:
        int(key, 16)
    except ValueError as e:  # pragma: no cover
        raise DatabaseConnectionError("Encryption key must be valid hexadecimal.") from e


class Database:
    """Async SQLAlchemy engine + session factory.

    Use :meth:`from_url` for the standard construction path. The legacy
    ``__init__(db_path=..., encryption_key_hex=...)`` signature is still
    supported for existing tests.
    """

    def __init__(
        self,
        db_path: Path | None = None,
        encryption_key_hex: str | None = None,
        *,
        url: str | None = None,
        sqlcipher_pragmas: tuple[str, ...] | None = None,
        echo: bool = False,
    ) -> None:
        if url is None:
            if db_path is None:
                raise DatabaseConnectionError("Either 'url' or 'db_path' must be provided.")
            url = f"sqlite+aiosqlite:///{Path(db_path).absolute()}"

        if encryption_key_hex:
            _validate_hex_key(encryption_key_hex)

        self._url = url
        self._db_path = db_path
        self._encryption_key_hex = encryption_key_hex or None
        self._sqlcipher_pragmas = sqlcipher_pragmas or DEFAULT_SQLCIPHER_PRAGMAS
        self._echo = echo
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    # ------------------------------------------------------------------ constructors
    @classmethod
    def from_url(
        cls,
        url: str,
        encryption_key_hex: str | None = None,
        *,
        echo: bool = False,
    ) -> Database:
        """Build a :class:`Database` from a SQLAlchemy URL string."""
        return cls(url=url, encryption_key_hex=encryption_key_hex, echo=echo)

    # ------------------------------------------------------------------ lifecycle
    async def init(self) -> None:
        """Initialise the engine and session factory."""
        connect_args: dict[str, object] = {}
        if self._url.startswith("sqlite"):
            connect_args["check_same_thread"] = False

        self._engine = create_async_engine(
            self._url,
            echo=self._echo,
            future=True,
            connect_args=connect_args,
        )

        # Apply SQLCipher PRAGMAs (or plain SQLite tuning) on each connection.
        if self._url.startswith("sqlite"):
            from sqlalchemy import event

            key = self._encryption_key_hex
            pragmas = self._sqlcipher_pragmas

            @event.listens_for(self._engine.sync_engine, "connect")
            def _on_connect(dbapi_connection, connection_record) -> None:
                cursor = dbapi_connection.cursor()
                try:
                    if key:
                        cursor.execute(f"PRAGMA key = \"x'{key}'\"")
                        for pragma in pragmas:
                            cursor.execute(pragma)
                    # General SQLite hygiene — safe for both plain & SQLCipher.
                    cursor.execute("PRAGMA journal_mode = WAL")
                    cursor.execute("PRAGMA synchronous = NORMAL")
                    cursor.execute("PRAGMA foreign_keys = ON")
                    cursor.execute("PRAGMA temp_store = MEMORY")
                    dbapi_connection.commit()
                finally:
                    cursor.close()

        self._session_factory = async_sessionmaker(
            self._engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )
        logger.info("Database initialised: %s", self._sanitised_url())

    async def close(self) -> None:
        """Close the engine and release connections."""
        if self._engine is not None:
            await self._engine.dispose()
            logger.info("Database connection closed")

    # ------------------------------------------------------------------ session API
    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Yield an :class:`AsyncSession` inside a context manager."""
        if self._session_factory is None:
            raise DatabaseConnectionError("Database not initialised. Call init() first.")
        async with self._session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    # ------------------------------------------------------------------ introspection
    @property
    def db_path(self) -> Path | None:
        return self._db_path

    @property
    def url(self) -> str:
        return self._url

    @property
    def is_encrypted(self) -> bool:
        return self._encryption_key_hex is not None and self._url.startswith("sqlite")

    def _sanitised_url(self) -> str:
        # Never log the passphrase / key. URLs may contain user:password@host.
        if "@" in self._url and "://" in self._url:
            scheme, rest = self._url.split("://", 1)
            _creds, host = rest.split("@", 1)
            return f"{scheme}://***@{host}"
        return self._url

    @property
    def engine(self) -> AsyncEngine:
        """Return the underlying engine (for migration/admin use)."""
        if self._engine is None:
            raise DatabaseConnectionError("Database not initialised. Call init() first.")
        return self._engine


def derive_encryption_key_from_passphrase(passphrase: str, salt: bytes) -> str:
    """Derive a 32-byte encryption key from a passphrase using Argon2id.

    Returns a 64-char hex string suitable for SQLCipher ``PRAGMA key``.

    Args:
        passphrase: User's passphrase (any length; validated by caller).
        salt: Cryptographically random salt (>= 16 bytes).

    References:
        - Argon2id: https://github.com/P-H-C/phc-winner-argon2
        - OWASP Password Storage Cheat Sheet.
    """
    from argon2.low_level import Type, hash_secret_raw

    if len(salt) < 16:
        raise ValueError("Salt must be at least 16 bytes.")

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


__all__ = [
    "DEFAULT_SQLCIPHER_PRAGMAS",
    "Database",
    "DatabaseConnectionError",
    "derive_encryption_key_from_passphrase",
]
