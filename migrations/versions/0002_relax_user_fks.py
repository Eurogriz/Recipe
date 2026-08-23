"""Relax user foreign keys, add audit_log_entry.actor_label.

Rationale (see ADR-0006 §5 & the 1.1.3 changelog):
    - The `user` table is optional in 1.x — it's only populated when the
      RBAC module is activated.  Making ``recipe.created_by`` and
      ``audit_log_entry.user_id`` non-null FKs meant we couldn't audit any
      action taken by a system job, seed importer, JWT subject that isn't
      provisioned yet, or a static API token.
    - Instead we make the FKs nullable and add a free-form
      ``actor_label`` on ``audit_log_entry`` so the acting principal is
      always preserved for forensics.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ``created_by`` on ``recipe`` — nullable FK with ON DELETE SET NULL.
    with op.batch_alter_table("recipe", recreate="always") as batch_op:
        batch_op.alter_column("created_by", existing_type=sa.String(36), nullable=True)

    # ``user_id`` on ``audit_log_entry`` — nullable, and add ``actor_label``.
    with op.batch_alter_table("audit_log_entry", recreate="always") as batch_op:
        batch_op.alter_column("user_id", existing_type=sa.String(36), nullable=True)
        batch_op.add_column(
            sa.Column("actor_label", sa.String(128), nullable=False, server_default="system")
        )

    # Drop the server default now that all existing rows have a value.
    with op.batch_alter_table("audit_log_entry") as batch_op:
        batch_op.alter_column("actor_label", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("audit_log_entry", recreate="always") as batch_op:
        batch_op.drop_column("actor_label")
        batch_op.alter_column("user_id", existing_type=sa.String(36), nullable=False)

    with op.batch_alter_table("recipe", recreate="always") as batch_op:
        batch_op.alter_column("created_by", existing_type=sa.String(36), nullable=False)
