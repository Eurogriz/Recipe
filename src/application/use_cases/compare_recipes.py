"""Compare recipes use case."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ...domain.entities.recipe import Recipe

if TYPE_CHECKING:
    from ..ports.recipe_repository import RecipeRepository


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CompareRecipesQuery:
    """Query to compare multiple recipes."""

    recipe_ids: tuple[str, ...]
    # Up to 4 recipes per the UI requirement


@dataclass(frozen=True, slots=True)
class ComparisonRow:
    """A row in the comparison table — a single field across all recipes."""

    field_name: str
    values: tuple[str, ...]  # One value per recipe (empty string if absent)


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    """Result of comparing multiple recipes."""

    recipes: tuple[Recipe, ...]
    composition_rows: tuple[ComparisonRow, ...]
    properties_rows: tuple[ComparisonRow, ...]
    process_rows: tuple[ComparisonRow, ...]


class CompareRecipesUseCase:
    """Use case to compare up to 4 recipes side-by-side."""

    MAX_RECIPES = 4

    def __init__(self, recipe_repo: RecipeRepository) -> None:
        self._recipe_repo = recipe_repo

    async def execute(self, query: CompareRecipesQuery) -> ComparisonResult:
        """Execute comparison."""
        if len(query.recipe_ids) < 2:
            raise ValueError(
                f"Comparison requires at least 2 recipes, got {len(query.recipe_ids)}"
            )
        if len(query.recipe_ids) > self.MAX_RECIPES:
            raise ValueError(
                f"Cannot compare more than {self.MAX_RECIPES} recipes, "
                f"got {len(query.recipe_ids)}"
            )

        # Fetch all recipes
        recipes: list[Recipe] = []
        for recipe_id in query.recipe_ids:
            recipe = await self._recipe_repo.get_by_id(recipe_id)
            if recipe is None:
                raise ValueError(f"Recipe not found: {recipe_id}")
            recipes.append(recipe)

        # Build comparison rows
        composition_rows = self._build_composition_rows(recipes)
        properties_rows = self._build_properties_rows(recipes)
        process_rows = self._build_process_rows(recipes)

        return ComparisonResult(
            recipes=tuple(recipes),
            composition_rows=composition_rows,
            properties_rows=properties_rows,
            process_rows=process_rows,
        )

    def _build_composition_rows(self, recipes: tuple[Recipe, ...]) -> tuple[ComparisonRow, ...]:
        """Build composition comparison rows."""
        # Gather all unique component names across recipes
        all_components: set[str] = set()
        for recipe in recipes:
            for comp in recipe.all_components:
                all_components.add(comp.name)

        rows: list[ComparisonRow] = []
        for comp_name in sorted(all_components):
            values: list[str] = []
            for recipe in recipes:
                comps = [c for c in recipe.all_components if c.name == comp_name]
                if comps:
                    values.append(
                        f"{comps[0].mass_percent:.2f}% "
                        f"(CAS: {comps[0].cas_number})"
                    )
                else:
                    values.append("—")
            rows.append(ComparisonRow(field_name=comp_name, values=tuple(values)))
        return tuple(rows)

    def _build_properties_rows(self, recipes: tuple[Recipe, ...]) -> tuple[ComparisonRow, ...]:
        """Build properties comparison rows."""
        rows: list[ComparisonRow] = []
        property_fields = [
            ("Category", lambda r: r.category),
            ("Subcategory", lambda r: r.subcategory),
            ("Binder type", lambda r: r.binder_type),
            ("Product class", lambda r: r.product_class.value),
            ("Finish", lambda r: r.finish),
            ("Color", lambda r: r.color),
            ("Status", lambda r: r.status.state.value),
            ("Verification count", lambda r: f"{r.status.verification_count}/{r.status.required_verifications}"),
            ("Version", lambda r: str(r.version)),
        ]
        for field_name, getter in property_fields:
            values = tuple(getter(r) for r in recipes)
            rows.append(ComparisonRow(field_name=field_name, values=values))
        return tuple(rows)

    def _build_process_rows(self, recipes: tuple[Recipe, ...]) -> tuple[ComparisonRow, ...]:
        """Build process comparison rows."""
        rows: list[ComparisonRow] = []
        for stage_num in range(1, max(len(r.stages) for r in recipes) + 1):
            stage_names: list[str] = []
            equipment: list[str] = []
            for recipe in recipes:
                stages = [s for s in recipe.stages if s.stage_number == stage_num]
                if stages:
                    stage_names.append(stages[0].name)
                    if stages[0].process:
                        equipment.append(stages[0].process.equipment)
                    else:
                        equipment.append("—")
                else:
                    stage_names.append("—")
                    equipment.append("—")
            rows.append(
                ComparisonRow(
                    field_name=f"Stage {stage_num}: name",
                    values=tuple(stage_names),
                )
            )
            rows.append(
                ComparisonRow(
                    field_name=f"Stage {stage_num}: equipment",
                    values=tuple(equipment),
                )
            )
        return tuple(rows)
