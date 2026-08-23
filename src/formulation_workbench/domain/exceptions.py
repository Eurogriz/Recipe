"""Domain exceptions.

These are the only exceptions raised by the domain layer.
Application and infrastructure layers should catch/translate these
but never introduce their own domain violations.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base for all domain errors."""


class RecipeInvariantViolation(DomainError):
    """A recipe violates a domain invariant (e.g., mass percents don't sum to 100)."""


class VerificationRuleViolation(DomainError):
    """A recipe violates a verification rule (e.g., missing primary source ISBN)."""


class InvalidStateTransition(DomainError):
    """Attempted invalid state transition (e.g., Verified → Verified directly)."""


class SourceReferenceMissing(DomainError):
    """A recipe lacks a required source reference."""
