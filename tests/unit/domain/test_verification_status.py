"""Unit tests for VerificationStatus value object.

Tests state machine and verification counting.
"""

from __future__ import annotations

import pytest

from formulation_workbench.domain.value_objects.verification_status import (
    InvalidStatusTransitionError,
    VerificationState,
    VerificationStatus,
)


class TestVerificationStatusInitialState:
    """Tests for initial state."""

    def test_default_is_draft(self) -> None:
        status = VerificationStatus()
        assert status.state == VerificationState.DRAFT
        assert status.verification_count == 0
        assert status.required_verifications == 3

    def test_custom_threshold(self) -> None:
        status = VerificationStatus(required_verifications=5)
        assert status.required_verifications == 5

    def test_invalid_state_type_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be VerificationState"):
            VerificationStatus(state="Invalid")  # type: ignore[arg-type]

    def test_negative_count_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            VerificationStatus(verification_count=-1)

    def test_zero_required_rejected(self) -> None:
        with pytest.raises(ValueError, match=">= 1"):
            VerificationStatus(required_verifications=0)


class TestStateTransitions:
    """Tests for state machine transitions."""

    def test_draft_to_pending_review(self) -> None:
        status = VerificationStatus()
        new = status.transition_to(VerificationState.PENDING_REVIEW)
        assert new.state == VerificationState.PENDING_REVIEW
        assert new.verification_count == 0

    def test_draft_to_rejected(self) -> None:
        status = VerificationStatus()
        new = status.transition_to(VerificationState.REJECTED)
        assert new.state == VerificationState.REJECTED

    def test_draft_to_verified_rejected(self) -> None:
        """Cannot skip PendingReview."""
        status = VerificationStatus()
        with pytest.raises(InvalidStatusTransitionError):
            status.transition_to(VerificationState.VERIFIED)

    def test_verified_to_pending_review_rejected(self) -> None:
        """Verified can only go back to Draft."""
        status = VerificationStatus(state=VerificationState.VERIFIED, verification_count=3)
        with pytest.raises(InvalidStatusTransitionError):
            status.transition_to(VerificationState.PENDING_REVIEW)

    def test_immutability_returns_new_instance(self) -> None:
        status = VerificationStatus()
        new = status.transition_to(VerificationState.PENDING_REVIEW)
        assert new is not status
        assert status.state == VerificationState.DRAFT  # unchanged


class TestVerificationCount:
    """Tests for verification count logic."""

    def test_single_verification_no_auto_transition(self) -> None:
        """Adding 1 verification while PendingReview doesn't auto-verify."""
        status = VerificationStatus(state=VerificationState.PENDING_REVIEW)
        new = status.add_verification()
        assert new.state == VerificationState.PENDING_REVIEW
        assert new.verification_count == 1

    def test_three_verifications_auto_transitions_to_verified(self) -> None:
        """Adding 3 verifications (default threshold) auto-transitions to VERIFIED."""
        status = VerificationStatus(state=VerificationState.PENDING_REVIEW)
        new = status.add_verification()
        new = new.add_verification()
        new = new.add_verification()
        assert new.state == VerificationState.VERIFIED
        assert new.verification_count == 3

    def test_custom_threshold(self) -> None:
        """With required_verifications=5, the 5th verification triggers VERIFIED."""
        status = VerificationStatus(
            state=VerificationState.PENDING_REVIEW, required_verifications=5
        )
        s = status
        for _i in range(4):
            s = s.add_verification()
            assert s.state == VerificationState.PENDING_REVIEW
        s = s.add_verification()
        assert s.state == VerificationState.VERIFIED
        assert s.verification_count == 5

    def test_adding_to_draft_state(self) -> None:
        """Adding verification to Draft is allowed (for completeness)."""
        status = VerificationStatus()
        new = status.add_verification()
        assert new.verification_count == 1
        # State remains Draft (since not in PendingReview)
        assert new.state == VerificationState.DRAFT


class TestCatalogVisibility:
    """Tests for catalog visibility logic."""

    def test_draft_not_visible(self) -> None:
        status = VerificationStatus(state=VerificationState.DRAFT)
        assert status.is_visible_in_main_catalog is False

    def test_pending_review_not_visible(self) -> None:
        """Per requirements, PendingReview is hidden from main catalog."""
        status = VerificationStatus(state=VerificationState.PENDING_REVIEW)
        assert status.is_visible_in_main_catalog is False

    def test_verified_visible(self) -> None:
        status = VerificationStatus(state=VerificationState.VERIFIED, verification_count=3)
        assert status.is_visible_in_main_catalog is True

    def test_rejected_not_visible(self) -> None:
        status = VerificationStatus(state=VerificationState.REJECTED)
        assert status.is_visible_in_main_catalog is False


class TestEqualityAndHashing:
    """Tests for equality and hashing."""

    def test_equal_statuses_are_equal(self) -> None:
        s1 = VerificationStatus(state=VerificationState.DRAFT, verification_count=0)
        s2 = VerificationStatus(state=VerificationState.DRAFT, verification_count=0)
        assert s1 == s2
        assert hash(s1) == hash(s2)

    def test_different_count_not_equal(self) -> None:
        s1 = VerificationStatus(state=VerificationState.DRAFT, verification_count=0)
        s2 = VerificationStatus(state=VerificationState.DRAFT, verification_count=1)
        assert s1 != s2

    def test_info_property(self) -> None:
        status = VerificationStatus(state=VerificationState.VERIFIED, verification_count=3)
        info = status.info
        assert info.state == VerificationState.VERIFIED
        assert info.verification_count == 3
