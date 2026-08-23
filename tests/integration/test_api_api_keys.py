"""Integration tests for personal API keys (v1.18.0).

Covers repository primitives (hash / authenticate / revoke) and the
full HTTP surface (`GET/POST/DELETE /users/{id}/api-keys`).  The
auth-mode roundtrip is exercised separately: a freshly-issued
plaintext token must let its owner reach protected endpoints as
their own user, and a revoked token must be rejected.
"""

from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from formulation_workbench.infrastructure.config import AppSettings, reset_settings_cache
from formulation_workbench.infrastructure.db.connection import Database
from formulation_workbench.infrastructure.db.models import Base
from formulation_workbench.infrastructure.db.repositories.api_keys import (
    ApiKeyError,
    ApiKeyRepository,
    _hash_token,
)
from formulation_workbench.infrastructure.db.repositories.users import UserRepository
from formulation_workbench.presentation.api.app import create_app

pytestmark = [pytest.mark.integration, pytest.mark.api]


def _basic(username: str, password: str) -> dict[str, str]:
    raw = f"{username}:{password}".encode()
    return {"Authorization": f"Basic {base64.b64encode(raw).decode()}"}


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------- unit


async def test_repo_create_and_authenticate(tmp_path: Path) -> None:
    dbc = Database.from_url(url=f"sqlite+aiosqlite:///{tmp_path / 'k.db'}")
    await dbc.init()
    async with dbc.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    users = UserRepository(dbc)
    user = await users.create(username="alice", password="alice-password", role="Viewer")

    repo = ApiKeyRepository(dbc)
    issued = await repo.create(user_id=user.id, label="ci-runner")
    assert issued.plaintext.startswith("fw_")
    assert issued.record.token_prefix == issued.plaintext[:8]
    assert issued.record.is_active is True

    got = await repo.authenticate(issued.plaintext)
    assert got is not None
    assert got.username == "alice"

    # Wrong plaintext (fresh mint, wrong digest) → None.
    assert await repo.authenticate("fw_bogus") is None
    # Missing prefix → None (no even hashing attempt).
    assert await repo.authenticate("wrong-shape") is None
    # Empty → None.
    assert await repo.authenticate("") is None
    await dbc.close()


async def test_repo_revoke_soft_delete(tmp_path: Path) -> None:
    dbc = Database.from_url(url=f"sqlite+aiosqlite:///{tmp_path / 'k.db'}")
    await dbc.init()
    async with dbc.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    users = UserRepository(dbc)
    user = await users.create(username="alice", password="alice-password", role="Viewer")
    repo = ApiKeyRepository(dbc)
    issued = await repo.create(user_id=user.id, label="ci")

    assert await repo.revoke(issued.record.id) is True
    # Idempotent.
    assert await repo.revoke(issued.record.id) is True
    # Row survives soft delete.
    listed = await repo.list_for_user(user.id)
    assert len(listed) == 1
    assert listed[0].revoked_at is not None
    assert listed[0].is_active is False
    # Authenticate refuses the revoked token.
    assert await repo.authenticate(issued.plaintext) is None
    await dbc.close()


async def test_repo_expired_key_rejected(tmp_path: Path) -> None:
    dbc = Database.from_url(url=f"sqlite+aiosqlite:///{tmp_path / 'k.db'}")
    await dbc.init()
    async with dbc.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    users = UserRepository(dbc)
    user = await users.create(username="alice", password="alice-password", role="Viewer")
    repo = ApiKeyRepository(dbc)
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    issued = await repo.create(user_id=user.id, label="stale", expires_at=past)

    assert issued.record.is_active is False
    assert await repo.authenticate(issued.plaintext) is None
    await dbc.close()


async def test_repo_rejects_blank_label(tmp_path: Path) -> None:
    dbc = Database.from_url(url=f"sqlite+aiosqlite:///{tmp_path / 'k.db'}")
    await dbc.init()
    async with dbc.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    users = UserRepository(dbc)
    user = await users.create(username="alice", password="alice-password", role="Viewer")
    repo = ApiKeyRepository(dbc)
    with pytest.raises(ApiKeyError):
        await repo.create(user_id=user.id, label="   ")
    await dbc.close()


def test_hash_token_is_deterministic() -> None:
    assert _hash_token("fw_abc") == _hash_token("fw_abc")
    assert _hash_token("fw_abc") != _hash_token("fw_xyz")
    # 64 hex chars for SHA-256.
    assert len(_hash_token("fw_abc")) == 64


# --------------------------------------------------------------------------- HTTP


@pytest_asyncio.fixture
async def api_with_users(
    tmp_path: Path,
) -> AsyncIterator[tuple[AsyncClient, str, str]]:
    """Build an API with an Admin (root) + a Viewer (alice) plus the
    alice-user's id (used by /users/{id}/api-keys routes)."""
    reset_settings_cache()
    db = tmp_path / "apikeys.db"
    dbc = Database.from_url(url=f"sqlite+aiosqlite:///{db}")
    await dbc.init()
    async with dbc.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    repo = UserRepository(dbc)
    await repo.create(username="root", password="root-password!", role="Admin")
    alice = await repo.create(username="alice", password="alice-password", role="Viewer")
    bob = await repo.create(username="bob", password="bob-password", role="Viewer")
    await dbc.close()

    settings = AppSettings(
        environment="development",
        database_url=f"sqlite+aiosqlite:///{db}",
        api_token="",
        rate_limit_enabled=False,
        model_dir=tmp_path / "models",
    )
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client, alice.id, bob.id


async def test_owner_can_create_list_revoke(
    api_with_users: tuple[AsyncClient, str, str],
) -> None:
    api, alice_id, _ = api_with_users
    headers = _basic("alice", "alice-password")

    r = await api.post(
        f"/users/{alice_id}/api-keys",
        headers=headers,
        json={"label": "lab-daemon"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["label"] == "lab-daemon"
    assert body["plaintext"].startswith("fw_")
    assert body["token_prefix"] == body["plaintext"][:8]
    assert body["is_active"] is True
    key_id = body["id"]
    plaintext = body["plaintext"]

    # Listing includes it (without plaintext).
    r = await api.get(f"/users/{alice_id}/api-keys", headers=headers)
    keys = r.json()["keys"]
    assert len(keys) == 1
    assert keys[0]["id"] == key_id
    assert "plaintext" not in keys[0]

    # The fresh token authenticates alice against a bearer endpoint.
    r = await api.get("/me", headers=_bearer(plaintext))
    assert r.status_code == 200, r.text
    me = r.json()
    assert me["mode"] == "api_key"
    assert me["subject"] == "user:alice"
    assert me["role"] == "Viewer"

    # Revocation.
    r = await api.delete(f"/users/{alice_id}/api-keys/{key_id}", headers=headers)
    assert r.status_code == 204
    # Revoked token is rejected loudly.
    r = await api.get("/me", headers=_bearer(plaintext))
    assert r.status_code == 401


async def test_non_owner_cannot_manage_another_users_keys(
    api_with_users: tuple[AsyncClient, str, str],
) -> None:
    api, alice_id, _ = api_with_users
    # Bob (Viewer, not owner, not Admin) tries to list Alice's keys.
    r = await api.get(f"/users/{alice_id}/api-keys", headers=_basic("bob", "bob-password"))
    assert r.status_code == 403


async def test_admin_can_manage_any_users_keys(
    api_with_users: tuple[AsyncClient, str, str],
) -> None:
    api, alice_id, _ = api_with_users
    headers = _basic("root", "root-password!")

    r = await api.post(
        f"/users/{alice_id}/api-keys",
        headers=headers,
        json={"label": "root-issued"},
    )
    assert r.status_code == 201, r.text
    key_id = r.json()["id"]

    # Admin can list & revoke.
    r = await api.get(f"/users/{alice_id}/api-keys", headers=headers)
    assert r.status_code == 200
    r = await api.delete(f"/users/{alice_id}/api-keys/{key_id}", headers=headers)
    assert r.status_code == 204


async def test_create_rejects_unknown_user(
    api_with_users: tuple[AsyncClient, str, str],
) -> None:
    api, _, _ = api_with_users
    r = await api.post(
        "/users/does-not-exist/api-keys",
        headers=_basic("root", "root-password!"),
        json={"label": "x"},
    )
    assert r.status_code == 404


async def test_create_rejects_bad_expires_at(
    api_with_users: tuple[AsyncClient, str, str],
) -> None:
    api, alice_id, _ = api_with_users
    r = await api.post(
        f"/users/{alice_id}/api-keys",
        headers=_basic("root", "root-password!"),
        json={"label": "x", "expires_at": "not-a-date"},
    )
    assert r.status_code == 422


async def test_bearer_with_fw_prefix_but_unknown_is_401(
    api_with_users: tuple[AsyncClient, str, str],
) -> None:
    api, _, _ = api_with_users
    # Any `fw_`-prefixed bearer with no matching row is a HARD 401,
    # never a fall-through to static/JWT.
    r = await api.get("/me", headers=_bearer("fw_ghosttoken"))
    assert r.status_code == 401


async def test_revoked_key_cross_user(
    api_with_users: tuple[AsyncClient, str, str],
) -> None:
    """Revoking a key that belongs to a different user must 404, not
    silently succeed (otherwise Bob could destroy Alice's keys via
    id-guessing)."""
    api, alice_id, bob_id = api_with_users
    # Root creates a key for alice.
    r = await api.post(
        f"/users/{alice_id}/api-keys",
        headers=_basic("root", "root-password!"),
        json={"label": "for-alice"},
    )
    key_id = r.json()["id"]
    # Bob tries to revoke by pretending it's his own → owner-check fails.
    r = await api.delete(
        f"/users/{bob_id}/api-keys/{key_id}", headers=_basic("bob", "bob-password")
    )
    # Own-user check passes for /users/{bob_id}/... but the key
    # belongs to alice — 404.
    assert r.status_code == 404
