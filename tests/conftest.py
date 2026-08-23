"""Pytest configuration and shared fixtures."""

from __future__ import annotations

import asyncio
import os
import secrets
import sys
import tempfile
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from formulation_workbench.infrastructure.db.connection import (
    Database,
    derive_encryption_key_from_passphrase,
)


@pytest.fixture(scope="session")
def event_loop() -> Iterator[asyncio.AbstractEventLoop]:
    """Session-scoped event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def temp_dir() -> Iterator[Path]:
    """Temporary directory for test artifacts."""
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def encryption_key() -> str:
    """Generate a random 256-bit encryption key for tests."""
    return secrets.token_hex(32)


@pytest.fixture
def passphrase() -> str:
    """Test passphrase (NOT for production)."""
    return "test-passphrase-do-not-use-in-production"


@pytest.fixture
def salt() -> bytes:
    """Random 16-byte salt for Argon2id."""
    return secrets.token_bytes(16)


@pytest.fixture
def derived_key(passphrase: str, salt: bytes) -> str:
    """Encryption key derived from passphrase using Argon2id."""
    return derive_encryption_key_from_passphrase(passphrase, salt)


@pytest_asyncio.fixture
async def test_database(temp_dir: Path, encryption_key: str) -> AsyncIterator[Database]:
    """Encrypted SQLite database for integration tests.

    Uses file-based DB (not :memory:) to test SQLCipher integration.
    """
    db_path = temp_dir / "test.db"
    db = Database(db_path=db_path, encryption_key_hex=encryption_key, echo=False)
    await db.init()

    # Run migrations
    from sqlalchemy.ext.asyncio import create_async_engine

    from formulation_workbench.infrastructure.db.models import Base

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path.absolute()}")
    async with engine.begin() as conn:
        # Note: SQLCipher pragmas not applied here, but for migration tests OK
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()

    yield db
    await db.close()


# Set env vars for deterministic test behavior
os.environ.setdefault("PYTHONHASHSEED", "0")
