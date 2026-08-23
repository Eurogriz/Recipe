"""Audit Logger port.

Defines the contract for audit logging — every change to a recipe
must be logged for compliance and forensics.
"""

from __future__ import annotations

import abc
from typing import Any


class AuditLogger(abc.ABC):
    """Abstract interface for audit logging."""

    @abc.abstractmethod
    async def log(
        self,
        action: str,
        aggregate_id: str,
        actor: str,
        changes: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Log an action performed by an actor on a recipe aggregate.

        Args:
            action: One of: Created, Updated, Deleted, SubmittedForReview,
                    Verified, Rejected, VersionCreated.
            aggregate_id: The recipe ID.
            actor: User ID or system identifier.
            changes: Dictionary of changes (field → new value).
            metadata: Additional context (IP, user agent, etc.).
        """
