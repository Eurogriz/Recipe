"""Raw Material aggregate — the reusable ingredient catalog.

A ``RawMaterial`` is a *reference* entity: many recipes point at the
same material. Unlike :class:`Component` — which is embedded inside a
recipe stage — a raw material has a stable identity, a supplier
reference, and a full physicochemical fingerprint.

Recipe components can either quote a raw-material id (preferred) or
carry the material's data inline for backwards compatibility.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from ..value_objects.cas_number import CasNumber
from ..value_objects.functions import ComponentFunction
from ..value_objects.physical_properties import PhysicalProperties


@dataclass(frozen=True, slots=True)
class SupplierReference:
    """Where a raw material can be sourced."""

    supplier_name: str
    trade_name: str = ""
    product_code: str = ""
    country: str = ""
    website: str = ""

    def __post_init__(self) -> None:
        if not self.supplier_name or not self.supplier_name.strip():
            raise ValueError("SupplierReference must have supplier_name")


class InvalidRawMaterialError(ValueError):
    """Raised when a raw material violates domain invariants."""


class RawMaterial:
    """Reusable raw-material aggregate root.

    Immutable in practice — mutations happen through
    :meth:`with_properties` and friends that return a new instance,
    keeping the aggregate side-effect free for the application layer.
    """

    def __init__(
        self,
        id: str | None = None,
        name: str = "",
        cas_number: CasNumber | str | None = None,
        function: ComponentFunction = ComponentFunction.UNSPECIFIED,
        chemical_family: str = "",
        inci_name: str = "",
        description: str = "",
        properties: PhysicalProperties | None = None,
        suppliers: tuple[SupplierReference, ...] = (),
        tags: tuple[str, ...] = (),
        deprecated: bool = False,
        replacement_id: str | None = None,
        created_at: datetime | None = None,
    ) -> None:
        if not name or not name.strip():
            raise InvalidRawMaterialError("RawMaterial must have a non-empty name")

        # Normalise CAS: accept CasNumber, plain str, or 'mixture' / 'proprietary'.
        normalised_cas: str
        if cas_number is None or cas_number == "":
            normalised_cas = "unspecified"
        elif isinstance(cas_number, CasNumber):
            normalised_cas = cas_number.value
        else:
            token = str(cas_number).strip().lower()
            if token in {"mixture", "proprietary", "unspecified", ""}:
                normalised_cas = token or "unspecified"
            else:
                normalised_cas = CasNumber(str(cas_number)).value

        if deprecated and not replacement_id:
            # A deprecated material without a successor is a broken state.
            raise InvalidRawMaterialError(f"Deprecated material '{name}' must set replacement_id")

        self._id = id or str(uuid.uuid4())
        self._name = name.strip()
        self._cas = normalised_cas
        self._function = function
        self._chemical_family = chemical_family.strip()
        self._inci_name = inci_name.strip()
        self._description = description
        self._properties = properties or PhysicalProperties()
        self._suppliers = tuple(suppliers)
        self._tags = tuple(tags)
        self._deprecated = deprecated
        self._replacement_id = replacement_id
        self._created_at = created_at or datetime.now(timezone.utc)

    # ------------------------------------------------------------------ props
    @property
    def id(self) -> str:
        return self._id

    @property
    def name(self) -> str:
        return self._name

    @property
    def cas_number(self) -> str:
        return self._cas

    @property
    def function(self) -> ComponentFunction:
        return self._function

    @property
    def chemical_family(self) -> str:
        return self._chemical_family

    @property
    def inci_name(self) -> str:
        return self._inci_name

    @property
    def description(self) -> str:
        return self._description

    @property
    def properties(self) -> PhysicalProperties:
        return self._properties

    @property
    def suppliers(self) -> tuple[SupplierReference, ...]:
        return self._suppliers

    @property
    def tags(self) -> tuple[str, ...]:
        return self._tags

    @property
    def deprecated(self) -> bool:
        return self._deprecated

    @property
    def replacement_id(self) -> str | None:
        return self._replacement_id

    @property
    def created_at(self) -> datetime:
        return self._created_at

    # ------------------------------------------------------------------ helpers
    def with_properties(self, props: PhysicalProperties) -> RawMaterial:
        return RawMaterial(
            id=self._id,
            name=self._name,
            cas_number=self._cas,
            function=self._function,
            chemical_family=self._chemical_family,
            inci_name=self._inci_name,
            description=self._description,
            properties=props,
            suppliers=self._suppliers,
            tags=self._tags,
            deprecated=self._deprecated,
            replacement_id=self._replacement_id,
            created_at=self._created_at,
        )

    def deprecate(self, replacement_id: str) -> RawMaterial:
        if not replacement_id:
            raise InvalidRawMaterialError("replacement_id must be non-empty")
        return RawMaterial(
            id=self._id,
            name=self._name,
            cas_number=self._cas,
            function=self._function,
            chemical_family=self._chemical_family,
            inci_name=self._inci_name,
            description=self._description,
            properties=self._properties,
            suppliers=self._suppliers,
            tags=self._tags,
            deprecated=True,
            replacement_id=replacement_id,
            created_at=self._created_at,
        )

    # ------------------------------------------------------------------ dunder
    def __eq__(self, other: object) -> bool:
        return isinstance(other, RawMaterial) and self._id == other._id

    def __hash__(self) -> int:
        return hash(self._id)

    def __repr__(self) -> str:
        return f"RawMaterial(id='{self._id[:8]}...', name={self._name!r}, function={self._function.value})"


__all__ = [
    "InvalidRawMaterialError",
    "RawMaterial",
    "SupplierReference",
]
