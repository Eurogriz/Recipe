"""``formulation-admin-users`` — CRUD on the ``user`` table from the shell.

The primary use case is bootstrap: a fresh install has no admins, and
without one the UI's ``/admin/users`` page is unreachable (it requires
the ``*`` scope from role Admin).  Without this CLI the operator has
to open a Python shell and hand-craft ``UserRepository.create``.

Six subcommands are supported:

- ``create-admin --username U --password P [--email ...]`` — insert a
  brand-new user with role ``Admin``.  Fails cleanly if the username
  is taken.
- ``create --username U --password P --role R [--email ...]`` — same
  but for any role.
- ``list`` — table of ``username | role | active | created_at``.
- ``set-password --username U --password P`` — rotate a password.
- ``set-role --username U --role R`` — promote/demote.
- ``activate --username U`` / ``deactivate --username U`` — toggle
  the ``is_active`` flag without deleting the row (preserves audit
  trail linkage via ``user_id``).
- ``delete --username U`` — hard delete.  Audit rows survive because
  their ``user_id`` FK is ``ON DELETE SET NULL``.

Reads settings from the environment exactly like the server (same
``FW_*`` variables), so pointing it at production or staging is a
matter of ``FW_DATABASE_URL=...`` before the call.

Exit codes:
    0 — success
    1 — user error (bad args, unknown role, missing user, duplicate
        username, weak password …)
    2 — I/O / DB error (unable to open the database, unexpected
        integrity violation)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Any

from ...infrastructure.config import get_settings
from ...infrastructure.db.connection import Database
from ...infrastructure.db.repositories.users import (
    VALID_ROLES,
    UnknownRoleError,
    UserRecord,
    UserRepository,
)
from ...infrastructure.logging.setup import setup_logging

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- helpers


def _fmt_ts(value: Any) -> str:
    if value is None:
        return "-"
    text = value.isoformat(timespec="seconds")
    return str(text).replace("+00:00", "Z")


def _print_table(records: list[UserRecord]) -> None:
    if not records:
        print("(no users)")
        return
    headers = ("USERNAME", "ROLE", "ACTIVE", "EMAIL", "CREATED", "LAST LOGIN")
    rows = [
        (
            r.username,
            r.role,
            "yes" if r.is_active else "no",
            r.email or "-",
            _fmt_ts(r.created_at),
            _fmt_ts(r.last_login_at),
        )
        for r in records
    ]
    widths = [max(len(headers[i]), *(len(row[i]) for row in rows)) for i in range(len(headers))]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    print(fmt.format(*("-" * w for w in widths)))
    for row in rows:
        print(fmt.format(*row))


# --------------------------------------------------------------------------- actions


async def _cmd_create(
    repo: UserRepository, *, username: str, password: str, role: str, email: str | None
) -> int:
    existing = await repo.get_by_username(username)
    if existing is not None:
        logger.error("username already exists: %s", username)
        return 1
    try:
        record = await repo.create(username=username, password=password, role=role, email=email)
    except UnknownRoleError as exc:
        logger.error(str(exc))
        return 1
    except ValueError as exc:  # short password / empty username
        logger.error(str(exc))
        return 1
    print(f"created user: {record.username}  role={record.role}  id={record.id}")
    return 0


async def _cmd_list(repo: UserRepository, *, limit: int) -> int:
    records = await repo.list_all(limit=limit)
    _print_table(records)
    return 0


async def _cmd_set_password(repo: UserRepository, *, username: str, password: str) -> int:
    record = await repo.get_by_username(username)
    if record is None:
        logger.error("user not found: %s", username)
        return 1
    try:
        await repo.update(record.id, new_password=password)
    except ValueError as exc:
        logger.error(str(exc))
        return 1
    print(f"password rotated for {username}")
    return 0


async def _cmd_set_role(repo: UserRepository, *, username: str, role: str) -> int:
    record = await repo.get_by_username(username)
    if record is None:
        logger.error("user not found: %s", username)
        return 1
    try:
        updated = await repo.update(record.id, role=role)
    except UnknownRoleError as exc:
        logger.error(str(exc))
        return 1
    print(f"{username}: role → {updated.role}")
    return 0


async def _cmd_set_active(repo: UserRepository, *, username: str, is_active: bool) -> int:
    record = await repo.get_by_username(username)
    if record is None:
        logger.error("user not found: %s", username)
        return 1
    updated = await repo.update(record.id, is_active=is_active)
    print(f"{username}: active → {updated.is_active}")
    return 0


async def _cmd_delete(repo: UserRepository, *, username: str) -> int:
    record = await repo.get_by_username(username)
    if record is None:
        logger.error("user not found: %s", username)
        return 1
    ok = await repo.delete(record.id)
    if not ok:  # pragma: no cover — race with concurrent delete
        logger.error("delete failed: %s", username)
        return 2
    print(f"deleted user: {username}")
    return 0


# --------------------------------------------------------------------------- CLI


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="formulation-admin-users",
        description=(
            "Manage the ``user`` table (bootstrap the first admin, "
            "rotate passwords, list roles) without opening the database."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_admin = sub.add_parser(
        "create-admin",
        help="Create a user with role Admin (bootstrap the first admin).",
    )
    p_admin.add_argument("--username", required=True)
    p_admin.add_argument("--password", required=True)
    p_admin.add_argument("--email", default=None)

    p_create = sub.add_parser("create", help="Create a user with an explicit role.")
    p_create.add_argument("--username", required=True)
    p_create.add_argument("--password", required=True)
    p_create.add_argument("--role", required=True, choices=sorted(VALID_ROLES), metavar="ROLE")
    p_create.add_argument("--email", default=None)

    p_list = sub.add_parser("list", help="List all users.")
    p_list.add_argument("--limit", type=int, default=500)

    p_set_pw = sub.add_parser("set-password", help="Rotate a user's password.")
    p_set_pw.add_argument("--username", required=True)
    p_set_pw.add_argument("--password", required=True)

    p_set_role = sub.add_parser("set-role", help="Change a user's role.")
    p_set_role.add_argument("--username", required=True)
    p_set_role.add_argument("--role", required=True, choices=sorted(VALID_ROLES), metavar="ROLE")

    p_activate = sub.add_parser("activate", help="Re-enable a user.")
    p_activate.add_argument("--username", required=True)

    p_deactivate = sub.add_parser("deactivate", help="Disable a user without deleting them.")
    p_deactivate.add_argument("--username", required=True)

    p_delete = sub.add_parser("delete", help="Hard-delete a user.")
    p_delete.add_argument("--username", required=True)

    return parser


async def _run_command(args: argparse.Namespace) -> int:
    settings = get_settings()
    setup_logging(log_level=settings.log_level, json_logs=False)

    database = Database.from_url(
        url=settings.database_url,
        encryption_key_hex=settings.encryption_key_hex or None,
    )
    try:
        await database.init()
    except Exception as exc:  # pragma: no cover — depends on env
        logger.error("failed to open the database: %s", exc)
        return 2

    repo = UserRepository(database)
    try:
        if args.command == "create-admin":
            return await _cmd_create(
                repo,
                username=args.username,
                password=args.password,
                role="Admin",
                email=args.email,
            )
        if args.command == "create":
            return await _cmd_create(
                repo,
                username=args.username,
                password=args.password,
                role=args.role,
                email=args.email,
            )
        if args.command == "list":
            return await _cmd_list(repo, limit=args.limit)
        if args.command == "set-password":
            return await _cmd_set_password(repo, username=args.username, password=args.password)
        if args.command == "set-role":
            return await _cmd_set_role(repo, username=args.username, role=args.role)
        if args.command == "activate":
            return await _cmd_set_active(repo, username=args.username, is_active=True)
        if args.command == "deactivate":
            return await _cmd_set_active(repo, username=args.username, is_active=False)
        if args.command == "delete":
            return await _cmd_delete(repo, username=args.username)
        # argparse's ``required=True`` already prevents this, but be
        # defensive so mypy sees a return in every branch.
        logger.error("unknown subcommand: %s", args.command)  # pragma: no cover
        return 1  # pragma: no cover
    finally:
        await database.close()


async def _main_async(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv or sys.argv[1:])
    return await _run_command(args)


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_main_async(argv))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["_main_async", "main"]
