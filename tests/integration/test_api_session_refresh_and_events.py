"""Tests for the sliding session refresh middleware and auth-event logging.

The two features shipped together in v1.18.0 and touch the same
plumbing (session cookies + audit_log_entry), so their tests share
a fixture.
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
    SessionPayload,
    issue_session_token,
    needs_refresh,
)

pytestmark = [pytest.mark.integration, pytest.mark.api]


# --------------------------------------------------------------------------- unit


def test_needs_refresh_at_half_ttl() -> None:
    now = 1_000_000
    fresh = SessionPayload(subject="a", role="Viewer", expires_at=now + 3600)
    stale = SessionPayload(subject="a", role="Viewer", expires_at=now + 100)
    # Full TTL 3600, fresh sits at full — no refresh.
    assert needs_refresh(fresh, ttl_seconds=3600, now=now) is False
    # Stale sits well under half → refresh.
    assert needs_refresh(stale, ttl_seconds=3600, now=now) is True


def test_needs_refresh_exact_boundary() -> None:
    now = 1_000_000
    # Remaining == ttl * fraction → boundary should NOT trigger
    # (strict less-than in the implementation).
    boundary = SessionPayload(subject="a", role="Viewer", expires_at=now + 1800)
    assert needs_refresh(boundary, ttl_seconds=3600, fraction=0.5, now=now) is False


# --------------------------------------------------------------------------- HTTP fixture


@pytest_asyncio.fixture
async def api_with_user(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    reset_settings_cache()
    db = tmp_path / "sess.db"
    dbc = Database.from_url(url=f"sqlite+aiosqlite:///{db}")
    await dbc.init()
    async with dbc.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    repo = UserRepository(dbc)
    await repo.create(username="alice", password="alice-password", role="Technologist")
    await repo.create(username="root", password="root-password!", role="Admin")
    await dbc.close()

    settings = AppSettings(
        environment="development",
        database_url=f"sqlite+aiosqlite:///{db}",
        api_token="",
        session_secret="test-session-secret-32-chars-x!x",
        rate_limit_enabled=False,
        model_dir=tmp_path / "models",
    )
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


# --------------------------------------------------------------------------- refresh middleware


async def test_fresh_cookie_is_not_refreshed(api_with_user: AsyncClient) -> None:
    r = await api_with_user.post(
        "/auth/login", json={"username": "alice", "password": "alice-password"}
    )
    assert r.status_code == 200

    r = await api_with_user.get("/me")
    assert r.status_code == 200
    # Freshly-issued cookie is above the refresh threshold →
    # middleware must not re-set it.
    assert "x-session-refreshed" not in r.headers


async def test_stale_cookie_gets_refreshed(api_with_user: AsyncClient) -> None:
    # Hand-craft a cookie whose ``exp`` sits below the half-TTL
    # threshold (well under 6 hours remaining).
    settings = AppSettings(
        environment="development",
        session_secret="test-session-secret-32-chars-x!x",
        api_token="",
    )
    now = int(time.time())
    stale = issue_session_token(
        subject="alice",
        role="Technologist",
        settings=settings,
        # Issued long ago: only 100 seconds of the 12h TTL remain.
        ttl_seconds=100,
        issued_at=now - 10,
    )
    api_with_user.cookies.set(SESSION_COOKIE_NAME, stale)
    r = await api_with_user.get("/me")
    assert r.status_code == 200
    assert r.headers.get("x-session-refreshed") == "1"
    # The Set-Cookie header on this response carries a token that
    # differs from the one we sent — that's the refreshed session.
    set_cookie = r.headers.get("set-cookie", "")
    assert SESSION_COOKIE_NAME in set_cookie
    assert stale not in set_cookie


async def test_logout_response_is_not_refreshed(api_with_user: AsyncClient) -> None:
    """A /auth/logout response contains its own Set-Cookie=delete;
    the refresh middleware must not stomp on it with a new token."""
    await api_with_user.post(
        "/auth/login", json={"username": "alice", "password": "alice-password"}
    )
    r = await api_with_user.post("/auth/logout")
    assert r.status_code == 204
    # After logout the cookie is cleared on the client side.
    assert SESSION_COOKIE_NAME not in api_with_user.cookies


# --------------------------------------------------------------------------- auth events


async def test_login_writes_login_event(api_with_user: AsyncClient) -> None:
    await api_with_user.post(
        "/auth/login", json={"username": "alice", "password": "alice-password"}
    )
    # As Admin, read /audit-log for auth events.
    from base64 import b64encode

    admin = {"Authorization": "Basic " + b64encode(b"root:root-password!").decode()}
    r = await api_with_user.get("/audit-log?action=Login", headers=admin)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    entry = body["entries"][0]
    assert entry["action"] == "Login"
    assert entry["actor_label"] == "user:alice"
    assert entry["recipe_id"] is None
    assert (entry["changes"] or {}).get("role") == "Technologist"


async def test_failed_login_writes_login_failed_event(
    api_with_user: AsyncClient,
) -> None:
    r = await api_with_user.post("/auth/login", json={"username": "alice", "password": "wrong"})
    assert r.status_code == 401

    from base64 import b64encode

    admin = {"Authorization": "Basic " + b64encode(b"root:root-password!").decode()}
    r = await api_with_user.get("/audit-log?action=LoginFailed", headers=admin)
    body = r.json()
    assert body["total"] >= 1
    entry = body["entries"][0]
    assert entry["action"] == "LoginFailed"
    assert entry["actor_label"] == "alice"
    assert (entry["changes"] or {}).get("reason") == "bad_credentials"


async def test_logout_writes_event_only_for_session(
    api_with_user: AsyncClient,
) -> None:
    from base64 import b64encode

    admin = {"Authorization": "Basic " + b64encode(b"root:root-password!").decode()}

    # Anonymous logout — must not write anything.
    r = await api_with_user.post("/auth/logout")
    assert r.status_code == 204
    body = (await api_with_user.get("/audit-log?action=Logout", headers=admin)).json()
    assert body["total"] == 0

    # Real login + logout writes exactly one Logout row.
    await api_with_user.post(
        "/auth/login", json={"username": "alice", "password": "alice-password"}
    )
    r = await api_with_user.post("/auth/logout")
    assert r.status_code == 204
    body = (await api_with_user.get("/audit-log?action=Logout", headers=admin)).json()
    assert body["total"] == 1
    entry = body["entries"][0]
    assert entry["actor_label"] == "user:alice"


async def test_api_key_events_appear_in_audit_log(
    api_with_user: AsyncClient,
) -> None:
    from base64 import b64encode

    admin_h = {"Authorization": "Basic " + b64encode(b"root:root-password!").decode()}
    # Find alice's id.
    users = (await api_with_user.get("/users", headers=admin_h)).json()["users"]
    alice_id = next(u["id"] for u in users if u["username"] == "alice")

    r = await api_with_user.post(
        f"/users/{alice_id}/api-keys",
        headers=admin_h,
        json={"label": "cron"},
    )
    key_id = r.json()["id"]
    r = await api_with_user.delete(f"/users/{alice_id}/api-keys/{key_id}", headers=admin_h)
    assert r.status_code == 204

    issued = (await api_with_user.get("/audit-log?action=ApiKeyIssued", headers=admin_h)).json()
    assert issued["total"] == 1
    assert issued["entries"][0]["actor_label"] == "user:root"
    assert (issued["entries"][0]["changes"] or {}).get("target_user") == "alice"

    revoked = (await api_with_user.get("/audit-log?action=ApiKeyRevoked", headers=admin_h)).json()
    assert revoked["total"] == 1
