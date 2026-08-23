"""Verification Status value object.

State machine for recipe verification workflow:
    Draft → PendingReview → Verified (with 3+ verifications)
    Any state can transition to Rejected (by Admin/Auditor)

A Verified recipe is logically immutable — any change creates a new version.
"""

from __future__ import annotations

from enum import Enum
from typing import NamedTuple


class InvalidStatusTransitionError(ValueError):
    """Raised when attempting an invalid state transition."""


class VerificationState(str, Enum):
    """Possible states of a recipe in the verification workflow."""

    DRAFT = "Draft"
    PENDING_REVIEW = "PendingReview"
    VERIFIED = "Verified"
    REJECTED = "Rejected"


# Allowed state transitions
_ALLOWED_TRANSITIONS: dict[VerificationState, frozenset[VerificationState]] = {
    VerificationState.DRAFT: frozenset(
        {VerificationState.PENDING_REVIEW, VerificationState.REJECTED}
    ),
    VerificationState.PENDING_REVIEW: frozenset(
        {VerificationState.VERIFIED, VerificationState.REJECTED, VerificationState.DRAFT}
    ),
    VerificationState.VERIFIED: frozenset(
        {VerificationState.DRAFT}
    ),  # Verified → Draft creates a new version
    VerificationState.REJECTED: frozenset(
        {VerificationState.DRAFT, VerificationState.PENDING_REVIEW}
    ),
}


class VerificationInfo(NamedTuple):
    """Tuple of (state, verification_count) for easy comparison."""

    state: VerificationState
    verification_count: int


class VerificationStatus:
    """Value object representing verification state.

    Immutable. State transitions return new instances.

    Attributes:
        state: Current verification state.
        verification_count: Number of independent verifications accumulated.
        required_verifications: Threshold for VERIFIED state (default 3).
    """

    def __init__(
        self,
        state: VerificationState = VerificationState.DRAFT,
        verification_count: int = 0,
        required_verifications: int = 3,
    ) -> None:
        if not isinstance(state, VerificationState):
            raise ValueError(f"State must be VerificationState, got {type(state).__name__}")
        if verification_count < 0:
            raise ValueError(f"Verification count must be non-negative, got {verification_count}")
        if required_verifications < 1:
            raise ValueError(f"Required verifications must be >= 1, got {required_verifications}")

        self._state = state
        self._verification_count = verification_count
        self._required_verifications = required_verifications

    @property
    def state(self) -> VerificationState:
        return self._state

    @property
    def verification_count(self) -> int:
        return self._verification_count

    @property
    def required_verifications(self) -> int:
        return self._required_verifications

    @property
    def info(self) -> VerificationInfo:
        return VerificationInfo(self._state, self._verification_count)

    @property
    def is_verified(self) -> bool:
        return self._state == VerificationState.VERIFIED

    @property
    def is_visible_in_main_catalog(self) -> bool:
        """Whether this status should be shown in the main recipe catalog."""
        return self._state in {VerificationState.VERIFIED}

    def can_transition_to(self, target: VerificationState) -> bool:
        return target in _ALLOWED_TRANSITIONS[self._state]

    def transition_to(self, target: VerificationState) -> VerificationStatus:
        """Create a new VerificationStatus after a state transition.

        Raises InvalidStatusTransitionError if transition is not allowed.
        """
        if not self.can_transition_to(target):
            raise InvalidStatusTransitionError(
                f"Invalid transition: {self._state.value} → {target.value}. "
                f"Allowed from {self._state.value}: "
                f"{sorted(s.value for s in _ALLOWED_TRANSITIONS[self._state])}"
            )

        # If transitioning to Verified, ensure we have enough verifications
        if target == VerificationState.VERIFIED:
            if self._verification_count < self._required_verifications:
                raise InvalidStatusTransitionError(
                    f"Cannot transition to Verified: only "
                    f"{self._verification_count}/{self._required_verifications} "
                    f"verifications accumulated."
                )

        # Reset verification count when going back to Draft
        new_count = 0 if target == VerificationState.DRAFT else self._verification_count

        return VerificationStatus(
            state=target,
            verification_count=new_count,
            required_verifications=self._required_verifications,
        )

    def add_verification(self) -> VerificationStatus:
        """Increment verification count. Returns new instance.

        If threshold reached and state is PENDING_REVIEW, automatically
        transitions to VERIFIED.
        """
        new_count = self._verification_count + 1
        new_state = self._state

        if (
            self._state == VerificationState.PENDING_REVIEW
            and new_count >= self._required_verifications
        ):
            new_state = VerificationState.VERIFIED

        return VerificationStatus(
            state=new_state,
            verification_count=new_count,
            required_verifications=self._required_verifications,
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, VerificationStatus):
            return NotImplemented
        return (
            self._state == other._state
            and self._verification_count == other._verification_count
            and self._required_verifications == other._required_verifications
        )

    def __hash__(self) -> int:
        return hash((self._state, self._verification_count, self._required_verifications))

    def __repr__(self) -> str:
        return (
            f"VerificationStatus(state={self._state.value}, "
            f"count={self._verification_count}/{self._required_verifications})"
        )
