"""Main CLI entry point (``formulation-workbench``).

The CLI is built with `Typer <https://typer.tiangolo.com/>`_ and covers
the day-to-day operations of the headless service — database init,
seed import, catalog inspection, and starting the REST API. Individual
one-shot commands (``formulation-init-db``, ``formulation-import-seed``,
``formulation-export-pdf``) reuse the same underlying use cases.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import sys
from pathlib import Path

import typer

from .. import __version__
from ..infrastructure.config import AppSettings, get_settings, reset_settings_cache
from ..infrastructure.di import Container
from ..infrastructure.logging.setup import setup_logging

app = typer.Typer(
    name="formulation-workbench",
    help="Verified formulation database — CLI and API entry points.",
    add_completion=False,
    no_args_is_help=True,
)


def _init_logging(settings: AppSettings) -> None:
    setup_logging(
        log_level=settings.log_level,
        json_logs=settings.log_json,
    )


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


@app.callback()
def _global(
    env_file: Path | None = typer.Option(
        None,
        "--env-file",
        help="Path to a .env file (overrides FW_* environment variables merging).",
        exists=True,
        dir_okay=False,
    ),
) -> None:
    """Global options (loaded before any command)."""
    if env_file is not None:
        # Force a re-load with the given file.
        import os

        os.environ["FW_ENV_FILE"] = str(env_file)
        reset_settings_cache()


@app.command()
def version() -> None:
    """Print the package version and exit."""
    typer.echo(__version__)


@app.command()
def info() -> None:
    """Show effective runtime configuration (secrets are redacted)."""
    settings = get_settings()
    _init_logging(settings)
    redacted = settings.model_dump()
    if redacted.get("encryption_key_hex"):
        redacted["encryption_key_hex"] = "***"
    if redacted.get("api_token"):
        redacted["api_token"] = "***"
    typer.echo(json.dumps(redacted, indent=2, default=str))


@app.command("generate-key")
def generate_key() -> None:
    """Print a fresh 32-byte SQLCipher key (64 hex characters) to stdout."""
    typer.echo(secrets.token_hex(32))


@app.command("init-db")
def init_db(
    drop_first: bool = typer.Option(False, help="Drop existing tables first (DANGEROUS)."),
) -> None:
    """Create all tables from the ORM metadata."""
    from ..infrastructure.db.models import Base

    settings = get_settings()
    _init_logging(settings)

    async def _run_init() -> None:
        container = await Container.build(settings)
        try:
            async with container.database.engine.begin() as conn:
                if drop_first:
                    typer.secho("Dropping existing tables…", fg=typer.colors.YELLOW)
                    await conn.run_sync(Base.metadata.drop_all)
                await conn.run_sync(Base.metadata.create_all)
        finally:
            await container.close()

    _run(_run_init())
    typer.secho("✓ Database schema created.", fg=typer.colors.GREEN)


@app.command()
def stats() -> None:
    """Print catalog statistics (counts per verification state)."""
    settings = get_settings()
    _init_logging(settings)

    async def _run_stats() -> None:
        from ..application.use_cases.search_recipes import GetCatalogStatisticsQuery

        container = await Container.build(settings)
        try:
            result = await container.catalog_stats.execute(GetCatalogStatisticsQuery())
            payload = {
                "total": result.total,
                "by_status": {s.value: n for s, n in result.by_status.items()},
            }
            typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))
        finally:
            await container.close()

    _run(_run_stats())


@app.command()
def search(
    query: str = typer.Argument("", help="Free-text query."),
    limit: int = typer.Option(20, help="Maximum results to return."),
) -> None:
    """Search recipes by full-text query."""
    settings = get_settings()
    _init_logging(settings)

    async def _run_search() -> None:
        from ..application.use_cases.search_recipes import SearchFilter

        container = await Container.build(settings)
        try:
            result = await container.search_recipes.execute(
                SearchFilter(text_query=query, limit=limit)
            )
            for r in result.recipes:
                typer.echo(
                    f"{r.id[:8]}\t{r.category}\t{r.subcategory}\t"
                    f"{r.product_class.value}\t{r.status.state.value}"
                )
            typer.echo(f"\n{len(result.recipes)} result(s), has_more={result.has_more}")
        finally:
            await container.close()

    _run(_run_search())


@app.command("import-seed")
def import_seed(
    source: Path = typer.Argument(
        ..., exists=True, help="JSON file or directory with seed recipes."
    ),
    actor: str = typer.Option("seed-import", help="Actor id recorded in the audit log."),
) -> None:
    """Import recipes from a JSON seed file (or directory of files)."""
    from .commands.import_seed import import_seed_from_path

    settings = get_settings()
    _init_logging(settings)

    imported, skipped = _run(import_seed_from_path(source, actor=actor, settings=settings))
    typer.secho(
        f"✓ Imported {imported} recipe(s); {skipped} skipped.",
        fg=typer.colors.GREEN if imported else typer.colors.YELLOW,
    )


@app.command("serve")
def serve(
    host: str | None = typer.Option(None, help="Bind host (default: FW_API_HOST)."),
    port: int | None = typer.Option(None, help="Bind port (default: FW_API_PORT)."),
    reload: bool = typer.Option(False, help="Enable uvicorn --reload (development only)."),
) -> None:
    """Start the REST API (uvicorn)."""
    from .api.main import run

    settings = get_settings()
    _init_logging(settings)
    run(host=host or settings.api_host, port=port or settings.api_port, reload=reload)


def main() -> None:
    """Entry point for ``python -m formulation_workbench.presentation.cli``."""
    try:
        app()
    except KeyboardInterrupt:  # pragma: no cover
        sys.exit(130)


if __name__ == "__main__":  # pragma: no cover
    main()
