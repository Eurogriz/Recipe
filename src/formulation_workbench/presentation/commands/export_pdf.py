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
    """Very small PDF renderer built on top of ReportLab.

    Layout is deliberately minimal — the goal is that ``formulation-export-pdf``
    always produces a valid, human-readable technical card even when the more
    elaborate report builder is not available (or misconfigured).
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(output_path), pagesize=A4, title=f"Recipe {recipe.id}")
    story: list = []

    story.append(Paragraph(f"<b>{recipe.category} — {recipe.subcategory}</b>", styles["Title"]))
    story.append(Spacer(1, 6))
    story.append(
        Paragraph(
            f"Binder: {recipe.binder_type}<br/>"
            f"Class: {recipe.product_class.value}<br/>"
            f"Status: {recipe.status.state.value} "
            f"({recipe.status.verification_count}/{recipe.status.required_verifications})",
            styles["BodyText"],
        )
    )
    story.append(Spacer(1, 12))

    for stage in recipe.stages:
        story.append(
            Paragraph(f"<b>Stage {stage.stage_number} — {stage.name}</b>", styles["Heading3"])
        )
        story.append(Paragraph(stage.description or "", styles["BodyText"]))
        rows = [["Component", "CAS", "Function", "Mass %"]]
        for comp in stage.components:
            rows.append([comp.name, comp.cas_number, comp.function, f"{comp.mass_percent:.2f}"])
        table = Table(rows, hAlign="LEFT", repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("ALIGN", (-1, 1), (-1, -1), "RIGHT"),
                ]
            )
        )
        story.append(table)
        story.append(Spacer(1, 12))

    story.append(Paragraph(f"Primary source: {recipe.primary_source}", styles["Italic"]))
    doc.build(story)


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
