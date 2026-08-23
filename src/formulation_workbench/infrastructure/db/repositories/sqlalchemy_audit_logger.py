"""SQLAlchemy implementation of AuditLogger port."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....application.ports.audit_logger import AuditLogger
from ..models import AuditLogEntryModel

logger = logging.getLogger(__name__)


class SqlAlchemyAuditLogger(AuditLogger):
    """SQLAlchemy implementation that writes audit log to the audit_log_entry table.

    This is a critical compliance feature — every state change is recorded with
    the actor (user), timestamp, and changes for full forensic traceability.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def log(
        self,
        action: str,
        aggregate_id: str,
        actor: str,
        changes: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Append audit log entry.

        Args:
            action: Action verb (Created, Updated, Deleted, etc.).
            aggregate_id: Recipe ID.
            actor: User ID or system identifier.
            changes: Dictionary of changes (JSON-serializable).
            metadata: Additional context.
        """
        entry = AuditLogEntryModel(
            recipe_id=aggregate_id,
            user_id=actor,
            action=action,
            changes_json=json.dumps(changes) if changes else None,
            timestamp=datetime.now(timezone.utc),
            ip_address=(metadata or {}).get("ip_address"),
        )
        self._session.add(entry)
        await self._session.flush()
        logger.info(
            "Audit log: action=%s, recipe=%s, actor=%s",
            action,
            aggregate_id[:8] + "...",
            actor,
        )
