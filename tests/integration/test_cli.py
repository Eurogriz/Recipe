"""CLI smoke tests via Typer's runner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from formulation_workbench.infrastructure.config import reset_settings_cache
from formulation_workbench.presentation.cli import app

pytestmark = [pytest.mark.integration]


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "cli.db"
    monkeypatch.setenv("FW_DATABASE_URL", f"sqlite+aiosqlite:///{db}")
    monkeypatch.setenv("FW_LOG_JSON", "false")
    reset_settings_cache()


def test_version_command(runner: CliRunner) -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip()


def test_info_command_redacts_secrets(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FW_API_TOKEN", "super-secret")
    monkeypatch.setenv("FW_ENCRYPTION_KEY_HEX", "a" * 64)
    reset_settings_cache()

    result = runner.invoke(app, ["info"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["api_token"] == "***"
    assert payload["encryption_key_hex"] == "***"


def test_generate_key_outputs_64_hex(runner: CliRunner) -> None:
    result = runner.invoke(app, ["generate-key"])
    assert result.exit_code == 0
    key = result.stdout.strip()
    assert len(key) == 64
    int(key, 16)  # must be hex


def test_init_db_and_stats(runner: CliRunner) -> None:
    init_result = runner.invoke(app, ["init-db"])
    assert init_result.exit_code == 0, init_result.stdout + (init_result.stderr or "")

    stats_result = runner.invoke(app, ["stats"])
    assert stats_result.exit_code == 0
    body = json.loads(stats_result.stdout)
    assert body["total"] == 0
    assert body["by_status"] == {
        "Draft": 0,
        "PendingReview": 0,
        "Verified": 0,
        "Rejected": 0,
    }
