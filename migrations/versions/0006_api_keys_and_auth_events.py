"""Personal API keys and auth event kinds in the audit log.

Three independent additions bundled into one migration because they
ship in the same release (v1.18.0) and all touch the auth surface.

1. New table ``api_key`` — per-user personal access tokens.  Users
   (or the CI system acting on their behalf) issue a token from the
   UI; the server stores only a SHA-256 digest, never the plaintext.
   Deletion is soft (``revoked_at``) so audit-log entries that
   reference an API key stay resolvable long after it stops
   working.

2. Extended ``ck_audit_action_valid`` CHECK with the new auth-facing
   verbs ``Login``, ``LoginFailed``, ``Logout``, ``ApiKeyIssued``,
   ``ApiKeyRevoked``.  These are written by the new
   ``ApiKeyRepository`` and by the ``/auth/login`` /
   ``/auth/logout`` endpoints, and let ``/admin/audit`` surface auth
   events alongside the domain history.

3. Loosened ``audit_log_entry.recipe_id`` to be nullable — auth
   events (Login/Logout/LoginFailed) and account admin events
   (ApiKeyIssued/Revoked) have no recipe to point at.  The existing
   CASCADE-on-delete is preserved for the non-null case.

SQLite can't ``DROP CONSTRAINT`` so the second and third changes go
through the batch-alter-table recipe (identical shape to migration
0005).

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


# The full whitelist as of this migration.  Kept as one string so that
# a future extension is a two-line diff (add here, add downgrade).
_ACTIONS_NEW = (
    "'Created', 'Updated', 'Deleted', 'SubmittedForReview', "
    "'Verified', 'Rejected', 'VersionCreated', 'Imported', 'Cloned', "
    "'PropertyMeasured', "
    "'Login', 'LoginFailed', 'Logout', 'ApiKeyIssued', 'ApiKeyRevoked'"
)
_ACTIONS_OLD = (
    "'Created', 'Updated', 'Deleted', 'SubmittedForReview', "
    "'Verified', 'Rejected', 'VersionCreated', 'Imported', 'Cloned', "
    "'PropertyMeasured'"
)


def upgrade() -> None:
    # 1) api_key table -------------------------------------------------------
    op.create_table(
        "api_key",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            # ON DELETE CASCADE — an API key without a live user has
            # no scopes it can grant, and would be a source of
            # confusing 403s.  Losing an audit entry's link to a
            # revoked user is fine (``actor_label`` still records
            # the historical username as a free-form string).
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(128), nullable=False),
        # HMAC-SHA256 hex digest of the plaintext token (never store
        # the plaintext).  64 chars for SHA-256; 128 gives us head
        # room for a future SHA-512 upgrade without a migration.
        sa.Column("token_hash", sa.String(128), nullable=False, unique=True),
        # Short prefix of the plaintext, kept for UI display so a
        # human can eyeball which key just triggered an event
        # without seeing the secret.
        sa.Column("token_prefix", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        # Soft delete — the row stays for audit lookups after revocation.
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_api_key_token_hash"),
    )
    op.create_index("ix_api_key_user_id", "api_key", ["user_id"])
    op.create_index("ix_api_key_token_hash", "api_key", ["token_hash"])

    # 2) Extend audit_log_entry.action CHECK + relax recipe_id ---------------
    # Batch runs a full copy-and-rename under SQLite; we want both
    # column-nullability and check-constraint edits to land in a
    # single rebuild.
    with op.batch_alter_table("audit_log_entry") as batch:
        batch.drop_constraint("ck_audit_action_valid", type_="check")
        batch.create_check_constraint(
            "ck_audit_action_valid",
            f"action IN ({_ACTIONS_NEW})",
        )
        batch.alter_column("recipe_id", existing_type=sa.String(36), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("audit_log_entry") as batch:
        batch.drop_constraint("ck_audit_action_valid", type_="check")
        batch.create_check_constraint(
            "ck_audit_action_valid",
            f"action IN ({_ACTIONS_OLD})",
        )
        # Recreating NOT NULL requires every row to have a value —
        # auth events that landed under 0006 would need cleanup
        # first.  We keep the down-migration syntactically valid but
        # note that it will fail loudly if such rows exist.
        batch.alter_column("recipe_id", existing_type=sa.String(36), nullable=False)

    op.drop_index("ix_api_key_token_hash", table_name="api_key")
    op.drop_index("ix_api_key_user_id", table_name="api_key")
    op.drop_table("api_key")


# Keep `sa` import needed by alembic environment even though the
# batch-alter block doesn't reference it directly.
_ = sa
