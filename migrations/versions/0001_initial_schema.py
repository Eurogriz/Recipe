"""Initial schema for Formulation Workbench.

Creates all tables from the ER diagram:
- user (with role-based access control)
- raw_material, supplier (catalog)
- source_citation (verified sources)
- recipe, composition_stage, component, recipe_source_reference
- audit_log_entry

Revision ID: 0001
Revises:
Create Date: 2026-06-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # =========================================================================
    # USER
    # =========================================================================
    op.create_table(
        "user",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("email", sa.String(256), nullable=True),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("username", name="uq_user_username"),
        sa.CheckConstraint(
            "role IN ('Viewer', 'Technologist', 'Admin', 'Auditor')",
            name="ck_user_role_valid",
        ),
    )
    op.create_index("ix_user_username", "user", ["username"], unique=True)

    # =========================================================================
    # RAW MATERIAL (catalog)
    # =========================================================================
    op.create_table(
        "raw_material",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("cas_number", sa.String(32), nullable=False),
        sa.Column("inci_name", sa.String(256), nullable=True),
        sa.Column("function", sa.String(128), nullable=False),
        sa.Column("density_g_per_cm3", sa.Float(), nullable=True),
        sa.Column("molar_mass", sa.Float(), nullable=True),
        sa.Column("is_predicted_density", sa.Boolean(), nullable=False, server_default="0"),
        sa.UniqueConstraint("cas_number", "name", name="uq_raw_material_cas_name"),
        sa.CheckConstraint("cas_number != ''", name="ck_raw_material_cas_not_empty"),
    )
    op.create_index("ix_raw_material_name", "raw_material", ["name"])
    op.create_index("ix_raw_material_cas_number", "raw_material", ["cas_number"])

    op.create_table(
        "supplier",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("country", sa.String(64), nullable=True),
        sa.Column("website", sa.String(512), nullable=True),
        sa.UniqueConstraint("name", name="uq_supplier_name"),
    )

    # =========================================================================
    # SOURCE CITATION (verified sources)
    # =========================================================================
    op.create_table(
        "source_citation",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("authors", sa.String(512), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("edition", sa.String(64), nullable=True),
        sa.Column("publisher", sa.String(256), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("isbn", sa.String(32), nullable=True),
        sa.Column("doi", sa.String(256), nullable=True),
        sa.Column("url", sa.String(512), nullable=True),
        sa.CheckConstraint("year >= 1000 AND year <= 2100", name="ck_citation_year_range"),
    )
    op.create_index("ix_source_citation_isbn", "source_citation", ["isbn"])
    op.create_index("ix_source_citation_doi", "source_citation", ["doi"])
    op.create_index("ix_source_citation_year", "source_citation", ["year"])

    # =========================================================================
    # RECIPE
    # =========================================================================
    op.create_table(
        "recipe",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("schema_version", sa.String(16), nullable=False, server_default="1.0.0"),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("subcategory", sa.String(128), nullable=False),
        sa.Column("binder_type", sa.String(128), nullable=False),
        sa.Column("product_class", sa.String(32), nullable=False),
        sa.Column("intended_use", sa.Text(), nullable=False),
        sa.Column("finish", sa.String(64), nullable=True),
        sa.Column("color", sa.String(64), nullable=True),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_by", sa.String(36), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "previous_version_id",
            sa.String(36),
            sa.ForeignKey("recipe.id"),
            nullable=True,
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="Draft"),
        sa.Column("verification_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("required_verifications", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('Draft', 'PendingReview', 'Verified', 'Rejected')",
            name="ck_recipe_status_valid",
        ),
        sa.CheckConstraint(
            "product_class IN ('SuperEconomy', 'Economy', 'Standard', 'Premium', "
            "'SuperPremium', 'Industrial', 'Specialty')",
            name="ck_recipe_product_class_valid",
        ),
    )
    op.create_index("ix_recipe_category_subcategory", "recipe", ["category", "subcategory"])
    op.create_index("ix_recipe_product_class", "recipe", ["product_class"])
    op.create_index("ix_recipe_status", "recipe", ["status"])
    op.create_index("ix_recipe_verified_at", "recipe", ["verified_at"])

    # =========================================================================
    # COMPOSITION STAGE
    # =========================================================================
    op.create_table(
        "composition_stage",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "recipe_id",
            sa.String(36),
            sa.ForeignKey("recipe.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stage_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("equipment", sa.String(256), nullable=True),
        sa.Column("rotational_speed_rpm", sa.Float(), nullable=True),
        sa.Column("peripheral_speed_m_per_s", sa.Float(), nullable=True),
        sa.Column("temperature_c", sa.Float(), nullable=True),
        sa.Column("duration_min", sa.Integer(), nullable=True),
        sa.Column("control_points_json", sa.Text(), nullable=True),
        sa.UniqueConstraint("recipe_id", "stage_number", name="uq_stage_recipe_number"),
        sa.CheckConstraint("stage_number >= 1", name="ck_stage_number_positive"),
    )
    op.create_index("ix_composition_stage_recipe_id", "composition_stage", ["recipe_id"])

    # =========================================================================
    # COMPONENT
    # =========================================================================
    op.create_table(
        "component",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "stage_id",
            sa.String(36),
            sa.ForeignKey("composition_stage.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("raw_material_id", sa.String(36), sa.ForeignKey("raw_material.id"), nullable=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("cas_number", sa.String(32), nullable=False),
        sa.Column("inci_name", sa.String(256), nullable=True),
        sa.Column("function", sa.String(128), nullable=False),
        sa.Column("manufacturer_reference", sa.Text(), nullable=True),
        sa.Column("mass_percent", sa.Float(), nullable=False),
        sa.Column("tolerance_percent", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("order_in_stage", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_predicted", sa.Boolean(), nullable=False, server_default="0"),
        sa.CheckConstraint("mass_percent >= 0 AND mass_percent <= 100", name="ck_mass_percent_range"),
        sa.CheckConstraint(
            "tolerance_percent >= 0 AND tolerance_percent <= 100", name="ck_tolerance_range"
        ),
    )
    op.create_index("ix_component_stage_id", "component", ["stage_id"])
    op.create_index("ix_component_raw_material_id", "component", ["raw_material_id"])

    # =========================================================================
    # RECIPE SOURCE REFERENCE (junction recipe ↔ source_citation)
    # =========================================================================
    op.create_table(
        "recipe_source_reference",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "recipe_id",
            sa.String(36),
            sa.ForeignKey("recipe.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("citation_id", sa.String(36), sa.ForeignKey("source_citation.id"), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("page_or_formula", sa.String(256), nullable=True),
        sa.Column("section", sa.String(512), nullable=True),
        sa.Column("verified_by", sa.String(36), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_recipe_source_reference_recipe_id", "recipe_source_reference", ["recipe_id"])

    # =========================================================================
    # AUDIT LOG
    # =========================================================================
    op.create_table(
        "audit_log_entry",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "recipe_id",
            sa.String(36),
            sa.ForeignKey("recipe.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("changes_json", sa.Text(), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.CheckConstraint(
            "action IN ('Created', 'Updated', 'Deleted', 'SubmittedForReview', "
            "'Verified', 'Rejected', 'VersionCreated', 'Imported')",
            name="ck_audit_action_valid",
        ),
    )
    op.create_index("ix_audit_log_recipe_time", "audit_log_entry", ["recipe_id", "timestamp"])
    op.create_index("ix_audit_log_user_time", "audit_log_entry", ["user_id", "timestamp"])


def downgrade() -> None:
    # Drop in reverse dependency order
    op.drop_table("audit_log_entry")
    op.drop_table("recipe_source_reference")
    op.drop_table("component")
    op.drop_table("composition_stage")
    op.drop_table("recipe")
    op.drop_table("source_citation")
    op.drop_table("supplier")
    op.drop_table("raw_material")
    op.drop_table("user")
