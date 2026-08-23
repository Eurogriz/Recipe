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


@app.command("recipe-get")
def recipe_get(recipe_id: str = typer.Argument(..., help="Recipe ID to fetch.")) -> None:
    """Fetch a single recipe by ID and print it as JSON."""
    from ..application.use_cases.get_recipe import GetRecipeByIdQuery

    settings = get_settings()
    _init_logging(settings)

    async def _run_get() -> None:
        container = await Container.build(settings)
        try:
            recipe = await container.get_recipe.execute(GetRecipeByIdQuery(recipe_id=recipe_id))
            if recipe is None:
                typer.secho(f"Recipe not found: {recipe_id}", fg=typer.colors.RED)
                raise typer.Exit(code=1)
            payload = {
                "id": recipe.id,
                "category": recipe.category,
                "subcategory": recipe.subcategory,
                "binder_type": recipe.binder_type,
                "product_class": recipe.product_class.value,
                "status": recipe.status.state.value,
                "version": recipe.version,
                "intended_use": recipe.intended_use,
                "stages": [
                    {
                        "stage_number": s.stage_number,
                        "name": s.name,
                        "components": [
                            {
                                "name": c.name,
                                "cas_number": c.cas_number,
                                "function": c.function,
                                "mass_percent": c.mass_percent,
                            }
                            for c in s.components
                        ],
                    }
                    for s in recipe.stages
                ],
                "primary_source": str(recipe.primary_source),
            }
            typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))
        finally:
            await container.close()

    _run(_run_get())


@app.command("verify")
def verify_recipe(
    recipe_id: str = typer.Argument(..., help="Recipe ID to add a verification to."),
    verifier: str = typer.Option(..., "--verifier", help="Verifier user id / login."),
    citation_id: str = typer.Option(
        "manual", "--citation-id", help="Identifier of the citation being verified."
    ),
    comment: str = typer.Option("", "--comment", help="Optional review note."),
) -> None:
    """Add one verification to a recipe (peer review)."""
    from ..application.use_cases.verification_workflow import VerifyRecipeCommand

    settings = get_settings()
    _init_logging(settings)

    async def _run_verify() -> None:
        container = await Container.build(settings)
        try:
            result = await container.verify_recipe.execute(
                VerifyRecipeCommand(
                    recipe_id=recipe_id,
                    verifier=verifier,
                    source_citation_id=citation_id,
                    comment=comment,
                )
            )
            typer.secho(
                f"✓ Verification recorded — {result.status.verification_count}/"
                f"{result.status.required_verifications} "
                f"({result.status.state.value})",
                fg=typer.colors.GREEN,
            )
        finally:
            await container.close()

    _run(_run_verify())


@app.command("audit-log")
def audit_log(
    aggregate_id: str = typer.Option("", "--aggregate-id", help="Filter by recipe id."),
    limit: int = typer.Option(50, help="Max entries returned."),
) -> None:
    """Tail entries from the audit log (newest first)."""
    from sqlalchemy import select

    from ..infrastructure.db.models import AuditLogEntryModel

    settings = get_settings()
    _init_logging(settings)

    async def _run_audit() -> None:
        container = await Container.build(settings)
        try:
            async with container.database.session() as session:
                stmt = (
                    select(AuditLogEntryModel)
                    .order_by(AuditLogEntryModel.timestamp.desc())
                    .limit(limit)
                )
                if aggregate_id:
                    stmt = stmt.where(AuditLogEntryModel.recipe_id == aggregate_id)
                rows = (await session.execute(stmt)).scalars().all()
                for row in rows:
                    typer.echo(
                        json.dumps(
                            {
                                "timestamp": row.timestamp.isoformat(),
                                "action": row.action,
                                "actor": row.actor_label,
                                "recipe_id": row.recipe_id,
                                "changes": row.changes_json,
                                "ip_address": row.ip_address,
                            },
                            default=str,
                            ensure_ascii=False,
                        )
                    )
        finally:
            await container.close()

    _run(_run_audit())


@app.command("backup")
def backup_cmd(
    output_dir: Path = typer.Option(
        Path("./backups"), "--output-dir", help="Directory to place the backup archive in."
    ),
    no_compress: bool = typer.Option(False, "--no-compress", help="Skip gzip."),
) -> None:
    """Create an online backup of the SQLite database."""
    from .commands.backup import _sqlite_path_from_url, backup

    settings = get_settings()
    _init_logging(settings)
    db_path = _sqlite_path_from_url(settings.database_url)
    output_dir.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    from datetime import timezone as _tz

    stamp = datetime.now(_tz.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = backup(db_path, output_dir / f"{db_path.stem}-{stamp}.db", compress=not no_compress)
    typer.secho(f"✓ Backup written: {archive}", fg=typer.colors.GREEN)


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
