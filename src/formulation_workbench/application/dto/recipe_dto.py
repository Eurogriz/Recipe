"""Recipe DTOs (Data Transfer Objects).

Used to transfer recipe data between application and presentation layers
without exposing domain entities directly.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...domain.entities.recipe import Recipe


@dataclass(frozen=True, slots=True)
class RecipeSummaryDto:
    """Lightweight DTO for list views (catalog, search results)."""

    id: str
    category: str
    subcategory: str
    binder_type: str
    product_class: str
    intended_use: str
    status: str
    verification_count: int
    verification_required: int
    version: int

    @classmethod
    def from_recipe(cls, recipe: Recipe) -> RecipeSummaryDto:
        """Create DTO from Recipe entity."""
        return cls(
            id=recipe.id,
            category=recipe.category,
            subcategory=recipe.subcategory,
            binder_type=recipe.binder_type,
            product_class=recipe.product_class.value,
            intended_use=recipe.intended_use,
            status=recipe.status.state.value,
            verification_count=recipe.status.verification_count,
            verification_required=recipe.status.required_verifications,
            version=recipe.version,
        )


@dataclass(frozen=True, slots=True)
class RecipeFullDto:
    """Full DTO for editor view (all fields)."""

    id: str
    category: str
    subcategory: str
    binder_type: str
    product_class: str
    intended_use: str
    finish: str
    color: str
    status: str
    verification_count: int
    verification_required: int
    version: int
    primary_source: str
    cross_references: tuple[str, ...]
    tags: tuple[str, ...]

    @classmethod
    def from_recipe(cls, recipe: Recipe) -> RecipeFullDto:
        """Create DTO from Recipe entity."""
        return cls(
            id=recipe.id,
            category=recipe.category,
            subcategory=recipe.subcategory,
            binder_type=recipe.binder_type,
            product_class=recipe.product_class.value,
            intended_use=recipe.intended_use,
            finish=recipe.finish,
            color=recipe.color,
            status=recipe.status.state.value,
            verification_count=recipe.status.verification_count,
            verification_required=recipe.status.required_verifications,
            version=recipe.version,
            primary_source=str(recipe.primary_source),
            cross_references=tuple(str(ref) for ref in recipe.cross_references),
            tags=recipe.tags,
        )
