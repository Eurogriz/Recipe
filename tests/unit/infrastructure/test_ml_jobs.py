"""Unit tests for the in-process JobRegistry."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from formulation_workbench.infrastructure.ml.jobs import JobRegistry

pytestmark = [pytest.mark.unit]


async def test_submit_and_wait_success() -> None:
    reg = JobRegistry()

    async def _work() -> dict:
        await asyncio.sleep(0)
        return {"value": 42}

    record = await reg.submit(kind="test.work", coro_factory=_work)
    assert record.status in {"queued", "running"}
    final = await reg.wait(record.id, timeout=2.0)
    assert final is not None
    assert final.status == "succeeded"
    assert final.result == {"value": 42}
    assert final.duration_seconds is not None


async def test_failure_is_captured_and_surfaced() -> None:
    reg = JobRegistry()

    async def _bad() -> dict:
        raise ValueError("boom")

    record = await reg.submit(kind="test.bad", coro_factory=_bad)
    final = await reg.wait(record.id, timeout=2.0)
    assert final is not None
    assert final.status == "failed"
    assert "boom" in (final.error or "")
    assert final.result is None


async def test_cancel_pending_job() -> None:
    reg = JobRegistry()

    async def _slow() -> None:
        await asyncio.sleep(10.0)

    record = await reg.submit(kind="test.slow", coro_factory=_slow)
    ok = await reg.cancel(record.id)
    assert ok is True
    final = await reg.wait(record.id, timeout=2.0)
    assert final is not None
    assert final.status == "cancelled"


async def test_cancel_unknown_returns_false() -> None:
    reg = JobRegistry()
    ok = await reg.cancel("does-not-exist")
    assert ok is False


async def test_list_filters_by_status_and_kind() -> None:
    reg = JobRegistry()

    async def _ok() -> int:
        return 1

    async def _bad() -> int:
        raise RuntimeError("nope")

    ids = []
    for _ in range(3):
        r = await reg.submit(kind="a", coro_factory=_ok)
        ids.append(r.id)
    for _ in range(2):
        r = await reg.submit(kind="b", coro_factory=_bad)
        ids.append(r.id)

    for jid in ids:
        await reg.wait(jid, timeout=2.0)

    listed = reg.list()
    assert len(listed) == 5
    assert [r.status for r in reg.list(kind="a")] == ["succeeded"] * 3
    assert [r.status for r in reg.list(kind="b")] == ["failed"] * 2
    assert reg.list(status="succeeded", kind="a") != []


async def test_snapshot_persists_and_reloads_stale_as_failed(tmp_path: Path) -> None:
    snap = tmp_path / "jobs.json"

    reg = JobRegistry(snapshot_path=snap)

    async def _ok() -> int:
        return 5

    record = await reg.submit(kind="persist", coro_factory=_ok)
    await reg.wait(record.id, timeout=2.0)

    # Manually inject a "running" record into the snapshot to simulate
    # a process death mid-run.
    data = json.loads(snap.read_text(encoding="utf-8"))
    data.append(
        {
            "id": "ghost",
            "kind": "persist",
            "status": "running",
            "created_at": "1970-01-01T00:00:00.000Z",
            "started_at": "1970-01-01T00:00:00.000Z",
            "finished_at": None,
            "duration_seconds": None,
            "metadata": {},
            "result": None,
            "error": None,
        }
    )
    snap.write_text(json.dumps(data), encoding="utf-8")

    reg2 = JobRegistry(snapshot_path=snap)
    ghost = reg2.get("ghost")
    assert ghost is not None
    assert ghost.status == "failed"
    assert ghost.error is not None
    assert "restarted" in ghost.error.lower()
    # The previously-succeeded record survives with its result.
    assert reg2.get(record.id) is not None
    assert reg2.get(record.id).status == "succeeded"  # type: ignore[union-attr]


async def test_eviction_drops_oldest_terminal() -> None:
    reg = JobRegistry(max_jobs=3)

    async def _ok() -> int:
        return 0

    ids = []
    for _ in range(5):
        r = await reg.submit(kind="k", coro_factory=_ok)
        ids.append(r.id)
        await reg.wait(r.id, timeout=2.0)

    remaining = {r.id for r in reg.list(limit=100)}
    # The last few must be kept; the earliest must be evicted.
    assert ids[-1] in remaining
    assert ids[0] not in remaining
