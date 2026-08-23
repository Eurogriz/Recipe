"""Integration tests for the ``/auth/login`` + ``/auth/logout`` flow.

These exercise the session cookie end-to-end, plus the underlying
``session_auth`` helpers (unit-level round-trip).
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from formulation_workbench.infrastructure.config import AppSettings, reset_settings_cache
from formulation_workbench.infrastructure.db.connection import Database
from formulation_workbench.infrastructure.db.models import Base
from formulation_workbench.infrastructure.db.repositories.users import UserRepository
from formulation_workbench.presentation.api.app import create_app
from formulation_workbench.presentation.api.session_auth import (
    SESSION_COOKIE_NAME,
    SessionTokenError,
    decode_session_token,
    issue_session_token,
)

pytestmark = [pytest.mark.integration, pytest.mark.api]


# --------------------------------------------------------------------------- unit


def test_issue_and_decode_roundtrip() -> None:
    settings = AppSettings(
        environment="development",
        session_secret="unit-test-secret-value-32-chars-min-length!",
        api_token="",
    )
    token = issue_session_token(
        subject="alice", role="Technologist", settings=settings, ttl_seconds=60
    )
    payload = decode_session_token(token, settings)
    assert payload.subject == "alice"
    assert payload.role == "Technologist"
    assert payload.expires_at > int(time.time())


def test_decode_rejects_tampered_signature() -> None:
    settings = AppSettings(
        environment="development",
        session_secret="unit-test-secret-value-32-chars-min-length!",
        api_token="",
    )
    token = issue_session_token(subject="alice", role="Viewer", settings=settings)
    tampered = token[:-4] + "AAAA"
    with pytest.raises(SessionTokenError):
        decode_session_token(tampered, settings)


def test_decode_rejects_expired_token() -> None:
    settings = AppSettings(
        environment="development",
        session_secret="unit-test-secret-value-32-chars-min-length!",
        api_token="",
    )
    token = issue_session_token(
        subject="alice",
        role="Viewer",
        settings=settings,
        ttl_seconds=1,
        issued_at=int(time.time()) - 3600,
    )
    with pytest.raises(SessionTokenError, match="expired"):
        decode_session_token(token, settings)


def test_decode_rejects_wrong_secret() -> None:
    settings_a = AppSettings(
        environment="development",
        session_secret="secret-a" * 4,
        api_token="",
    )
    settings_b = AppSettings(
        environment="development",
        session_secret="secret-b" * 4,
        api_token="",
    )
    token = issue_session_token(subject="alice", role="Viewer", settings=settings_a)
    with pytest.raises(SessionTokenError):
        decode_session_token(token, settings_b)


# --------------------------------------------------------------------------- HTTP fixture


@pytest_asyncio.fixture
async def api_with_user(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    reset_settings_cache()
    db = tmp_path / "session.db"
    dbc = Database.from_url(url=f"sqlite+aiosqlite:///{db}")
    await dbc.init()
    async with dbc.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    repo = UserRepository(dbc)
    await repo.create(username="alice", password="alice-password", role="Technologist", email="a@b")
    await dbc.close()

    settings = AppSettings(
        environment="development",
        database_url=f"sqlite+aiosqlite:///{db}",
        api_token="",
        # Non-empty session_secret so we don't rely on the dev fallback.
        session_secret="session-secret-for-tests-32chars-x!",
        rate_limit_enabled=False,
        model_dir=tmp_path / "models",
    )
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


# --------------------------------------------------------------------------- e2e


async def test_login_sets_cookie(api_with_user: AsyncClient) -> None:
    r = await api_with_user.post(
        "/auth/login",
        json={"username": "alice", "password": "alice-password"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["subject"] == "user:alice"
    assert body["role"] == "Technologist"
    assert "recipes:read" in body["scopes"]
    # Cookie set on the response.
    assert SESSION_COOKIE_NAME in r.cookies
    # httpx follows Set-Cookie into its cookie jar.
    assert SESSION_COOKIE_NAME in api_with_user.cookies


async def test_login_rejects_wrong_password(api_with_user: AsyncClient) -> None:
    r = await api_with_user.post("/auth/login", json={"username": "alice", "password": "nope"})
    assert r.status_code == 401
    assert SESSION_COOKIE_NAME not in r.cookies


async def test_login_rejects_unknown_user(api_with_user: AsyncClient) -> None:
    r = await api_with_user.post("/auth/login", json={"username": "ghost", "password": "whatever"})
    assert r.status_code == 401


async def test_me_uses_session_cookie(api_with_user: AsyncClient) -> None:
    login = await api_with_user.post(
        "/auth/login", json={"username": "alice", "password": "alice-password"}
    )
    assert login.status_code == 200

    me = await api_with_user.get("/me")
    assert me.status_code == 200
    body = me.json()
    assert body["subject"] == "user:alice"
    assert body["mode"] == "session"
    assert body["role"] == "Technologist"


async def test_logout_clears_cookie(api_with_user: AsyncClient) -> None:
    await api_with_user.post(
        "/auth/login", json={"username": "alice", "password": "alice-password"}
    )
    assert SESSION_COOKIE_NAME in api_with_user.cookies

    r = await api_with_user.post("/auth/logout")
    assert r.status_code == 204
    # Browser drops the cookie on receipt of the delete instruction.
    # httpx models this by clearing its own jar entry.
    assert SESSION_COOKIE_NAME not in api_with_user.cookies

    # Follow-up /me falls back to open mode.
    me = await api_with_user.get("/me")
    assert me.json()["mode"] == "open"


async def test_logout_is_idempotent(api_with_user: AsyncClient) -> None:
    r = await api_with_user.post("/auth/logout")
    assert r.status_code == 204
    r = await api_with_user.post("/auth/logout")
    assert r.status_code == 204


async def test_invalid_cookie_falls_through_to_open(api_with_user: AsyncClient) -> None:
    """A tampered cookie must not silently authenticate the caller."""
    api_with_user.cookies.set(SESSION_COOKIE_NAME, "garbage.token")
    r = await api_with_user.get("/me")
    assert r.status_code == 200
    body = r.json()
    # Falls through to open mode — but the cookie is definitely NOT treated
    # as a valid session.
    assert body["mode"] == "open"
