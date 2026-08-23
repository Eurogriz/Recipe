"""Unit tests for AppSettings validation."""

from __future__ import annotations

import pytest

from formulation_workbench.infrastructure.config import AppSettings, reset_settings_cache


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    reset_settings_cache()


class TestEncryptionKeyValidation:
    def test_empty_key_is_valid(self) -> None:
        settings = AppSettings(encryption_key_hex="")
        assert settings.encryption_key_hex == ""

    def test_valid_64_hex_key_is_accepted(self) -> None:
        settings = AppSettings(encryption_key_hex="a" * 64)
        assert len(settings.encryption_key_hex) == 64

    def test_short_key_rejected(self) -> None:
        with pytest.raises(Exception, match="64 hex"):
            AppSettings(encryption_key_hex="abcd")

    def test_non_hex_key_rejected(self) -> None:
        with pytest.raises(Exception, match="hex"):
            AppSettings(encryption_key_hex="z" * 64)


class TestProductionInvariants:
    def test_dev_mode_does_not_enforce(self) -> None:
        AppSettings(environment="development").enforce_production_invariants()

    def test_production_requires_api_token(self) -> None:
        s = AppSettings(
            environment="production",
            database_url="postgresql+asyncpg://user:pass@db/formulation",
            api_token="",
        )
        with pytest.raises(RuntimeError, match="FW_API_TOKEN"):
            s.enforce_production_invariants()

    def test_production_requires_encryption_key_for_sqlite(self) -> None:
        s = AppSettings(
            environment="production",
            database_url="sqlite+aiosqlite:///./prod.db",
            api_token="valid-token",
            encryption_key_hex="",
        )
        with pytest.raises(RuntimeError, match="FW_ENCRYPTION_KEY_HEX"):
            s.enforce_production_invariants()

    def test_production_rejects_debug_mode(self) -> None:
        s = AppSettings(
            environment="production",
            debug=True,
            database_url="postgresql+asyncpg://u:p@db/f",
            api_token="tok",
        )
        with pytest.raises(RuntimeError, match="FW_DEBUG"):
            s.enforce_production_invariants()

    def test_production_happy_path(self) -> None:
        s = AppSettings(
            environment="production",
            debug=False,
            database_url="postgresql+asyncpg://u:p@db/f",
            api_token="tok",
        )
        s.enforce_production_invariants()  # should not raise
