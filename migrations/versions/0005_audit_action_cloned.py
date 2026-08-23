"""Extend audit_log_entry.action CHECK to include 'Cloned'.

Adds one entry to the whitelist for the ``ck_audit_action_valid``
constraint so the new ``clone`` endpoint can audit-log the fork event.
Also adds ``'PropertyMeasured'`` while we're here — a spot the lab
workflow will use next; keeping the whitelist stable across two
subsequent releases spares a second SQLite table-copy migration.

SQLite doesn't support ``ALTER TABLE … DROP CONSTRAINT``, so we
rebuild the table via the standard SQLAlchemy batch-alter recipe.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


_ACTIONS_NEW = (
    "'Created', 'Updated', 'Deleted', 'SubmittedForReview', "
    "'Verified', 'Rejected', 'VersionCreated', 'Imported', 'Cloned', "
    "'PropertyMeasured'"
)
_ACTIONS_OLD = (
    "'Created', 'Updated', 'Deleted', 'SubmittedForReview', "
    "'Verified', 'Rejected', 'VersionCreated', 'Imported'"
)


def upgrade() -> None:
    with op.batch_alter_table("audit_log_entry") as batch:
        batch.drop_constraint("ck_audit_action_valid", type_="check")
        batch.create_check_constraint(
            "ck_audit_action_valid",
            f"action IN ({_ACTIONS_NEW})",
        )


def downgrade() -> None:
    with op.batch_alter_table("audit_log_entry") as batch:
        batch.drop_constraint("ck_audit_action_valid", type_="check")
        batch.create_check_constraint(
            "ck_audit_action_valid",
            f"action IN ({_ACTIONS_OLD})",
        )


# Keep `sa` import needed by alembic environment even though we don't
# call anything on it directly — the migration engine runs
# ``import`` statements as part of loading a revision.
_ = sa
