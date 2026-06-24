"""Recipe aggregate root.

A Recipe is the central domain entity. It encapsulates:
- Composition (multi-stage production process)
- Source references (verified citations)
- Verification status (workflow)
- Audit trail (immutable history)

Invariants (enforced in __post_init__ and methods):
- Composition mass percents must sum to 100% (±0.5% tolerance)
- Each component has a CAS number (or explicit 'mixture' designation)
- Source references must be non-empty
- Verified recipes are logically immutable (any change creates new version)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..value_objects.citation import Citation
    from ..value_objects.verification_status import VerificationStatus


class ProductClass(str, Enum):
    """Product class for market positioning."""

    SUPER_ECONOMY = "SuperEconomy"
    ECONOMY = "Economy"
    STANDARD = "Standard"
    PREMIUM = "Premium"
    SUPER_PREMIUM = "SuperPremium"
    INDUSTRIAL = "Industrial"
    SPECIALTY = "Specialty"


class InvalidRecipeError(ValueError):
    """Raised when recipe violates domain invariants."""


@dataclass(frozen=True, slots=True)
class Component:
    """A single component in a recipe composition stage.

    Immutable. Includes CAS number, mass percent, and function.
    """

    name: str
    cas_number: str  # CAS or "mixture" or "proprietary"
    function: str
    mass_percent: float
    tolerance_percent: float = 0.0
    inci_name: str = ""
    manufacturer_reference: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise InvalidRecipeError("Component must have non-empty name")
        if not self.cas_number or not self.cas_number.strip():
            raise InvalidRecipeError(f"Component '{self.name}' must have CAS number")
        if not self.function or not self.function.strip():
            raise InvalidRecipeError(f"Component '{self.name}' must have function")
        if not (0.0 <= self.mass_percent <= 100.0):
            raise InvalidRecipeError(
                f"Component '{self.name}' mass_percent must be in [0, 100], got {self.mass_percent}"
            )
        if not (0.0 <= self.tolerance_percent <= 100.0):
            raise InvalidRecipeError(
                f"Component '{self.name}' tolerance must be in [0, 100], got {self.tolerance_percent}"
            )


@dataclass(frozen=True, slots=True)
class ProcessParams:
    """Process parameters for a single production stage."""

    equipment: str
    rotational_speed_rpm: float | None = None
    peripheral_speed_m_per_s: float | None = None
    temperature_c: float | None = None
    duration_min: int | None = None
    control_points: tuple[dict[str, str], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.equipment or not self.equipment.strip():
            raise InvalidRecipeError("ProcessParams must have equipment")


@dataclass(frozen=True, slots=True)
class CompositionStage:
    """A single production stage with components and process parameters."""

    stage_number: int
    name: str
    description: str
    components: tuple[Component, ...]
    process: ProcessParams | None = None

    def __post_init__(self) -> None:
        if self.stage_number < 1:
            raise InvalidRecipeError(f"Stage number must be >= 1, got {self.stage_number}")
        if not self.name or not self.name.strip():
            raise InvalidRecipeError(f"Stage {self.stage_number} must have name")

    @property
    def total_mass_percent(self) -> float:
        """Sum of mass percents of all components in this stage."""
        return sum(c.mass_percent for c in self.components)


class Recipe:
    """Recipe aggregate root.

    Multi-stage composition with verified source references and
    triple-verification workflow.
    """

    SCHEMA_VERSION = "1.0.0"
    MASS_PERCENT_TOLERANCE = 0.5  # ±0.5% allowed for sum-to-100 check

    def __init__(
        self,
        id: str | None = None,
        category: str = "",
        subcategory: str = "",
        binder_type: str = "",
        product_class: ProductClass = ProductClass.STANDARD,
        intended_use: str = "",
        stages: tuple[CompositionStage, ...] = (),
        primary_source: Citation | None = None,
        cross_references: tuple[Citation, ...] = (),
        status: VerificationStatus | None = None,
        created_at: datetime | None = None,
        created_by: str = "",
        version: int = 1,
        previous_version_id: str | None = None,
        tags: tuple[str, ...] = (),
        finish: str = "",
        color: str = "",
    ) -> None:
        from ..value_objects.citation import Citation
        from ..value_objects.verification_status import VerificationStatus

        # Required fields
        if not category or not category.strip():
            raise InvalidRecipeError("Recipe must have category")
        if not subcategory or not subcategory.strip():
            raise InvalidRecipeError("Recipe must have subcategory")
        if not binder_type or not binder_type.strip():
            raise InvalidRecipeError("Recipe must have binder_type")
        if not intended_use or not intended_use.strip():
            raise InvalidRecipeError("Recipe must have intended_use")

        if not stages:
            raise InvalidRecipeError("Recipe must have at least one composition stage")

        if primary_source is None:
            raise InvalidRecipeError("Recipe must have primary source citation")

        # Validate mass percents sum to 100%
        total_mass = sum(stage.total_mass_percent for stage in stages)
        if abs(total_mass - 100.0) > self.MASS_PERCENT_TOLERANCE:
            raise InvalidRecipeError(
                f"Component mass percents must sum to 100% (±{self.MASS_PERCENT_TOLERANCE}%), "
                f"got {total_mass:.2f}%"
            )

        # Validate stage numbering is sequential starting from 1
        expected_stage_numbers = list(range(1, len(stages) + 1))
        actual_stage_numbers = [s.stage_number for s in stages]
        if actual_stage_numbers != expected_stage_numbers:
            raise InvalidRecipeError(
                f"Stage numbers must be sequential starting from 1, got {actual_stage_numbers}"
            )

        # Assign immutable fields
        self._id = id or str(uuid.uuid4())
        self._category = category
        self._subcategory = subcategory
        self._binder_type = binder_type
        self._product_class = product_class
        self._intended_use = intended_use
        self._stages = stages
        self._primary_source = primary_source
        self._cross_references = cross_references
        self._status = status or VerificationStatus()
        self._created_at = created_at or datetime.now(timezone.utc)
        self._created_by = created_by
        self._version = version
        self._previous_version_id = previous_version_id
        self._tags = tags
        self._finish = finish
        self._color = color

    # ============================================================================
    # Properties (read-only access)
    # ============================================================================

    @property
    def id(self) -> str:
        return self._id

    @property
    def schema_version(self) -> str:
        return self.SCHEMA_VERSION

    @property
    def category(self) -> str:
        return self._category

    @property
    def subcategory(self) -> str:
        return self._subcategory

    @property
    def binder_type(self) -> str:
        return self._binder_type

    @property
    def product_class(self) -> ProductClass:
        return self._product_class

    @property
    def intended_use(self) -> str:
        return self._intended_use

    @property
    def stages(self) -> tuple[CompositionStage, ...]:
        return self._stages

    @property
    def primary_source(self) -> Citation:
        return self._primary_source

    @property
    def cross_references(self) -> tuple[Citation, ...]:
        return self._cross_references

    @property
    def status(self) -> VerificationStatus:
        return self._status

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def created_by(self) -> str:
        return self._created_by

    @property
    def version(self) -> int:
        return self._version

    @property
    def previous_version_id(self) -> str | None:
        return self._previous_version_id

    @property
    def tags(self) -> tuple[str, ...]:
        return self._tags

    @property
    def finish(self) -> str:
        return self._finish

    @property
    def color(self) -> str:
        return self._color

    @property
    def all_components(self) -> tuple[Component, ...]:
        """Flat list of all components across all stages."""
        result: list[Component] = []
        for stage in self._stages:
            result.extend(stage.components)
        return tuple(result)

    @property
    def all_source_references(self) -> tuple[Citation, ...]:
        """Primary source + all cross-references."""
        return (self._primary_source,) + self._cross_references

    # ============================================================================
    # Domain operations (return new instances for immutability)
    # ============================================================================

    def submit_for_review(self) -> Recipe:
        """Submit recipe for verification. Returns new Recipe instance."""
        return self._with_status(self._status.transition_to(VerificationState.PENDING_REVIEW))

    def verify(self) -> Recipe:
        """Add a verification. Returns new Recipe instance.

        May auto-transition to VERIFIED if threshold reached.
        """
        return self._with_status(self._status.add_verification())

    def reject(self) -> Recipe:
        """Reject recipe. Returns new Recipe instance."""
        return self._with_status(self._status.transition_to(VerificationState.REJECTED))

    def create_new_version(self) -> Recipe:
        """Create a new version (for editing Verified recipes). Returns new Recipe.

        The new version starts at Draft status with previous_version_id set.
        """
        new_recipe = Recipe(
            id=str(uuid.uuid4()),
            category=self._category,
            subcategory=self._subcategory,
            binder_type=self._binder_type,
            product_class=self._product_class,
            intended_use=self._intended_use,
            stages=self._stages,
            primary_source=self._primary_source,
            cross_references=self._cross_references,
            status=None,  # reset to DRAFT
            created_at=datetime.now(timezone.utc),
            created_by=self._created_by,
            version=self._version + 1,
            previous_version_id=self._id,
            tags=self._tags,
            finish=self._finish,
            color=self._color,
        )
        return new_recipe

    def _with_status(self, new_status: VerificationStatus) -> Recipe:
        """Internal helper to create a copy with new status."""
        new_recipe = Recipe(
            id=self._id,
            category=self._category,
            subcategory=self._subcategory,
            binder_type=self._binder_type,
            product_class=self._product_class,
            intended_use=self._intended_use,
            stages=self._stages,
            primary_source=self._primary_source,
            cross_references=self._cross_references,
            status=new_status,
            created_at=self._created_at,
            created_by=self._created_by,
            version=self._version,
            previous_version_id=self._previous_version_id,
            tags=self._tags,
            finish=self._finish,
            color=self._color,
        )
        return new_recipe

    # ============================================================================
    # Equality and representation
    # ============================================================================

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Recipe):
            return NotImplemented
        return self._id == other._id

    def __hash__(self) -> int:
        return hash(self._id)

    def __repr__(self) -> str:
        return (
            f"Recipe(id='{self._id[:8]}...', "
            f"category='{self._category}', "
            f"class={self._product_class.value}, "
            f"status={self._status.state.value})"
        )
