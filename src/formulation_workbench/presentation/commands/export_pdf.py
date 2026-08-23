"""``formulation-export-pdf`` — export a single recipe to a PDF technical card."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from ...application.use_cases.get_recipe import GetRecipeByIdQuery
from ...infrastructure.config import get_settings
from ...infrastructure.di import Container
from ...infrastructure.logging.setup import setup_logging

logger = logging.getLogger(__name__)


def _render_pdf(recipe, output_path: Path) -> None:  # type: ignore[no-untyped-def]
    """Delegate to the shared PDF renderer.

    Kept as a thin wrapper so existing callers (tests, docs) don't
    break — the actual rendering lives in
    ``infrastructure.reporting.pdf`` and is reused by the HTTP API.
    """
    from ...infrastructure.reporting import render_recipe_pdf

    render_recipe_pdf(recipe, output_path)


async def _export(recipe_id: str, output: Path) -> None:
    settings = get_settings()
    setup_logging(log_level=settings.log_level, json_logs=settings.log_json)

    container = await Container.build(settings)
    try:
        recipe = await container.get_recipe.execute(GetRecipeByIdQuery(recipe_id=recipe_id))
        if recipe is None:
            raise SystemExit(f"Recipe not found: {recipe_id}")
        output.parent.mkdir(parents=True, exist_ok=True)
        _render_pdf(recipe, output)
        logger.info("exported recipe to %s", output)
    finally:
        await container.close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Export a recipe to a PDF technical card.")
    p.add_argument("--recipe-id", required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args(argv or sys.argv[1:])
    asyncio.run(_export(args.recipe_id, args.output))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
