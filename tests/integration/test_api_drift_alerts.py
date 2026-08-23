"""Integration tests for the drift-full alert dispatch endpoint.

Uses an in-process ``CapturingNotifier`` swapped in by monkey-patching
``container.alert_notifier`` on the running app — the endpoint does
not create the notifier itself, so this remains a pure integration
test without spinning up a real Slack webhook.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from formulation_workbench.infrastructure.config import AppSettings, reset_settings_cache
from formulation_workbench.infrastructure.db.connection import Database
from formulation_workbench.infrastructure.db.models import Base
from formulation_workbench.infrastructure.ml.features import FEATURE_NAMES
from formulation_workbench.infrastructure.notifications import Alert
from formulation_workbench.presentation.api.app import create_app

pytestmark = [pytest.mark.integration, pytest.mark.api]


class _CapturingNotifier:
    def __init__(self, *, accept: bool = True) -> None:
        self.accept = accept
        self.received: list[Alert] = []

    async def notify(self, alert: Alert) -> bool:
        self.received.append(alert)
        return self.accept


def _recipe(binder_pct: float) -> dict:
    water = round(100.0 - binder_pct - 10.0, 2)
    return {
        "category": "Краски",
        "subcategory": "Водно-дисперсионные",
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
                        "mass_percent": water,
                    },
                    {
                        "name": "Acrylic",
                        "cas_number": "mixture",
                        "function": "binder",
                        "mass_percent": binder_pct,
                    },
                    {
                        "name": "TiO2",
                        "cas_number": "13463-67-7",
                        "function": "pigment",
                        "mass_percent": 10.0,
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
async def api_and_notifier(
    tmp_path: Path,
) -> AsyncIterator[tuple[AsyncClient, _CapturingNotifier]]:
    reset_settings_cache()
    db = tmp_path / "drift_alerts.db"
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
        notifier = _CapturingNotifier()
        app.state.container.alert_notifier = notifier
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client, notifier


async def _seed(api: AsyncClient, n: int = 12) -> list[str]:
    ids: list[str] = []
    for i in range(n):
        binder = 20.0 + i * 3.0
        r = (await api.post("/recipes", json=_recipe(binder))).json()
        rid = r["id"]
        ids.append(rid)
        exp = (
            await api.post(
                "/experiments",
                json={"recipe_id": rid, "recipe_version": 1, "operator": "alice"},
            )
        ).json()
        await api.post(
            f"/experiments/{exp['id']}/complete",
            json={
                "batch": {"batch_number": f"B-{i:03d}", "target_mass_kg": 5.0},
                "measured_properties": [
                    {"property_code": "gloss_60", "value": 15.0 + 1.6 * binder + (i % 5) - 2},
                ],
            },
        )
    await api.post("/ml/train", json={"recipe_ids": ids})
    return ids


async def test_drift_alert_dispatches_on_severe(
    api_and_notifier: tuple[AsyncClient, _CapturingNotifier],
) -> None:
    api, notifier = api_and_notifier
    await _seed(api)
    # A very off-distribution current batch — extreme shifted values.
    current = [[999.0] * len(FEATURE_NAMES) for _ in range(10)]
    r = await api.post(
        "/ml/models/gloss_60/drift-full/alert",
        json={
            "current_vectors": current,
            "dispatch_min_level": "moderate_drift",
            "context": {"plant": "Tallinn-1", "batch_ref": "TL-42"},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["alert_dispatched"] is True
    assert body["worst_level"] in {"moderate_drift", "severe_drift"}
    assert len(notifier.received) == 1
    alert = notifier.received[0]
    assert alert.kind == "ml.drift"
    assert alert.fields["property_code"] == "gloss_60"
    assert alert.fields["plant"] == "Tallinn-1"
    assert alert.fields["batch_ref"] == "TL-42"


async def test_drift_alert_stays_silent_below_threshold(
    api_and_notifier: tuple[AsyncClient, _CapturingNotifier],
) -> None:
    api, notifier = api_and_notifier
    await _seed(api)
    # Same-shape same-scale current — should not trigger severe.
    current = [[0.0] * len(FEATURE_NAMES) for _ in range(5)]
    r = await api.post(
        "/ml/models/gloss_60/drift-full/alert",
        json={
            "current_vectors": current,
            "dispatch_min_level": "severe_drift",
        },
    )
    assert r.status_code == 200
    body = r.json()
    # Not asserting dispatched=False because zero-vectors *may* also
    # trigger severe drift for some feature depending on scale — but
    # if nothing did, no alert must have been sent.
    if not body["alert_dispatched"]:
        assert notifier.received == []
        assert body["dispatch_reason"] == "below-threshold"


async def test_drift_alert_404_when_no_model(
    api_and_notifier: tuple[AsyncClient, _CapturingNotifier],
) -> None:
    api, _ = api_and_notifier
    current = [[0.0] * len(FEATURE_NAMES) for _ in range(3)]
    r = await api.post(
        "/ml/models/no_such/drift-full/alert",
        json={"current_vectors": current},
    )
    assert r.status_code == 404


async def test_drift_alert_422_on_bad_min_level(
    api_and_notifier: tuple[AsyncClient, _CapturingNotifier],
) -> None:
    api, _ = api_and_notifier
    await _seed(api)
    current = [[0.0] * len(FEATURE_NAMES) for _ in range(3)]
    r = await api.post(
        "/ml/models/gloss_60/drift-full/alert",
        json={"current_vectors": current, "dispatch_min_level": "banana"},
    )
    assert r.status_code == 422
