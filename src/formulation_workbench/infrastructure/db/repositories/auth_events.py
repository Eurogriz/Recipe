"""Standalone writer for auth-facing audit-log entries.

The domain ``AuditLogger`` port is session-scoped (it hooks into the
per-use-case UnitOfWork) and always requires a ``recipe_id``.  Auth
events (Login, Logout, LoginFailed, ApiKeyIssued, ApiKeyRevoked)
don't fit either constraint: they run outside a domain use-case and
have no recipe to point at.

This helper writes such rows directly, in its own transaction.  It
is intentionally chatty in what it records (actor label, IP address,
extra changes dict) so an incident-response walk-through has enough
context without joining half the schema.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..connection import Database
from ..models import AuditLogEntryModel

logger = logging.getLogger(__name__)


# Whitelisted verbs.  These must be a subset of the CHECK constraint
# on ``audit_log_entry.action`` (see migration 0006).
_AUTH_ACTIONS: frozenset[str] = frozenset(
    {"Login", "LoginFailed", "Logout", "ApiKeyIssued", "ApiKeyRevoked"}
)


@dataclass(frozen=True, slots=True)
class AuthEvent:
    """Minimal DTO an endpoint fills in when it wants to audit auth."""

    action: str
    actor_label: str
    user_id: str | None = None
    ip_address: str | None = None
    changes: dict[str, Any] | None = None


class AuthEventLogger:
    """Writes auth events into ``audit_log_entry`` in its own tx."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def log(self, event: AuthEvent) -> None:
        """Append ``event`` to the audit log.  Never raises upward.

        Auth logging is best-effort: a login attempt must not fail
        because the audit sink is unavailable.  We swallow errors
        after logging them at WARNING level so an operator still
        sees the incident, and the login flow itself keeps working.
        """
        if event.action not in _AUTH_ACTIONS:
            # Programming error, not a runtime failure — fail fast so
            # a typo doesn't silently drop rows on the floor.
            raise ValueError(
                f"unknown auth action: {event.action!r}, expected one of {sorted(_AUTH_ACTIONS)}"
            )
        try:
            async with self._database.session() as session:
                row = AuditLogEntryModel(
                    id=uuid.uuid4().hex,
                    recipe_id=None,
                    user_id=event.user_id,
                    actor_label=event.actor_label or "anonymous",
                    action=event.action,
                    changes_json=json.dumps(event.changes) if event.changes else None,
                    timestamp=datetime.now(timezone.utc),
                    ip_address=event.ip_address,
                )
                session.add(row)
                await session.commit()
        except Exception:  # pragma: no cover — best-effort
            logger.warning(
                "auth_event_write_failed",
                extra={"action": event.action, "actor": event.actor_label},
                exc_info=True,
            )


__all__ = ["AuthEvent", "AuthEventLogger"]
