"""Runtime configuration (pydantic-settings based).

Settings load from environment variables prefixed with ``FW_`` and, optionally,
from a ``.env`` file. Defaults are safe for local development but every
security-sensitive value MUST be overridden in production (see docstring of
:class:`AppSettings`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """Global application configuration.

    In production you MUST override:
        - ``FW_DATABASE_URL`` — location of the SQLite/SQLCipher database.
        - ``FW_ENCRYPTION_KEY_HEX`` — 64-char hex string (32-byte AES-256 key).
          Provide via secret manager, NOT via a checked-in .env file.
        - ``FW_ENVIRONMENT`` — ``production`` triggers stricter runtime checks.

    Values are validated on load; the process exits early if a required
    value is missing or malformed.
    """

    model_config = SettingsConfigDict(
        env_prefix="FW_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- Environment ---------------------------------------------------------
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_json: bool = True

    # ---- Database ------------------------------------------------------------
    database_url: str = "sqlite+aiosqlite:///./data/formulation.db"
    database_echo: bool = False
    # Optional SQLCipher key (64 hex chars). If empty, DB is unencrypted.
    encryption_key_hex: str = ""

    # ---- HTTP / API ----------------------------------------------------------
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_root_path: str = ""
    api_cors_origins: list[str] = Field(default_factory=list)

    # ---- Auth ----------------------------------------------------------------
    # Static bearer token — the legacy option from 1.1.x.  Kept for
    # backwards compatibility.  Prefer JWT for new deployments.
    api_token: str = ""

    # JWT settings.  When ``jwt_secret`` is non-empty, JWTs are accepted
    # (and preferred over the static token).  HS256 by default.
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = ""
    jwt_require_exp: bool = True

    # ---- Paths ---------------------------------------------------------------
    data_dir: Path = Path("./data")
    export_dir: Path = Path("./exports")
    model_dir: Path = Path("./data/models")
    regulatory_data_dir: Path = Path("./data/regulatory")

    # ---- Observability -------------------------------------------------------
    metrics_enabled: bool = True
    otlp_endpoint: str = ""  # e.g. http://otel-collector:4317
    otel_service_name: str = "formulation-workbench"

    # ---- Rate limiting -------------------------------------------------------
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 120

    # ---- Validation ----------------------------------------------------------
    @field_validator("encryption_key_hex")
    @classmethod
    def _validate_key(cls, v: str) -> str:
        if not v:
            return v
        if len(v) != 64:
            raise ValueError("FW_ENCRYPTION_KEY_HEX must be exactly 64 hex characters (32 bytes)")
        try:
            int(v, 16)
        except ValueError as e:  # pragma: no cover — defensive
            raise ValueError("FW_ENCRYPTION_KEY_HEX must be valid hexadecimal") from e
        return v

    def enforce_production_invariants(self) -> None:
        """Fail fast if security-critical values are missing in production."""
        if self.environment != "production":
            return
        problems: list[str] = []
        if self.debug:
            problems.append("FW_DEBUG must be false in production")
        if not self.api_token and not self.jwt_secret:
            problems.append("Either FW_API_TOKEN or FW_JWT_SECRET must be set in production")
        if self.jwt_secret and self.jwt_algorithm == "HS256" and len(self.jwt_secret) < 32:
            problems.append("FW_JWT_SECRET must be at least 32 characters when using HS256")
        if not self.encryption_key_hex and "sqlite" in self.database_url:
            problems.append("FW_ENCRYPTION_KEY_HEX must be set in production when using SQLite")
        if problems:
            raise RuntimeError("Production configuration invalid: " + "; ".join(problems))


_cached: AppSettings | None = None


def get_settings() -> AppSettings:
    """Return a cached :class:`AppSettings` instance (loaded once)."""
    global _cached
    if _cached is None:
        _cached = AppSettings()
    return _cached


def reset_settings_cache() -> None:
    """Reset the cached settings (test helper)."""
    global _cached
    _cached = None


__all__ = ["AppSettings", "get_settings", "reset_settings_cache"]
