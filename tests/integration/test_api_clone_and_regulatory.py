"""Integration tests for POST /recipes/{id}/clone and /catalog/regulatory-scan."""

from __future__ import annotations

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


def _recipe(*, subcat: str = "test", pigment_cas: str = "13463-67-7") -> dict:
    return {
        "category": "Краски",
        "subcategory": subcat,
        "binder_type": "Acrylic",
        "product_class": "Standard",
        "intended_use": "Test",
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
                        "mass_percent": 50.0,
                    },
                    {
                        "name": "Binder",
                        "cas_number": "mixture",
                        "function": "binder",
                        "mass_percent": 30.0,
                    },
                    {
                        "name": "Pigment",
                        "cas_number": pigment_cas,
                        "function": "pigment",
                        "mass_percent": 20.0,
                    },
                ],
                "process": {"equipment": "Disperser"},
            }
        ],
        "primary_source": {
            "authors": "Flick",
            "title": "WBPF",
            "year": 1995,
            "publisher": "Noyes Publications",
            "isbn": "9780815513773",
        },
        "cross_references": [],
    }


@pytest_asyncio.fixture
async def api(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    reset_settings_cache()
    db = tmp_path / "clone.db"
    dbc = Database.from_url(url=f"sqlite+aiosqlite:///{db}")
    await dbc.init()
    async with dbc.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
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


# --------------------------------------------------------------------------- clone


async def test_clone_creates_fresh_draft_with_new_id(api: AsyncClient) -> None:
    src = (await api.post("/recipes", json=_recipe())).json()["id"]
    r = await api.post(f"/recipes/{src}/clone")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["id"] != src
    assert body["status"] == "Draft"
    assert body["version"] == 1
    assert body["verification_count"] == 0


async def test_clone_preserves_composition(api: AsyncClient) -> None:
    src = (await api.post("/recipes", json=_recipe(subcat="original"))).json()["id"]
    clone_id = (await api.post(f"/recipes/{src}/clone")).json()["id"]

    src_full = (await api.get(f"/recipes/{src}/full")).json()
    clone_full = (await api.get(f"/recipes/{clone_id}/full")).json()

    assert clone_full["subcategory"] == src_full["subcategory"]
    assert clone_full["binder_type"] == src_full["binder_type"]
    assert len(clone_full["stages"]) == len(src_full["stages"])
    # Same components with identical mass percentages.
    src_comps = {
        (c["name"], round(c["mass_percent"], 4))
        for s in src_full["stages"]
        for c in s["components"]
    }
    clone_comps = {
        (c["name"], round(c["mass_percent"], 4))
        for s in clone_full["stages"]
        for c in s["components"]
    }
    assert src_comps == clone_comps


async def test_clone_404_on_unknown_source(api: AsyncClient) -> None:
    r = await api.post("/recipes/does-not-exist/clone")
    assert r.status_code == 404


# --------------------------------------------------------------------------- regulatory scan


async def test_regulatory_scan_returns_empty_when_no_data(api: AsyncClient) -> None:
    r = await api.get("/catalog/regulatory-scan")
    assert r.status_code == 200
    body = r.json()
    # No CSV loaded in tests → checker is None → empty result.
    assert body["n_offending"] == 0
    assert body["findings"] == []


async def test_regulatory_scan_finds_dehp_phthalate(api: AsyncClient, tmp_path: Path) -> None:
    """A recipe using CAS 117-81-7 (DEHP, a SVHC phthalate) must
    show up in the scan; a clean TiO2 recipe must not.
    """
    from formulation_workbench.domain.services.regulatory import (
        RegulatoryComplianceChecker,
    )

    checker = RegulatoryComplianceChecker()
    rid_clean = (await api.post("/recipes", json=_recipe(subcat="clean"))).json()["id"]
    rid_dehp = (
        await api.post(
            "/recipes",
            json=_recipe(subcat="dehp", pigment_cas="117-81-7"),
        )
    ).json()["id"]

    # The API only exposes the checker via the DI container; here we
    # patch the container's checker onto the app so /regulatory-scan
    # actually returns something.  The API endpoint calls
    # container.regulatory_scan.execute which reads the checker set at
    # container build time — we swap the whole use case:
    from formulation_workbench.application.use_cases.regulatory_scan import (
        RegulatoryScanUseCase,
    )

    container = api._transport.app.state.container  # type: ignore[attr-defined]
    container.regulatory_scan = RegulatoryScanUseCase(container.recipe_repository, checker)

    r = await api.get("/catalog/regulatory-scan")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["n_scanned"] == 2
    ids = [f["recipe_id"] for f in body["findings"]]
    assert rid_dehp in ids
    assert rid_clean not in ids
    hit = next(f for f in body["findings"] if f["recipe_id"] == rid_dehp)
    assert hit["errors"] >= 1 or hit["warnings"] >= 1
    assert hit["top_substances"], "expected at least one top substance"


async def test_regulatory_scan_error_only_filter(
    api: AsyncClient,
) -> None:
    from formulation_workbench.application.use_cases.regulatory_scan import (
        RegulatoryScanUseCase,
    )
    from formulation_workbench.domain.services.regulatory import (
        RegulatoryComplianceChecker,
    )

    await api.post("/recipes", json=_recipe(subcat="dehp", pigment_cas="117-81-7"))
    container = api._transport.app.state.container  # type: ignore[attr-defined]
    container.regulatory_scan = RegulatoryScanUseCase(
        container.recipe_repository, RegulatoryComplianceChecker()
    )

    # min_severity=warning → всё
    all_hits = (await api.get("/catalog/regulatory-scan?min_severity=warning")).json()
    # min_severity=error → только строки с ≥1 error
    err_hits = (await api.get("/catalog/regulatory-scan?min_severity=error")).json()
    assert err_hits["n_offending"] <= all_hits["n_offending"]
    for row in err_hits["findings"]:
        assert row["errors"] >= 1
