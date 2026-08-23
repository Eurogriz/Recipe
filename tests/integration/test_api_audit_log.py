"""Integration tests for ``GET /audit-log``.

We generate audit rows by exercising the real write path (create +
verify a recipe), then read them back through the API and check the
filter/pagination behaviour.
"""

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
from formulation_workbench.infrastructure.db.repositories.users import UserRepository
from formulation_workbench.presentation.api.app import create_app

pytestmark = [pytest.mark.integration, pytest.mark.api]


def _basic(username: str, password: str) -> dict[str, str]:
    raw = f"{username}:{password}".encode()
    token = base64.b64encode(raw).decode("ascii")
    return {"Authorization": f"Basic {token}"}


_RECIPE_PAYLOAD = {
    "category": "Paints",
    "subcategory": "test",
    "binder_type": "Acrylic",
    "product_class": "Standard",
    "intended_use": "Test rig",
    "stages": [
        {
            "stage_number": 1,
            "name": "Mix",
            "description": "",
            "components": [
                {
                    "name": "Water",
                    "cas_number": "7732-18-5",
                    "function": "vehicle",
                    "mass_percent": 60.0,
                    "tolerance_percent": 1.0,
                },
                {
                    "name": "Binder",
                    "cas_number": "mixture",
                    "function": "binder",
                    "mass_percent": 25.0,
                    "tolerance_percent": 1.0,
                },
                {
                    "name": "TiO2",
                    "cas_number": "13463-67-7",
                    "function": "pigment",
                    "mass_percent": 15.0,
                    "tolerance_percent": 1.0,
                },
            ],
            "process": None,
        }
    ],
    "primary_source": {
        "authors": "T",
        "title": "T",
        "year": 2020,
        "publisher": "Noyes Publications",
        "isbn": "9780815513773",
        "citation_type": "book",
    },
    "actor": "seed",
}


@pytest_asyncio.fixture
async def api_with_admin(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    reset_settings_cache()
    db = tmp_path / "audit.db"
    dbc = Database.from_url(url=f"sqlite+aiosqlite:///{db}")
    await dbc.init()
    async with dbc.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    repo = UserRepository(dbc)
    await repo.create(username="root", password="root-password!", role="Admin")
    await repo.create(username="viewer", password="viewer-password", role="Viewer")
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
            yield client


async def test_audit_log_empty_returns_empty_page(
    api_with_admin: AsyncClient,
) -> None:
    r = await api_with_admin.get("/audit-log", headers=_basic("root", "root-password!"))
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0
    assert body["entries"] == []
    assert body["actions"] == []
    assert body["limit"] == 100
    assert body["offset"] == 0


async def test_audit_log_records_created_and_updated(
    api_with_admin: AsyncClient,
) -> None:
    headers = _basic("root", "root-password!")
    # Create → one Created row.
    r = await api_with_admin.post("/recipes", headers=headers, json=_RECIPE_PAYLOAD)
    assert r.status_code == 201, r.text
    recipe_id = r.json()["id"]

    # Update → one Updated row.
    payload = dict(_RECIPE_PAYLOAD, intended_use="Updated purpose")
    r = await api_with_admin.put(
        f"/recipes/{recipe_id}",
        headers=headers,
        json=payload,
    )
    assert r.status_code == 200, r.text

    # Read the log.
    r = await api_with_admin.get("/audit-log", headers=headers)
    body = r.json()
    assert body["total"] >= 2
    actions = [e["action"] for e in body["entries"]]
    assert "Created" in actions
    assert "Updated" in actions
    # Newest-first ordering.
    assert body["entries"][0]["action"] == "Updated"


async def test_audit_log_filters_by_recipe_id(api_with_admin: AsyncClient) -> None:
    headers = _basic("root", "root-password!")
    r1 = await api_with_admin.post("/recipes", headers=headers, json=_RECIPE_PAYLOAD)
    r2 = await api_with_admin.post("/recipes", headers=headers, json=_RECIPE_PAYLOAD)
    id1, id2 = r1.json()["id"], r2.json()["id"]

    r = await api_with_admin.get("/audit-log", headers=headers, params={"recipe_id": id1})
    body = r.json()
    assert body["total"] >= 1
    for entry in body["entries"]:
        assert entry["recipe_id"] == id1
    # Sanity: the second recipe has its own row.
    r = await api_with_admin.get("/audit-log", headers=headers, params={"recipe_id": id2})
    body = r.json()
    assert body["total"] >= 1
    for entry in body["entries"]:
        assert entry["recipe_id"] == id2


async def test_audit_log_filters_by_action(api_with_admin: AsyncClient) -> None:
    headers = _basic("root", "root-password!")
    await api_with_admin.post("/recipes", headers=headers, json=_RECIPE_PAYLOAD)
    r = await api_with_admin.get("/audit-log", headers=headers, params={"action": "Created"})
    body = r.json()
    assert body["total"] >= 1
    for entry in body["entries"]:
        assert entry["action"] == "Created"


async def test_audit_log_pagination(api_with_admin: AsyncClient) -> None:
    headers = _basic("root", "root-password!")
    for _ in range(3):
        await api_with_admin.post("/recipes", headers=headers, json=_RECIPE_PAYLOAD)

    page1 = (
        await api_with_admin.get("/audit-log", headers=headers, params={"limit": 2, "offset": 0})
    ).json()
    page2 = (
        await api_with_admin.get("/audit-log", headers=headers, params={"limit": 2, "offset": 2})
    ).json()
    # First page carries the ``actions`` list, later pages omit it.
    assert page1["actions"]  # non-empty
    assert page2["actions"] == []
    assert len(page1["entries"]) == 2
    ids_page_1 = {e["id"] for e in page1["entries"]}
    ids_page_2 = {e["id"] for e in page2["entries"]}
    assert ids_page_1.isdisjoint(ids_page_2)


async def test_audit_log_forbidden_for_non_admin(api_with_admin: AsyncClient) -> None:
    r = await api_with_admin.get("/audit-log", headers=_basic("viewer", "viewer-password"))
    assert r.status_code == 403


async def test_audit_log_rejects_bad_pagination(api_with_admin: AsyncClient) -> None:
    headers = _basic("root", "root-password!")
    r = await api_with_admin.get("/audit-log", headers=headers, params={"limit": 0})
    assert r.status_code == 422
    r = await api_with_admin.get("/audit-log", headers=headers, params={"offset": -1})
    assert r.status_code == 422
