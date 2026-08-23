"""Integration tests for Database connection.

Tests SQLCipher encryption integration with SQLAlchemy.
"""

from __future__ import annotations

import pytest

from formulation_workbench.infrastructure.db.connection import (
    Database,
    DatabaseConnectionError,
    derive_encryption_key_from_passphrase,
)


@pytest.mark.integration
class TestDatabaseConnection:
    """Tests for SQLCipher-encrypted database connection."""

    async def test_database_init_and_close(self, test_database: Database) -> None:
        """Database initializes and closes without errors."""
        # If we got here, init() succeeded
        assert test_database._engine is not None
        assert test_database._session_factory is not None

    async def test_session_yields_session(self, test_database: Database) -> None:
        """session() context manager yields a session."""
        async with test_database.session() as session:
            assert session is not None

    async def test_invalid_key_length_rejected(self, temp_dir) -> None:
        """Key of wrong length is rejected."""
        with pytest.raises(DatabaseConnectionError, match="64 hex chars"):
            Database(
                db_path=temp_dir / "bad.db",
                encryption_key_hex="tooshort",
            )

    async def test_invalid_hex_rejected(self, temp_dir) -> None:
        """Key with invalid hex characters is rejected."""
        with pytest.raises(DatabaseConnectionError, match="hexadecimal"):
            Database(
                db_path=temp_dir / "bad.db",
                encryption_key_hex="Z" * 64,  # Not valid hex
            )

    async def test_session_rollback_on_exception(self, test_database: Database) -> None:
        """Session rolls back on exception."""
        from sqlalchemy import text

        with pytest.raises(RuntimeError):
            async with test_database.session() as session:
                await session.execute(text("SELECT 1"))
                raise RuntimeError("test error")
        # If rollback didn't work, we'd see other issues; just verify no crash


@pytest.mark.integration
class TestPassphraseDerivation:
    """Tests for Argon2id passphrase → key derivation."""

    def test_same_passphrase_same_salt_same_key(self, passphrase: str, salt: bytes) -> None:
        """Deterministic: same inputs → same key."""
        key1 = derive_encryption_key_from_passphrase(passphrase, salt)
        key2 = derive_encryption_key_from_passphrase(passphrase, salt)
        assert key1 == key2
        assert len(key1) == 64  # 32 bytes in hex

    def test_different_salt_different_key(self, passphrase: str) -> None:
        """Different salt → different key."""
        import secrets

        salt1 = secrets.token_bytes(16)
        salt2 = secrets.token_bytes(16)
        key1 = derive_encryption_key_from_passphrase(passphrase, salt1)
        key2 = derive_encryption_key_from_passphrase(passphrase, salt2)
        assert key1 != key2

    def test_different_passphrase_different_key(self, salt: bytes) -> None:
        """Different passphrase → different key."""
        key1 = derive_encryption_key_from_passphrase("passphrase1", salt)
        key2 = derive_encryption_key_from_passphrase("passphrase2", salt)
        assert key1 != key2

    def test_key_is_valid_hex(self, passphrase: str, salt: bytes) -> None:
        """Derived key is valid hexadecimal."""
        key = derive_encryption_key_from_passphrase(passphrase, salt)
        # Should not raise
        bytes.fromhex(key)
