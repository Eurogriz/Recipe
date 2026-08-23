"""Read-side repository for the ``audit_log_entry`` table.

The write path uses :class:`SqlAlchemyAuditLogger` (a session-scoped
port implementation), but the UI needs a query API that can filter by
recipe, actor, or action and paginate — which does not fit the
``AuditLogger`` port abstraction.  So we ship a small, purpose-built
read-only repository here and expose it through the DI container.

Every row is returned as a plain dataclass (:class:`AuditLogRecord`)
so the API layer can turn it into a Pydantic DTO without leaking the
SQLAlchemy models to the presentation layer.

The ``changes`` field is decoded from JSON eagerly: keeping it as a
string all the way to the client saves a few CPU cycles but forces
the UI to duplicate JSON.parse everywhere.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from ..connection import Database
from ..models import AuditLogEntryModel

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AuditLogRecord:
    """Read-side representation of one ``audit_log_entry`` row."""

    id: str
    recipe_id: str
    user_id: str | None
    actor_label: str
    action: str
    changes: dict[str, Any] | None
    timestamp: datetime
    ip_address: str | None


@dataclass(frozen=True, slots=True)
class AuditLogPage:
    """Page of audit log rows + total count for cursor-free pagination."""

    total: int
    entries: list[AuditLogRecord]


class AuditLogRepository:
    """Read-only queries over ``audit_log_entry``.

    Kept intentionally tiny — anything that needs a write goes through
    :class:`SqlAlchemyAuditLogger` (see the ``AuditLogger`` port),
    which is invoked inside every domain use case's session scope.
    """

    def __init__(self, database: Database) -> None:
        self._database = database

    async def list_recent(
        self,
        *,
        recipe_id: str | None = None,
        actor: str | None = None,
        action: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> AuditLogPage:
        """Return the most recent audit rows matching the filters.

        Filters are combined with AND.  Rows are ordered by timestamp
        DESC so the newest event is first — the UI paginates forward
        from row 0.
        """
        # Clamp to sane bounds so a mis-typed URL cannot DOS us.
        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))

        stmt = select(AuditLogEntryModel)
        count_stmt = select(func.count()).select_from(AuditLogEntryModel)
        if recipe_id:
            stmt = stmt.where(AuditLogEntryModel.recipe_id == recipe_id)
            count_stmt = count_stmt.where(AuditLogEntryModel.recipe_id == recipe_id)
        if actor:
            stmt = stmt.where(AuditLogEntryModel.actor_label == actor)
            count_stmt = count_stmt.where(AuditLogEntryModel.actor_label == actor)
        if action:
            stmt = stmt.where(AuditLogEntryModel.action == action)
            count_stmt = count_stmt.where(AuditLogEntryModel.action == action)
        stmt = stmt.order_by(AuditLogEntryModel.timestamp.desc()).limit(limit).offset(offset)

        async with self._database.session() as session:
            rows = (await session.execute(stmt)).scalars().all()
            total = int((await session.execute(count_stmt)).scalar_one())

        return AuditLogPage(
            total=total,
            entries=[_to_record(r) for r in rows],
        )

    async def distinct_actions(self) -> list[str]:
        """List every unique action name — used by the UI filter dropdown."""
        stmt = select(AuditLogEntryModel.action).distinct().order_by(AuditLogEntryModel.action)
        async with self._database.session() as session:
            rows = (await session.execute(stmt)).scalars().all()
        return [r for r in rows if r]


def _to_record(row: AuditLogEntryModel) -> AuditLogRecord:
    changes: dict[str, Any] | None = None
    if row.changes_json:
        try:
            parsed = json.loads(row.changes_json)
        except json.JSONDecodeError:
            # Log at debug so a corrupt row does not spam production
            # logs, but keep the row visible in the UI so an operator
            # can spot it (empty ``changes`` dict).
            logger.debug("audit_row_bad_json", extra={"row_id": row.id})
            parsed = None
        if isinstance(parsed, dict):
            changes = parsed
    return AuditLogRecord(
        id=row.id,
        recipe_id=row.recipe_id,
        user_id=row.user_id,
        actor_label=row.actor_label,
        action=row.action,
        changes=changes,
        timestamp=row.timestamp,
        ip_address=row.ip_address,
    )


__all__ = ["AuditLogPage", "AuditLogRecord", "AuditLogRepository"]
