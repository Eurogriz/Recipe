"""Users repository — CRUD over ``user`` table + password hashing.

Password hashing uses ``hashlib.scrypt`` (stdlib, no extra dep).  We
stash both the salt and the parameters (``n``, ``r``, ``p``) inside
the ``password_hash`` string so future migrations to stronger params
stay backwards-compatible.  Storage format:

    scrypt$<n>$<r>$<p>$<salt_hex>$<hash_hex>

The four accepted roles map to permission scopes at auth time (see
``presentation.api.auth``):

    Viewer         → recipes:read
    Technologist   → recipes:read + recipes:write
    Auditor        → recipes:read + recipes:write + recipes:verify
    Admin          → *

Auditor differs from Technologist by having the reserved
``recipes:verify`` scope; today all verify endpoints are guarded by
``require_writer`` (i.e. any Technologist can verify), but the scope
is already present so that a future tightening is a one-line change.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select

from ..connection import Database
from ..models import UserModel

# --------------------------------------------------------------------------- roles


class UnknownRoleError(ValueError):
    """Raised when a role name is not one of the four canonical ones."""


VALID_ROLES: frozenset[str] = frozenset({"Viewer", "Technologist", "Auditor", "Admin"})


def role_scopes(role: str) -> frozenset[str]:
    """Return the permission scopes granted by a role.

    Unknown roles raise :class:`UnknownRoleError` so a bad seed stops
    the process at boot rather than silently granting nothing.
    """
    if role == "Viewer":
        return frozenset({"recipes:read"})
    if role == "Technologist":
        return frozenset({"recipes:read", "recipes:write"})
    if role == "Auditor":
        return frozenset({"recipes:read", "recipes:write", "recipes:verify"})
    if role == "Admin":
        return frozenset({"*"})
    raise UnknownRoleError(f"unknown role: {role!r}, expected one of {sorted(VALID_ROLES)}")


# --------------------------------------------------------------------------- password hashing


_SCRYPT_N = 2**14  # ~16 MB per hash — comfortable for a login endpoint
_SCRYPT_R = 8
_SCRYPT_P = 1


def hash_password(plaintext: str) -> str:
    """Hash a plaintext password with a fresh salt."""
    if not plaintext or len(plaintext) < 6:
        raise ValueError("password must be at least 6 characters")
    salt = os.urandom(16)
    digest = hashlib.scrypt(
        plaintext.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=32,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(plaintext: str, stored: str) -> bool:
    """Check a plaintext password against a stored hash."""
    try:
        scheme, n_s, r_s, p_s, salt_hex, hash_hex = stored.split("$", 5)
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    try:
        n, r, p = int(n_s), int(r_s), int(p_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except ValueError:
        return False
    try:
        got = hashlib.scrypt(
            plaintext.encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            dklen=len(expected),
        )
    except (ValueError, MemoryError):
        return False
    return hmac.compare_digest(got, expected)


# --------------------------------------------------------------------------- repository


@dataclass(frozen=True, slots=True)
class UserRecord:
    """Read-side representation of a user row."""

    id: str
    username: str
    email: str | None
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None


class _Unset:
    """Sentinel so ``email=None`` (explicit clear) can be told apart
    from ``email`` argument omitted entirely."""


_UNSET = _Unset()


class UserRepository:
    """CRUD over ``user`` table plus password verification."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def create(
        self,
        *,
        username: str,
        password: str,
        role: str,
        email: str | None = None,
        is_active: bool = True,
    ) -> UserRecord:
        if role not in VALID_ROLES:
            raise UnknownRoleError(f"unknown role: {role!r}, expected one of {sorted(VALID_ROLES)}")
        if not username or not username.strip():
            raise ValueError("username must be non-empty")
        password_hash = hash_password(password)
        user_id = uuid.uuid4().hex
        async with self._database.session() as session:
            row = UserModel(
                id=user_id,
                username=username.strip(),
                password_hash=password_hash,
                email=(email.strip() if email else None),
                role=role,
                is_active=is_active,
                created_at=datetime.now(timezone.utc),
            )
            session.add(row)
            await session.commit()
        return await self._require_by_id(user_id)

    async def update(
        self,
        user_id: str,
        *,
        email: str | _Unset | None = _UNSET,
        role: str | None = None,
        is_active: bool | None = None,
        new_password: str | None = None,
    ) -> UserRecord:
        if role is not None and role not in VALID_ROLES:
            raise UnknownRoleError(f"unknown role: {role!r}, expected one of {sorted(VALID_ROLES)}")
        async with self._database.session() as session:
            row = await session.get(UserModel, user_id)
            if row is None:
                raise LookupError(f"user not found: {user_id}")
            if email is not _UNSET:
                row.email = email.strip() if email else None  # type: ignore[union-attr]
            if role is not None:
                row.role = role
            if is_active is not None:
                row.is_active = is_active
            if new_password is not None:
                row.password_hash = hash_password(new_password)
            await session.commit()
        return await self._require_by_id(user_id)

    async def delete(self, user_id: str) -> bool:
        async with self._database.session() as session:
            row = await session.get(UserModel, user_id)
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
        return True

    async def get_by_username(self, username: str) -> UserRecord | None:
        async with self._database.session() as session:
            stmt = select(UserModel).where(UserModel.username == username)
            row = (await session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _to_record(row)

    async def get_by_id(self, user_id: str) -> UserRecord | None:
        async with self._database.session() as session:
            row = await session.get(UserModel, user_id)
        return None if row is None else _to_record(row)

    async def list_all(self, *, limit: int = 100) -> list[UserRecord]:
        async with self._database.session() as session:
            stmt = select(UserModel).order_by(UserModel.username).limit(limit)
            rows = (await session.execute(stmt)).scalars().all()
        return [_to_record(r) for r in rows]

    async def authenticate(self, username: str, password: str) -> UserRecord | None:
        """Return the user record iff the password is correct AND the user is active.

        Also updates ``last_login_at`` on success — best-effort, silently
        ignores a write failure.
        """
        async with self._database.session() as session:
            stmt = select(UserModel).where(UserModel.username == username)
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None or not row.is_active:
                return None
            if not verify_password(password, row.password_hash):
                return None
            row.last_login_at = datetime.now(timezone.utc)
            try:
                await session.commit()
            except Exception:  # pragma: no cover — best-effort
                await session.rollback()
        return _to_record(row)

    async def _require_by_id(self, user_id: str) -> UserRecord:
        row = await self.get_by_id(user_id)
        if row is None:  # pragma: no cover — insert just happened
            raise LookupError(f"user not found after insert: {user_id}")
        return row


# --------------------------------------------------------------------------- private helpers


def _to_record(row: UserModel) -> UserRecord:
    return UserRecord(
        id=row.id,
        username=row.username,
        email=row.email,
        role=row.role,
        is_active=bool(row.is_active),
        created_at=row.created_at,
        last_login_at=row.last_login_at,
    )


__all__ = [
    "VALID_ROLES",
    "UnknownRoleError",
    "UserRecord",
    "UserRepository",
    "hash_password",
    "role_scopes",
    "verify_password",
]
