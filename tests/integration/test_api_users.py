"""Integration tests for users/roles + HTTP Basic auth."""

from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from formulation_workbench.infrastructure.config import AppSettings, reset_settings_cache
from formulation_workbench.infrastructure.db.connection import Database
from formulation_workbench.infrastructure.db.models import Base
from formulation_workbench.infrastructure.db.repositories.users import (
    UserRepository,
    hash_password,
    role_scopes,
    verify_password,
)
from formulation_workbench.presentation.api.app import create_app

pytestmark = [pytest.mark.integration, pytest.mark.api]


# --------------------------------------------------------------------------- unit


def test_hash_and_verify_roundtrip() -> None:
    stored = hash_password("s3cret-passw0rd")
    assert stored.startswith("scrypt$")
    assert verify_password("s3cret-passw0rd", stored) is True
    assert verify_password("wrong", stored) is False


def test_hash_rejects_short_password() -> None:
    with pytest.raises(ValueError):
        hash_password("abc")


def test_role_scopes_mapping() -> None:
    assert role_scopes("Viewer") == frozenset({"recipes:read"})
    assert role_scopes("Technologist") == frozenset({"recipes:read", "recipes:write"})
    assert role_scopes("Auditor") == frozenset({"recipes:read", "recipes:write", "recipes:verify"})
    assert role_scopes("Admin") == frozenset({"*"})


def test_role_scopes_rejects_unknown() -> None:
    from formulation_workbench.infrastructure.db.repositories.users import (
        UnknownRoleError,
    )

    with pytest.raises(UnknownRoleError):
        role_scopes("Superuser")


# --------------------------------------------------------------------------- HTTP fixture


async def _seed_admin(db_url: str) -> tuple[str, str]:
    """Insert an admin user directly via the repository and return
    (username, password) for HTTP tests to use."""
    dbc = Database.from_url(url=db_url)
    await dbc.init()
    repo = UserRepository(dbc)
    await repo.create(username="root", password="root-password!", role="Admin", email="a@b")
    await dbc.close()
    return "root", "root-password!"


def _basic(username: str, password: str) -> dict[str, str]:
    """Build a HTTP Basic Authorization header."""
    raw = f"{username}:{password}".encode()
    token = base64.b64encode(raw).decode("ascii")
    return {"Authorization": f"Basic {token}"}


@pytest_asyncio.fixture
async def api_with_admin(tmp_path: Path) -> AsyncIterator[tuple[AsyncClient, dict[str, str]]]:
    reset_settings_cache()
    db = tmp_path / "users.db"
    dbc = Database.from_url(url=f"sqlite+aiosqlite:///{db}")
    await dbc.init()
    async with dbc.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await dbc.close()

    username, password = await _seed_admin(f"sqlite+aiosqlite:///{db}")
    admin_headers = _basic(username, password)

    settings = AppSettings(
        environment="development",
        database_url=f"sqlite+aiosqlite:///{db}",
        # api_token empty → auth required only when Basic is presented;
        # non-Basic requests still fall through to the anonymous open mode.
        # But guards that specifically require admin (like /users) will
        # still work because open-mode principal has scope "*".
        api_token="",
        rate_limit_enabled=False,
        model_dir=tmp_path / "models",
    )
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client, admin_headers


# --------------------------------------------------------------------------- e2e


async def test_me_returns_admin_when_basic(
    api_with_admin: tuple[AsyncClient, dict[str, str]],
) -> None:
    api, headers = api_with_admin
    r = await api.get("/me", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["subject"] == "user:root"
    assert body["mode"] == "basic"
    assert body["role"] == "Admin"
    assert "*" in body["scopes"]


async def test_me_open_mode_when_no_auth(
    api_with_admin: tuple[AsyncClient, dict[str, str]],
) -> None:
    api, _ = api_with_admin
    r = await api.get("/me")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "open"
    assert body["role"] is None


async def test_users_crud_flow(
    api_with_admin: tuple[AsyncClient, dict[str, str]],
) -> None:
    api, headers = api_with_admin

    # List starts with just root.
    initial = (await api.get("/users", headers=headers)).json()["users"]
    assert len(initial) == 1
    assert initial[0]["username"] == "root"

    # Create a Viewer.
    r = await api.post(
        "/users",
        headers=headers,
        json={
            "username": "alice",
            "password": "alice-password",
            "role": "Viewer",
            "email": "alice@lab",
        },
    )
    assert r.status_code == 201, r.text
    alice = r.json()
    assert alice["role"] == "Viewer"
    assert alice["is_active"] is True

    # Alice can authenticate and /me reports Viewer.
    alice_headers = _basic("alice", "alice-password")
    me = (await api.get("/me", headers=alice_headers)).json()
    assert me["role"] == "Viewer"
    assert me["scopes"] == ["recipes:read"]

    # Update alice to Technologist + change password + clear email.
    r = await api.put(
        f"/users/{alice['id']}",
        headers=headers,
        json={
            "role": "Technologist",
            "new_password": "alice-new-password",
            "email": None,
        },
    )
    assert r.status_code == 200, r.text
    updated = r.json()
    assert updated["role"] == "Technologist"
    assert updated["email"] is None

    # Old password fails.
    r = await api.get("/me", headers=alice_headers)
    assert r.status_code == 401 or r.json().get("mode") == "open"

    # New password + new scopes.
    fresh = _basic("alice", "alice-new-password")
    scopes = (await api.get("/me", headers=fresh)).json()["scopes"]
    assert set(scopes) == {"recipes:read", "recipes:write"}

    # Delete.
    r = await api.delete(f"/users/{alice['id']}", headers=headers)
    assert r.status_code == 204
    r = await api.delete(f"/users/{alice['id']}", headers=headers)
    assert r.status_code == 404


async def test_create_user_422_on_bad_role(
    api_with_admin: tuple[AsyncClient, dict[str, str]],
) -> None:
    api, headers = api_with_admin
    r = await api.post(
        "/users",
        headers=headers,
        json={"username": "bob", "password": "bob-password", "role": "SuperUser"},
    )
    assert r.status_code == 422


async def test_invalid_basic_returns_401(
    api_with_admin: tuple[AsyncClient, dict[str, str]],
) -> None:
    api, _ = api_with_admin
    wrong = _basic("root", "wrong-password")
    r = await api.get("/me", headers=wrong)
    assert r.status_code == 401


async def test_non_admin_cannot_list_users(
    api_with_admin: tuple[AsyncClient, dict[str, str]],
) -> None:
    api, headers = api_with_admin
    # First create a Viewer.
    await api.post(
        "/users",
        headers=headers,
        json={
            "username": "carol",
            "password": "carol-password",
            "role": "Viewer",
        },
    )
    carol_headers = _basic("carol", "carol-password")
    r = await api.get("/users", headers=carol_headers)
    assert r.status_code == 403
