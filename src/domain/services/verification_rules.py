"""Domain services for recipe verification rules.

Pure domain logic — no I/O, no infrastructure dependencies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..value_objects.verification_status import VerificationState, VerificationStatus

if TYPE_CHECKING:
    from ..entities.recipe import Recipe


class VerificationRuleViolation(Exception):
    """Raised when a recipe violates verification rules."""

    def __init__(self, rule: str, message: str) -> None:
        super().__init__(f"[{rule}] {message}")
        self.rule = rule
        self.message = message


class VerificationRules:
    """Domain service enforcing verification rules.

    Rules (documented):
        R1: Every Verified recipe must have a primary source with ISBN or DOI.
        R2: Verified recipes require at least 3 independent verifications.
        R3: Each component must have a CAS number (or explicit 'mixture'/'proprietary').
        R4: Source references must be from approved publishers/standards.
        R5: Rejected recipes cannot transition directly to Verified.
    """

    # Whitelist of approved publisher domains (for online sources)
    # and well-known standards organizations
    APPROVED_PUBLISHERS: frozenset[str] = frozenset(
        {
            "Noyes Publications",
            "Wiley",
            "Wiley-VCH",
            "Vincentz Network",
            "Hanser",
            "Springer",
            "Elsevier",
            "CRC Press",
            "Taylor & Francis",
            "ASTM International",
            "ISO",
            "DIN",
            "ГОСТ",
            "BSI",
            "AFNOR",
        }
    )

    # Whitelist of approved verification source types
    APPROVED_SOURCE_CATEGORIES: frozenset[str] = frozenset(
        {
            "book",           # Textbook or reference book (Flick, Wicks, etc.)
            "technical_bulletin",  # Manufacturer's technical data sheet
            "standard",       # ГОСТ, ISO, ASTM, DIN
            "journal_paper",  # Peer-reviewed scientific paper
            "thesis",         # PhD/Master thesis
        }
    )

    @classmethod
    def can_be_verified(cls, recipe: Recipe) -> tuple[bool, list[VerificationRuleViolation]]:
        """Check if a recipe satisfies all rules to be in Verified state.

        Returns:
            Tuple of (is_valid, list_of_violations).
        """
        violations: list[VerificationRuleViolation] = []

        # R1: Primary source must have ISBN or DOI
        primary = recipe.primary_source
        if primary.isbn is None and primary.doi is None and not primary.url:
            violations.append(
                VerificationRuleViolation(
                    "R1",
                    "Primary source must have ISBN, DOI, or URL for verifiable citation.",
                )
            )

        # R2: Verification count check
        if recipe.status.state == VerificationState.VERIFIED:
            if recipe.status.verification_count < recipe.status.required_verifications:
                violations.append(
                    VerificationRuleViolation(
                        "R2",
                        f"Verified recipe requires at least "
                        f"{recipe.status.required_verifications} verifications, "
                        f"has {recipe.status.verification_count}.",
                    )
                )

        # R3: All components must have CAS
        for component in recipe.all_components:
            cas = component.cas_number.strip().lower()
            if cas not in {"mixture", "proprietary"} and not _looks_like_cas(cas):
                violations.append(
                    VerificationRuleViolation(
                        "R3",
                        f"Component '{component.name}' has invalid CAS number: '{component.cas_number}'. "
                        f"Expected CAS format (XXXXXX-XX-X) or 'mixture'/'proprietary'.",
                    )
                )

        # R4: Publisher check (if state is VERIFIED)
        if recipe.status.state == VerificationState.VERIFIED:
            for citation in recipe.all_source_references:
                if citation.publisher not in cls.APPROVED_PUBLISHERS:
                    violations.append(
                        VerificationRuleViolation(
                            "R4",
                            f"Source '{citation.short_form}' has unapproved publisher: "
                            f"'{citation.publisher}'. Approved: {sorted(cls.APPROVED_PUBLISHERS)}.",
                        )
                    )

        # R5: Cannot skip PENDING_REVIEW
        if recipe.status.state == VerificationState.VERIFIED:
            if recipe.status.verification_count < 1:
                violations.append(
                    VerificationRuleViolation(
                        "R5",
                        "Recipe cannot be Verified without going through PendingReview.",
                    )
                )

        return (len(violations) == 0, violations)

    @classmethod
    def enforce_verification(cls, recipe: Recipe) -> None:
        """Raise if recipe cannot be verified. Use this before transitioning to VERIFIED."""
        is_valid, violations = cls.can_be_verified(recipe)
        if not is_valid:
            raise VerificationRuleViolation(
                "Multiple",
                "; ".join(f"{v.rule}: {v.message}" for v in violations),
            )


def _looks_like_cas(value: str) -> bool:
    """Quick sanity check for CAS-like format (XXXXXX-XX-X) without checksum validation.

    The full validation with checksum is done in CasNumber value object.
    This is a permissive check used in domain rules.
    """
    import re
    return bool(re.match(r"^\d{2,7}-\d{2}-\d$", value))
