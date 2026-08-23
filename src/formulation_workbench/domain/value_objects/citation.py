"""Citation value object.

Represents a verified bibliographic source for a recipe.
Used as a Value Object in SourceReference and CrossReference.

Format follows standard bibliographic conventions but is intentionally
flexible (free-text) since source citations vary widely across publishers.
"""

from __future__ import annotations

from dataclasses import dataclass

from .doi import Doi  # type: ignore[attr-defined]  # imported below
from .isbn import Isbn


@dataclass(frozen=True, slots=True)
class Citation:
    """Bibliographic citation.

    Required:
        - authors: comma-separated list of authors (e.g., "Flick, E.W.")
        - title: book/paper title
        - year: publication year (4-digit)
        - publisher: publisher name

    Optional:
        - edition: edition number (e.g., "2nd ed.", "4th ed.")
        - isbn: ISBN value object (validates checksum)
        - doi: DOI value object
        - url: URL for online resource
        - page_or_formula: specific page or formulation number
        - section: chapter/section reference
    """

    authors: str
    title: str
    year: int
    publisher: str
    edition: str = ""
    isbn: Isbn | None = None
    doi: Doi | None = None
    url: str | None = None
    page_or_formula: str = ""
    section: str = ""

    def __post_init__(self) -> None:
        if not self.authors or not self.authors.strip():
            raise ValueError("Citation must have non-empty authors")
        if not self.title or not self.title.strip():
            raise ValueError("Citation must have non-empty title")
        if not (1000 <= self.year <= 2100):
            raise ValueError(f"Year must be between 1000 and 2100, got {self.year}")
        if not self.publisher or not self.publisher.strip():
            raise ValueError("Citation must have non-empty publisher")

    @property
    def short_form(self) -> str:
        """Short bibliographic form for display (e.g., 'Flick (1995)')."""
        first_author = self.authors.split(",")[0].strip()
        return f"{first_author} ({self.year})"

    @property
    def full_form(self) -> str:
        """Full bibliographic form with all available fields."""
        parts = [f"{self.authors}", f"{self.title}"]
        if self.edition:
            parts.append(f"{self.edition}")
        parts.append(f"{self.publisher}, {self.year}")

        identifiers = []
        if self.isbn:
            identifiers.append(f"ISBN: {self.isbn}")
        if self.doi:
            identifiers.append(f"DOI: {self.doi}")
        if self.url:
            identifiers.append(f"URL: {self.url}")

        if identifiers:
            parts.append("; ".join(identifiers))

        return ". ".join(parts)

    def __str__(self) -> str:
        return self.full_form

    def __repr__(self) -> str:
        return f"Citation(authors='{self.authors}', title='{self.title}', year={self.year})"
