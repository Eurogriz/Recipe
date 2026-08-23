"""Domain events.

Domain events are facts about things that happened in the past.
They are emitted by aggregates and consumed by the application layer
(e.g., to trigger audit log entries, notifications, etc.).

This is a pure value-object representation of events — no I/O.
The actual dispatching is done by an event bus in the application layer.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True, slots=True)
class DomainEvent:
    """Base class for all domain events."""

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    event_type: str = ""
    aggregate_id: str = ""
    actor: str = ""  # user_id or system identifier
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.event_type:
            raise ValueError("event_type must be set")


@dataclass(frozen=True, slots=True)
class RecipeCreated(DomainEvent):
    """Emitted when a new recipe is created."""

    event_type: str = field(default="recipe.created", init=False)
    recipe_category: str = ""
    recipe_subcategory: str = ""
    product_class: str = ""


@dataclass(frozen=True, slots=True)
class RecipeUpdated(DomainEvent):
    """Emitted when a recipe is updated."""

    event_type: str = field(default="recipe.updated", init=False)
    changes_summary: str = ""


@dataclass(frozen=True, slots=True)
class RecipeSubmittedForReview(DomainEvent):
    """Emitted when a recipe is submitted for verification."""

    event_type: str = field(default="recipe.submitted_for_review", init=False)


@dataclass(frozen=True, slots=True)
class RecipeVerified(DomainEvent):
    """Emitted when a verification is added (or recipe achieves VERIFIED state)."""

    event_type: str = field(default="recipe.verified", init=False)
    verification_count: int = 0
    required_verifications: int = 0
    reached_threshold: bool = False


@dataclass(frozen=True, slots=True)
class RecipeRejected(DomainEvent):
    """Emitted when a recipe is rejected."""

    event_type: str = field(default="recipe.rejected", init=False)
    reason: str = ""


@dataclass(frozen=True, slots=True)
class RecipeVersionCreated(DomainEvent):
    """Emitted when a new version of a verified recipe is created."""

    event_type: str = field(default="recipe.version_created", init=False)
    previous_version_id: str = ""
    new_version: int = 0
