"""Persist ExperimentRun and MeasuredValue.

Introduces the ``experiment_run`` + ``measured_value`` tables so that
lab data survives container restarts and can seed the ML training
pipeline (see ADR-0008).

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "experiment_run",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("recipe_id", sa.String(36), nullable=False),
        sa.Column("recipe_version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(256), nullable=False, server_default=""),
        sa.Column("hypothesis", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="planned"),
        sa.Column("verdict", sa.String(32)),
        sa.Column("operator", sa.String(128), nullable=False, server_default=""),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("batch_number", sa.String(64)),
        sa.Column("batch_target_mass_kg", sa.Float()),
        sa.Column("batch_actual_mass_kg", sa.Float()),
        sa.Column("batch_equipment_used", sa.String(128)),
        sa.Column("batch_lot_numbers_json", sa.Text()),
        sa.Column("target_properties_json", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        # No FK to recipe: an ExperimentRun must survive recipe deletion
        # for forensic reasons (see models.py).
    )
    op.create_index("ix_experiment_run_recipe_id", "experiment_run", ["recipe_id"])
    op.create_index("ix_experiment_run_status", "experiment_run", ["status"])
    op.create_index("ix_experiment_run_created_at", "experiment_run", ["created_at"])

    op.create_table(
        "measured_value",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("property_code", sa.String(64), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(32), nullable=False, server_default=""),
        sa.Column("method_standard", sa.String(64)),
        sa.Column("measured_at", sa.DateTime(timezone=True)),
        sa.Column("operator", sa.String(128), nullable=False, server_default=""),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.ForeignKeyConstraint(
            ["run_id"], ["experiment_run.id"], ondelete="CASCADE", name="fk_mv_run"
        ),
        sa.UniqueConstraint("run_id", "property_code", name="uq_measured_value_run_property"),
    )
    op.create_index("ix_measured_value_run_id", "measured_value", ["run_id"])
    op.create_index("ix_measured_value_property_code", "measured_value", ["property_code"])


def downgrade() -> None:
    op.drop_index("ix_measured_value_property_code", table_name="measured_value")
    op.drop_index("ix_measured_value_run_id", table_name="measured_value")
    op.drop_table("measured_value")

    op.drop_index("ix_experiment_run_created_at", table_name="experiment_run")
    op.drop_index("ix_experiment_run_status", table_name="experiment_run")
    op.drop_index("ix_experiment_run_recipe_id", table_name="experiment_run")
    op.drop_table("experiment_run")
