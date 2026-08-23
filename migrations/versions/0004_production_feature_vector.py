"""Store production feature-vector samples for drift monitoring.

Adds a lightweight ``production_feature_vector`` table that ingests
the 37-column composition-feature vector we extract from each live
lot / production batch.  The ``drift-from-catalog`` endpoint gains a
new ``source=production`` mode that compares the model's training
snapshot against these samples instead of against the current recipe
catalog — which is what a real MLOps setup needs.

Deliberately decoupled from ``experiment_run`` and ``recipe``:

- No foreign key on ``recipe_id`` — production data may reference a
  recipe id that has already been superseded or archived; treating
  it as a plain text label keeps ingestion resilient.
- Vector stored as a JSON list of floats.  We do not embed feature
  names in the row because they are declarative on the module
  (``FEATURE_NAMES``) — a schema-column change would rev the
  migration, and we want to notice it.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "production_feature_vector",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("recipe_id", sa.String(36), nullable=False, index=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("source", sa.String(64), nullable=False, server_default="lab"),
        sa.Column("features_json", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
    )
    op.create_index(
        "ix_production_feature_vector_recipe_recorded",
        "production_feature_vector",
        ["recipe_id", "recorded_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_production_feature_vector_recipe_recorded", "production_feature_vector")
    op.drop_table("production_feature_vector")
