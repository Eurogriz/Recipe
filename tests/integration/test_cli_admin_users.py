"""Integration tests for the ``formulation-admin-users`` CLI.

Exercises every subcommand against a freshly-created SQLite database
under ``tmp_path``.  Uses the CLI's own ``_main_async`` coroutine so
we can ``await`` from inside pytest-asyncio's loop rather than paying
the price of a fresh interpreter through ``asyncio.run``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from formulation_workbench.infrastructure.config import (
    AppSettings,
    reset_settings_cache,
)
from formulation_workbench.infrastructure.db.connection import Database
from formulation_workbench.infrastructure.db.models import Base
from formulation_workbench.infrastructure.db.repositories.users import UserRepository
from formulation_workbench.presentation.commands.admin_users import _main_async

pytestmark = [pytest.mark.integration]


async def _fresh_db(tmp_path: Path) -> AppSettings:
    """Create a schema-only SQLite DB and pin the settings cache to it."""
    reset_settings_cache()
    db = tmp_path / "admin-users.db"
    dbc = Database.from_url(url=f"sqlite+aiosqlite:///{db}")
    await dbc.init()
    async with dbc.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await dbc.close()
    settings = AppSettings(
        environment="development",
        database_url=f"sqlite+aiosqlite:///{db}",
        api_token="",
        rate_limit_enabled=False,
        model_dir=tmp_path / "models",
    )
    import formulation_workbench.infrastructure.config as cfg

    cfg._cached = settings  # type: ignore[attr-defined]
    return settings


async def _read_user(db_url: str, username: str) -> object | None:
    dbc = Database.from_url(url=db_url)
    await dbc.init()
    repo = UserRepository(dbc)
    try:
        return await repo.get_by_username(username)
    finally:
        await dbc.close()


# --------------------------------------------------------------------------- create-admin


async def test_create_admin_bootstraps_first_user(tmp_path: Path) -> None:
    settings = await _fresh_db(tmp_path)
    rc = await _main_async(
        [
            "create-admin",
            "--username",
            "root",
            "--password",
            "root-password!",
            "--email",
            "a@b",
        ]
    )
    assert rc == 0
    record = await _read_user(settings.database_url, "root")
    assert record is not None
    assert record.role == "Admin"  # type: ignore[attr-defined]
    assert record.email == "a@b"  # type: ignore[attr-defined]
    assert record.is_active is True  # type: ignore[attr-defined]


async def test_create_admin_rejects_duplicate(tmp_path: Path) -> None:
    await _fresh_db(tmp_path)
    await _main_async(["create-admin", "--username", "root", "--password", "root-password!"])
    rc = await _main_async(["create-admin", "--username", "root", "--password", "another"])
    assert rc == 1


async def test_create_admin_rejects_weak_password(tmp_path: Path) -> None:
    await _fresh_db(tmp_path)
    rc = await _main_async(["create-admin", "--username", "root", "--password", "abc"])
    # scrypt hash refuses < 6 chars → surfaced as user error, exit 1.
    assert rc == 1


# --------------------------------------------------------------------------- create with explicit role


async def test_create_with_role(tmp_path: Path) -> None:
    settings = await _fresh_db(tmp_path)
    rc = await _main_async(
        [
            "create",
            "--username",
            "alice",
            "--password",
            "alice-password",
            "--role",
            "Technologist",
        ]
    )
    assert rc == 0
    record = await _read_user(settings.database_url, "alice")
    assert record is not None
    assert record.role == "Technologist"  # type: ignore[attr-defined]


async def test_create_rejects_unknown_role(tmp_path: Path) -> None:
    await _fresh_db(tmp_path)
    # argparse's ``choices=`` triggers SystemExit(2) before our code runs.
    with pytest.raises(SystemExit):
        await _main_async(
            [
                "create",
                "--username",
                "bob",
                "--password",
                "bob-password",
                "--role",
                "Superuser",
            ]
        )


# --------------------------------------------------------------------------- list / set-password / set-role


async def test_list_shows_all_users(tmp_path: Path, capsys) -> None:
    await _fresh_db(tmp_path)
    await _main_async(["create-admin", "--username", "root", "--password", "root-password!"])
    await _main_async(
        ["create", "--username", "alice", "--password", "alice-password", "--role", "Viewer"]
    )
    rc = await _main_async(["list"])
    captured = capsys.readouterr().out
    assert rc == 0
    assert "root" in captured
    assert "alice" in captured
    assert "Admin" in captured
    assert "Viewer" in captured


async def test_set_password_rotates(tmp_path: Path) -> None:
    settings = await _fresh_db(tmp_path)
    await _main_async(["create-admin", "--username", "root", "--password", "root-password!"])

    rc = await _main_async(["set-password", "--username", "root", "--password", "brand-new-secret"])
    assert rc == 0

    # Login with the new password succeeds.
    dbc = Database.from_url(url=settings.database_url)
    await dbc.init()
    repo = UserRepository(dbc)
    try:
        ok = await repo.authenticate("root", "brand-new-secret")
        assert ok is not None
        stale = await repo.authenticate("root", "root-password!")
        assert stale is None
    finally:
        await dbc.close()


async def test_set_password_rejects_unknown_user(tmp_path: Path) -> None:
    await _fresh_db(tmp_path)
    rc = await _main_async(["set-password", "--username", "ghost", "--password", "whatever"])
    assert rc == 1


async def test_set_role_promotes(tmp_path: Path) -> None:
    settings = await _fresh_db(tmp_path)
    await _main_async(
        ["create", "--username", "alice", "--password", "alice-password", "--role", "Viewer"]
    )
    rc = await _main_async(["set-role", "--username", "alice", "--role", "Auditor"])
    assert rc == 0
    record = await _read_user(settings.database_url, "alice")
    assert record.role == "Auditor"  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- activate / deactivate / delete


async def test_deactivate_then_activate(tmp_path: Path) -> None:
    settings = await _fresh_db(tmp_path)
    await _main_async(["create-admin", "--username", "root", "--password", "root-password!"])
    await _main_async(["deactivate", "--username", "root"])
    record = await _read_user(settings.database_url, "root")
    assert record.is_active is False  # type: ignore[attr-defined]
    await _main_async(["activate", "--username", "root"])
    record = await _read_user(settings.database_url, "root")
    assert record.is_active is True  # type: ignore[attr-defined]


async def test_delete_removes_user(tmp_path: Path) -> None:
    settings = await _fresh_db(tmp_path)
    await _main_async(["create-admin", "--username", "root", "--password", "root-password!"])
    rc = await _main_async(["delete", "--username", "root"])
    assert rc == 0
    record = await _read_user(settings.database_url, "root")
    assert record is None


async def test_delete_rejects_unknown_user(tmp_path: Path) -> None:
    await _fresh_db(tmp_path)
    rc = await _main_async(["delete", "--username", "ghost"])
    assert rc == 1
