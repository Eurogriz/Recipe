"""Repository for personal API keys.

Tokens are the "long-lived" complement to session cookies: a session
cookie is for a human at a browser, a token is for CI, cron, a
lab-instrument daemon.  They inherit the issuing user's role and go
away when the user is deleted (``ON DELETE CASCADE``).

Storage model
=============
- Plaintext token format: ``fw_<43-char-urlsafe-b64>``.  Total ~46
  chars — that's 32 bytes of ``secrets.token_bytes`` encoded
  urlsafe, deterministic length, easy to spot in logs / configs.
- Only the SHA-256 digest is persisted (``token_hash``); the
  plaintext is returned to the caller **once** and can never be
  recovered.  Same trade-off as SSH's ``authorized_keys`` — lose
  it, mint a new one.
- ``token_prefix`` = first 8 chars of the plaintext.  Displayed in
  the UI and written into audit-log entries so an operator can see
  "this event came from fw_a1b2c3…" without ever seeing the secret.

Auth path
=========
:meth:`authenticate` looks up the digest of the presented header, and
refuses the row when it's revoked or expired.  On success it stamps
``last_used_at`` (best-effort — never breaks the request on write
failure) and returns the owning :class:`UserRecord` so the caller can
compute scopes exactly like it does for HTTP Basic.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select

from ..connection import Database
from ..models import ApiKeyModel, UserModel
from .users import UserRecord, _to_record  # type: ignore[attr-defined]

logger = logging.getLogger(__name__)


_TOKEN_PREFIX = "fw_"  # noqa: S105  — public prefix, not a password
_TOKEN_ENTROPY_BYTES = 32
_TOKEN_PREFIX_DISPLAY_LEN = 8


class ApiKeyError(ValueError):
    """Raised when an API key cannot be created (bad label, duplicate…)."""


@dataclass(frozen=True, slots=True)
class ApiKeyRecord:
    """Metadata-only view of one API key row.

    Never carries the plaintext token — that is returned exactly once
    from :meth:`ApiKeyRepository.create` and thrown away afterwards.
    """

    id: str
    user_id: str
    label: str
    token_prefix: str
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None

    @property
    def is_active(self) -> bool:
        """True iff the key is neither revoked nor past its expiry."""
        if self.revoked_at is not None:
            return False
        return not (self.expires_at is not None and _in_past(self.expires_at))


def _in_past(ts: datetime) -> bool:
    """True iff ``ts`` is at or before "now".

    Normalises the input so a tz-naive datetime coming out of SQLite
    (which drops the ``tzinfo`` on read) compares cleanly with the
    aware ``datetime.now(timezone.utc)`` we produce internally.
    Both sides are treated as UTC — that's the only timezone we
    ever persist.
    """
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts <= datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class IssuedApiKey:
    """Result of :meth:`ApiKeyRepository.create` — plaintext + metadata.

    The ``plaintext`` field is populated only here; it never appears
    in a stored row or a subsequent read.
    """

    record: ApiKeyRecord
    plaintext: str


def _hash_token(plaintext: str) -> str:
    """Deterministic SHA-256 hex digest of the plaintext token."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def _mint_token() -> str:
    """Generate a fresh plaintext token.  Uses ``secrets`` (CSPRNG)."""
    return _TOKEN_PREFIX + secrets.token_urlsafe(_TOKEN_ENTROPY_BYTES)


class ApiKeyRepository:
    """CRUD + authentication for the ``api_key`` table."""

    def __init__(self, database: Database) -> None:
        self._database = database

    # ---- writes -------------------------------------------------------------

    async def create(
        self,
        *,
        user_id: str,
        label: str,
        expires_at: datetime | None = None,
    ) -> IssuedApiKey:
        """Mint a new key for ``user_id`` and return the plaintext once."""
        cleaned_label = (label or "").strip()
        if not cleaned_label:
            raise ApiKeyError("label must be non-empty")
        if len(cleaned_label) > 128:
            raise ApiKeyError("label must be <= 128 characters")

        plaintext = _mint_token()
        row = ApiKeyModel(
            id=uuid.uuid4().hex,
            user_id=user_id,
            label=cleaned_label,
            token_hash=_hash_token(plaintext),
            token_prefix=plaintext[:_TOKEN_PREFIX_DISPLAY_LEN],
            created_at=datetime.now(timezone.utc),
            expires_at=expires_at,
        )
        async with self._database.session() as session:
            session.add(row)
            await session.commit()

        return IssuedApiKey(record=_row_to_record(row), plaintext=plaintext)

    async def revoke(self, key_id: str) -> bool:
        """Mark a key revoked.  Returns ``False`` when the row is missing."""
        async with self._database.session() as session:
            row = await session.get(ApiKeyModel, key_id)
            if row is None:
                return False
            if row.revoked_at is not None:
                # Idempotent — a caller retrying revocation must not
                # be surprised by a 404 the second time round.
                return True
            row.revoked_at = datetime.now(timezone.utc)
            await session.commit()
        return True

    # ---- reads --------------------------------------------------------------

    async def list_for_user(self, user_id: str) -> list[ApiKeyRecord]:
        stmt = (
            select(ApiKeyModel)
            .where(ApiKeyModel.user_id == user_id)
            .order_by(ApiKeyModel.created_at.desc())
        )
        async with self._database.session() as session:
            rows = (await session.execute(stmt)).scalars().all()
        return [_row_to_record(r) for r in rows]

    async def get(self, key_id: str) -> ApiKeyRecord | None:
        async with self._database.session() as session:
            row = await session.get(ApiKeyModel, key_id)
        return None if row is None else _row_to_record(row)

    # ---- auth ---------------------------------------------------------------

    async def authenticate(self, plaintext: str) -> UserRecord | None:
        """Resolve ``plaintext`` to the owning user, or ``None``.

        Refuses inactive users, revoked keys, and expired keys.  Also
        stamps ``last_used_at`` on success — best-effort, a write
        failure is swallowed so read-only replicas still authenticate.
        """
        if not plaintext or not plaintext.startswith(_TOKEN_PREFIX):
            return None
        digest = _hash_token(plaintext)
        async with self._database.session() as session:
            stmt = (
                select(ApiKeyModel, UserModel)
                .join(UserModel, UserModel.id == ApiKeyModel.user_id)
                .where(ApiKeyModel.token_hash == digest)
            )
            row = (await session.execute(stmt)).first()
            if row is None:
                return None
            key_row, user_row = row
            if key_row.revoked_at is not None:
                return None
            if key_row.expires_at is not None and _in_past(key_row.expires_at):
                return None
            if not user_row.is_active:
                return None
            key_row.last_used_at = datetime.now(timezone.utc)
            try:
                await session.commit()
            except Exception:  # pragma: no cover — best-effort
                await session.rollback()
            return _to_record(user_row)


def _row_to_record(row: ApiKeyModel) -> ApiKeyRecord:
    return ApiKeyRecord(
        id=row.id,
        user_id=row.user_id,
        label=row.label,
        token_prefix=row.token_prefix,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
    )


__all__ = [
    "ApiKeyError",
    "ApiKeyRecord",
    "ApiKeyRepository",
    "IssuedApiKey",
]
