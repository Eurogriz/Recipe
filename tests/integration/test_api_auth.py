"""Tests for the JWT + static-token authentication layer."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from formulation_workbench.infrastructure.config import AppSettings, reset_settings_cache
from formulation_workbench.infrastructure.db.connection import Database
from formulation_workbench.infrastructure.db.models import Base
from formulation_workbench.presentation.api.app import create_app

pytestmark = [pytest.mark.integration, pytest.mark.api]

_SECRET = "super-secret-32-byte-jwt-signing-key!"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _make_jwt(claims: dict[str, object], secret: str = _SECRET) -> str:
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode("utf-8"))
    payload = _b64url(json.dumps(claims).encode("utf-8"))
    signing_input = f"{header}.{payload}".encode("ascii")
    sig = _b64url(hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"


async def _prepare_db(path: Path) -> None:
    db = Database.from_url(url=f"sqlite+aiosqlite:///{path}")
    await db.init()
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await db.close()


async def _make_client(settings: AppSettings) -> AsyncClient:
    app = create_app(settings)
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://testserver"), app  # type: ignore[return-value]


@pytest_asyncio.fixture
async def jwt_api(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    reset_settings_cache()
    db = tmp_path / "auth.db"
    await _prepare_db(db)

    settings = AppSettings(
        environment="staging",
        database_url=f"sqlite+aiosqlite:///{db}",
        api_token="",
        jwt_secret=_SECRET,
        rate_limit_enabled=False,
    )
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


@pytest_asyncio.fixture
async def static_api(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    reset_settings_cache()
    db = tmp_path / "static.db"
    await _prepare_db(db)

    settings = AppSettings(
        environment="staging",
        database_url=f"sqlite+aiosqlite:///{db}",
        api_token="static-tok",
        jwt_secret="",
        rate_limit_enabled=False,
    )
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


async def test_health_public_even_with_jwt(jwt_api: AsyncClient) -> None:
    r = await jwt_api.get("/health")
    assert r.status_code == 200


async def test_recipes_requires_token(jwt_api: AsyncClient) -> None:
    r = await jwt_api.get("/recipes")
    assert r.status_code == 401


async def test_valid_jwt_grants_read_scope(jwt_api: AsyncClient) -> None:
    token = _make_jwt({"sub": "alice", "exp": int(time.time()) + 300, "scope": "recipes:read"})
    r = await jwt_api.get("/recipes", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


async def test_jwt_without_scope_is_forbidden_from_write(jwt_api: AsyncClient) -> None:
    token = _make_jwt({"sub": "alice", "exp": int(time.time()) + 300, "scope": "recipes:read"})
    from tests.integration.test_api_write import VALID_RECIPE

    r = await jwt_api.post(
        "/recipes", json=VALID_RECIPE, headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 403


async def test_jwt_with_write_scope_can_create(jwt_api: AsyncClient) -> None:
    token = _make_jwt(
        {
            "sub": "editor",
            "exp": int(time.time()) + 300,
            "scope": "recipes:read recipes:write",
        }
    )
    from tests.integration.test_api_write import VALID_RECIPE

    r = await jwt_api.post(
        "/recipes", json=VALID_RECIPE, headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 201


async def test_expired_jwt_rejected(jwt_api: AsyncClient) -> None:
    token = _make_jwt({"sub": "alice", "exp": int(time.time()) - 60, "scope": "recipes:read"})
    r = await jwt_api.get("/recipes", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


async def test_bad_signature_rejected(jwt_api: AsyncClient) -> None:
    token = _make_jwt({"sub": "alice", "exp": int(time.time()) + 300}, secret="wrong-secret")
    r = await jwt_api.get("/recipes", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


async def test_static_token_still_works(static_api: AsyncClient) -> None:
    r = await static_api.get("/recipes", headers={"Authorization": "Bearer static-tok"})
    assert r.status_code == 200


async def test_static_token_wrong_value(static_api: AsyncClient) -> None:
    r = await static_api.get("/recipes", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


async def test_open_mode_grants_everything(tmp_path: Path) -> None:
    reset_settings_cache()
    db = tmp_path / "open.db"
    await _prepare_db(db)
    settings = AppSettings(
        environment="development",
        database_url=f"sqlite+aiosqlite:///{db}",
        api_token="",
        jwt_secret="",
        rate_limit_enabled=False,
    )
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            from tests.integration.test_api_write import VALID_RECIPE

            r = await client.post("/recipes", json=VALID_RECIPE)
            assert r.status_code == 201
