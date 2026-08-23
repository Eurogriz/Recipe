"""In-process asynchronous job registry for long-running ML operations.

This is intentionally lightweight — no Celery, no Redis, no broker.
Jobs are executed as ``asyncio`` tasks on the running event loop and
their state is stored in memory (with an optional JSON snapshot on
disk so operators can inspect history across a restart).

Design goals
------------
1. **Non-blocking API** — the HTTP handler returns immediately with a
   ``job_id``; the client polls ``GET /ml/jobs/{job_id}`` for status
   and result.
2. **Deterministic status vocabulary** — ``queued`` → ``running`` →
   ``succeeded`` | ``failed`` | ``cancelled``.
3. **Safe concurrency** — a single ``asyncio.Lock`` guards mutations
   to the in-memory table; the disk snapshot is written best-effort.
4. **Bounded memory** — the registry keeps at most ``max_jobs`` (LRU
   by ``created_at``); older completed jobs are pruned.
5. **Backend-agnostic payloads** — the caller supplies a coroutine
   factory that returns any JSON-serialisable object.  The registry
   does not know or care about the training pipeline.

This is not a replacement for a real work queue (no cross-process
distribution, no retries, no priority) — but it is sufficient for the
current single-node deployments that our OEM customers use and it
avoids a hard dependency on an external broker.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import traceback
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]


@dataclass(slots=True)
class JobRecord:
    """A snapshot of one job's lifecycle.

    ``result`` and ``error`` are mutually exclusive (a job cannot both
    succeed and fail).  ``metadata`` is a free-form dict the caller
    can use to tag the job (e.g. property_codes, requested by whom).
    """

    id: str
    kind: str
    status: JobStatus
    created_at: str  # ISO-8601 UTC
    started_at: str | None = None
    finished_at: str | None = None
    duration_seconds: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    result: Any | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class JobRegistry:
    """Manage a bounded set of in-flight and completed jobs.

    Thread-safety: the registry is designed for a single asyncio event
    loop.  Cross-thread access is not supported.
    """

    def __init__(
        self,
        *,
        snapshot_path: Path | None = None,
        max_jobs: int = 500,
    ) -> None:
        self._jobs: dict[str, JobRecord] = {}
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._lock = asyncio.Lock()
        self._snapshot_path = snapshot_path
        self._max_jobs = max_jobs

        if snapshot_path is not None and snapshot_path.exists():
            self._load_snapshot()

    # ------------------------------------------------------------------ query
    def get(self, job_id: str) -> JobRecord | None:
        return self._jobs.get(job_id)

    def list(
        self,
        *,
        status: JobStatus | None = None,
        kind: str | None = None,
        limit: int = 100,
    ) -> list[JobRecord]:
        records = list(self._jobs.values())
        records.sort(key=lambda r: r.created_at, reverse=True)
        if status is not None:
            records = [r for r in records if r.status == status]
        if kind is not None:
            records = [r for r in records if r.kind == kind]
        return records[:limit]

    # ------------------------------------------------------------------ submit
    async def submit(
        self,
        kind: str,
        coro_factory: Callable[[], Awaitable[Any]],
        *,
        metadata: dict[str, Any] | None = None,
    ) -> JobRecord:
        """Register a job and schedule it on the event loop.

        ``coro_factory`` is a zero-arg callable returning an awaitable
        (we take a factory rather than an awaitable directly so that
        the coroutine object is created after we hold the registry
        lock — avoids ``RuntimeWarning: coroutine ... was never
        awaited`` on registration failure).
        """
        async with self._lock:
            self._evict_if_needed_locked()
            job_id = uuid.uuid4().hex
            record = JobRecord(
                id=job_id,
                kind=kind,
                status="queued",
                created_at=_utcnow_iso(),
                metadata=dict(metadata or {}),
            )
            self._jobs[job_id] = record
            self._persist_locked()

        task = asyncio.create_task(self._run(record, coro_factory))
        self._tasks[job_id] = task
        return record

    async def cancel(self, job_id: str) -> bool:
        """Cancel a queued/running job (best-effort).

        For a task that was cancelled before ``_run`` had a chance to
        start we also mark the record cancelled here — the runner's
        own ``CancelledError`` handler would never fire in that case.
        """
        task = self._tasks.get(job_id)
        record = self._jobs.get(job_id)
        if task is None or record is None:
            return False
        if record.status in {"succeeded", "failed", "cancelled"}:
            return False
        task.cancel()
        # Give the event loop one turn so the task can actually observe
        # the cancellation and _run can mark the record itself.  If it
        # never started, we mark the record ourselves below.
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.sleep(0)
        if record.status in {"queued", "running"}:
            async with self._lock:
                record.status = "cancelled"
                record.finished_at = _utcnow_iso()
                if record.started_at is None:
                    record.duration_seconds = 0.0
                self._persist_locked()
        return True

    async def wait(self, job_id: str, timeout: float | None = None) -> JobRecord | None:
        """Block until ``job_id`` finishes (test/CLI helper).

        A cancellation raised inside the underlying task is treated as
        completion (the job record already reflects the cancelled
        state), not as an error to bubble up.
        """
        task = self._tasks.get(job_id)
        if task is None:
            return self._jobs.get(job_id)

        async def _await_task() -> None:
            with contextlib.suppress(asyncio.CancelledError):
                await task

        with contextlib.suppress(asyncio.TimeoutError):
            if timeout is None:
                await _await_task()
            else:
                await asyncio.wait_for(_await_task(), timeout=timeout)
        return self._jobs.get(job_id)

    async def shutdown(self, *, timeout: float = 5.0) -> None:
        """Cancel running jobs on application shutdown."""
        pending = [t for t in self._tasks.values() if not t.done()]
        for t in pending:
            t.cancel()
        if pending:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(
                    asyncio.gather(*pending, return_exceptions=True),
                    timeout=timeout,
                )

    # ------------------------------------------------------------------ internals
    async def _run(
        self,
        record: JobRecord,
        coro_factory: Callable[[], Awaitable[Any]],
    ) -> None:
        start = time.perf_counter()
        async with self._lock:
            record.status = "running"
            record.started_at = _utcnow_iso()
            self._persist_locked()

        try:
            result = await coro_factory()
        except asyncio.CancelledError:
            async with self._lock:
                record.status = "cancelled"
                record.finished_at = _utcnow_iso()
                record.duration_seconds = round(time.perf_counter() - start, 3)
                self._persist_locked()
            logger.info("job_cancelled", extra={"job_id": record.id, "kind": record.kind})
            raise
        except Exception as exc:
            async with self._lock:
                record.status = "failed"
                record.error = f"{type(exc).__name__}: {exc}"
                record.finished_at = _utcnow_iso()
                record.duration_seconds = round(time.perf_counter() - start, 3)
                self._persist_locked()
            logger.exception(
                "job_failed",
                extra={
                    "job_id": record.id,
                    "kind": record.kind,
                    "traceback": traceback.format_exc(limit=5),
                },
            )
            return

        async with self._lock:
            record.status = "succeeded"
            record.result = _ensure_jsonable(result)
            record.finished_at = _utcnow_iso()
            record.duration_seconds = round(time.perf_counter() - start, 3)
            self._persist_locked()
        logger.info(
            "job_succeeded",
            extra={
                "job_id": record.id,
                "kind": record.kind,
                "duration": record.duration_seconds,
            },
        )

    def _evict_if_needed_locked(self) -> None:
        if len(self._jobs) < self._max_jobs:
            return
        # Prefer to evict terminal jobs first, oldest first.
        terminal = [
            r for r in self._jobs.values() if r.status in {"succeeded", "failed", "cancelled"}
        ]
        terminal.sort(key=lambda r: r.created_at)
        to_drop = max(1, len(self._jobs) - self._max_jobs + 1)
        for r in terminal[:to_drop]:
            self._jobs.pop(r.id, None)
            self._tasks.pop(r.id, None)

    def _persist_locked(self) -> None:
        if self._snapshot_path is None:
            return
        try:
            self._snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            payload = [r.to_dict() for r in self._jobs.values()]
            self._snapshot_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except OSError as exc:  # pragma: no cover — best-effort
            logger.warning(
                "job_snapshot_write_failed",
                extra={"path": str(self._snapshot_path), "error": str(exc)},
            )

    def _load_snapshot(self) -> None:
        assert self._snapshot_path is not None
        try:
            data = json.loads(self._snapshot_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:  # pragma: no cover
            logger.warning(
                "job_snapshot_read_failed",
                extra={"path": str(self._snapshot_path), "error": str(exc)},
            )
            return
        for row in data:
            try:
                record = JobRecord(**row)
                # A snapshot may contain a job that was still running when
                # the process died — surface it as failed rather than lie.
                if record.status in {"queued", "running"}:
                    record.status = "failed"
                    record.error = "Process restarted mid-job"
                    record.finished_at = record.finished_at or _utcnow_iso()
                self._jobs[record.id] = record
            except (TypeError, ValueError):
                continue


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _ensure_jsonable(value: Any) -> Any:
    """Coerce common non-JSON-native types into serialisable equivalents."""
    try:
        json.dumps(value, default=str)
    except TypeError:
        return json.loads(json.dumps(value, default=str))
    else:
        return value


__all__ = ["JobRecord", "JobRegistry", "JobStatus"]
