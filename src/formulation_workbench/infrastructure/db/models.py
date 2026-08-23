"""SQLAlchemy ORM models.

Mirrors the ER diagram in docs/00-discovery/er-diagram.md.
Pure persistence models — no domain logic.

Domain entities (in src/domain/) are mapped to/from these models
via the repository implementation.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """SQLAlchemy declarative base."""

    pass


def _uuid_str() -> str:
    return str(uuid.uuid4())


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ==============================================================================
# User
# ==============================================================================
class UserModel(Base):
    __tablename__ = "user"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    email: Mapped[str | None] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # Viewer/Technologist/Admin/Auditor
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ==============================================================================
# Raw Material (справочник сырья)
# ==============================================================================
class RawMaterialModel(Base):
    __tablename__ = "raw_material"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    name: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    cas_number: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    inci_name: Mapped[str | None] = mapped_column(String(256))
    function: Mapped[str] = mapped_column(String(128), nullable=False)
    density_g_per_cm3: Mapped[float | None] = mapped_column(Float)
    molar_mass: Mapped[float | None] = mapped_column(Float)
    is_predicted_density: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("cas_number", "name", name="uq_raw_material_cas_name"),
        CheckConstraint("cas_number != ''", name="ck_raw_material_cas_not_empty"),
    )


class SupplierModel(Base):
    __tablename__ = "supplier"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    name: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)
    country: Mapped[str | None] = mapped_column(String(64))
    website: Mapped[str | None] = mapped_column(String(512))


# ==============================================================================
# Source Citation
# ==============================================================================
class SourceCitationModel(Base):
    __tablename__ = "source_citation"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    authors: Mapped[str] = mapped_column(String(512), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    edition: Mapped[str | None] = mapped_column(String(64))
    publisher: Mapped[str] = mapped_column(String(256), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    isbn: Mapped[str | None] = mapped_column(String(32), index=True)
    doi: Mapped[str | None] = mapped_column(String(256), index=True)
    url: Mapped[str | None] = mapped_column(String(512))

    __table_args__ = (
        Index("idx_source_citation_year", "year"),
        Index("idx_source_citation_authors", "authors"),
    )


# ==============================================================================
# Recipe (core)
# ==============================================================================
class RecipeModel(Base):
    __tablename__ = "recipe"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0.0")
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    subcategory: Mapped[str] = mapped_column(String(128), nullable=False)
    binder_type: Mapped[str] = mapped_column(String(128), nullable=False)
    product_class: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    intended_use: Mapped[str] = mapped_column(Text, nullable=False)
    finish: Mapped[str | None] = mapped_column(String(64))
    color: Mapped[str | None] = mapped_column(String(64))

    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("user.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )
    verified_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("user.id"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    previous_version_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("recipe.id"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="Draft", index=True)
    verification_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    required_verifications: Mapped[int] = mapped_column(Integer, nullable=False, default=3)

    metadata_json: Mapped[str | None] = mapped_column(Text)

    # Relationships
    stages: Mapped[list[CompositionStageModel]] = relationship(
        "CompositionStageModel",
        back_populates="recipe",
        cascade="all, delete-orphan",
        order_by="CompositionStageModel.stage_number",
    )
    primary_source: Mapped[RecipeSourceReferenceModel] = relationship(
        "RecipeSourceReferenceModel",
        back_populates="recipe",
        cascade="all, delete-orphan",
        foreign_keys="RecipeSourceReferenceModel.recipe_id",
    )

    __table_args__ = (
        Index("idx_recipe_category", "category", "subcategory"),
        Index("idx_recipe_verified_at", "verified_at"),
    )


class CompositionStageModel(Base):
    __tablename__ = "composition_stage"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    recipe_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("recipe.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    # Process parameters (denormalized for simplicity in MVP)
    equipment: Mapped[str | None] = mapped_column(String(256))
    rotational_speed_rpm: Mapped[float | None] = mapped_column(Float)
    peripheral_speed_m_per_s: Mapped[float | None] = mapped_column(Float)
    temperature_c: Mapped[float | None] = mapped_column(Float)
    duration_min: Mapped[int | None] = mapped_column(Integer)
    control_points_json: Mapped[str | None] = mapped_column(Text)

    recipe: Mapped[RecipeModel] = relationship("RecipeModel", back_populates="stages")
    components: Mapped[list[ComponentModel]] = relationship(
        "ComponentModel",
        back_populates="stage",
        cascade="all, delete-orphan",
        order_by="ComponentModel.order_in_stage",
    )

    __table_args__ = (
        UniqueConstraint("recipe_id", "stage_number", name="uq_stage_recipe_number"),
        CheckConstraint("stage_number >= 1", name="ck_stage_number_positive"),
    )


class ComponentModel(Base):
    __tablename__ = "component"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    stage_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("composition_stage.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    raw_material_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("raw_material.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    cas_number: Mapped[str] = mapped_column(String(32), nullable=False)
    inci_name: Mapped[str | None] = mapped_column(String(256))
    function: Mapped[str] = mapped_column(String(128), nullable=False)
    manufacturer_reference: Mapped[str | None] = mapped_column(Text)
    mass_percent: Mapped[float] = mapped_column(Float, nullable=False)
    tolerance_percent: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    order_in_stage: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(Text)
    is_predicted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    stage: Mapped[CompositionStageModel] = relationship(
        "CompositionStageModel", back_populates="components"
    )

    __table_args__ = (
        CheckConstraint("mass_percent >= 0 AND mass_percent <= 100", name="ck_mass_percent_range"),
        CheckConstraint(
            "tolerance_percent >= 0 AND tolerance_percent <= 100", name="ck_tolerance_range"
        ),
    )


class RecipeSourceReferenceModel(Base):
    __tablename__ = "recipe_source_reference"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    recipe_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("recipe.id", ondelete="CASCADE"), nullable=False, index=True
    )
    citation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("source_citation.id"), nullable=False
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False)
    page_or_formula: Mapped[str | None] = mapped_column(String(256))
    section: Mapped[str | None] = mapped_column(String(512))
    verified_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("user.id"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    recipe: Mapped[RecipeModel] = relationship(
        "RecipeModel",
        back_populates="primary_source",
        foreign_keys=[recipe_id],
    )
    citation: Mapped[SourceCitationModel] = relationship("SourceCitationModel")


# ==============================================================================
# Audit Log
# ==============================================================================
class AuditLogEntryModel(Base):
    __tablename__ = "audit_log_entry"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    recipe_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("recipe.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("user.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    changes_json: Mapped[str | None] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, index=True
    )
    ip_address: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        Index("idx_audit_log_recipe_time", "recipe_id", "timestamp"),
        Index("idx_audit_log_user_time", "user_id", "timestamp"),
    )
