"""Minimal, dependable PDF technical card for a Recipe.

The layout is deliberately small and self-contained: the point is
that this renderer always produces a valid, human-readable one-pager
even when the more elaborate marketing PDF builder is not available.

Two entry points:

- :func:`render_recipe_pdf`      — write to a filesystem path (used by
                                    the ``formulation-export-pdf`` CLI).
- :func:`render_recipe_pdf_bytes` — return the PDF as ``bytes`` (used
                                    by the HTTP API to stream a
                                    ``Content-Disposition: attachment``
                                    response without touching disk).

Both share the internal ``_build_story`` helper, so any layout change
lands in both call sites at once.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...domain.entities.recipe import Recipe


def _build_story(recipe: Recipe) -> list[Any]:
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    story: list[Any] = []

    # ---- Header ---------------------------------------------------
    header = f"{recipe.category} — {recipe.subcategory}"
    story.append(Paragraph(f"<b>{_escape(header)}</b>", styles["Title"]))
    story.append(Spacer(1, 6))

    story.append(
        Paragraph(
            "<br/>".join(
                filter(
                    None,
                    [
                        f"<b>ID:</b> {_escape(recipe.id)}",
                        f"<b>Version:</b> {recipe.version}",
                        f"<b>Binder:</b> {_escape(recipe.binder_type)}",
                        f"<b>Class:</b> {_escape(recipe.product_class.value)}",
                        f"<b>Finish:</b> {_escape(recipe.finish)}" if recipe.finish else "",
                        f"<b>Color:</b> {_escape(recipe.color)}" if recipe.color else "",
                        f"<b>Intended use:</b> {_escape(recipe.intended_use)}",
                        (
                            "<b>Status:</b> "
                            f"{_escape(recipe.status.state.value)} "
                            f"({recipe.status.verification_count}"
                            f"/{recipe.status.required_verifications})"
                        ),
                    ],
                )
            ),
            styles["BodyText"],
        )
    )
    story.append(Spacer(1, 12))

    # ---- Composition, one table per stage --------------------------
    for stage in recipe.stages:
        story.append(
            Paragraph(
                f"<b>Stage {stage.stage_number} — {_escape(stage.name)}</b>",
                styles["Heading3"],
            )
        )
        if stage.description:
            story.append(Paragraph(_escape(stage.description), styles["BodyText"]))
        if stage.process is not None:
            details = ", ".join(
                filter(
                    None,
                    [
                        f"Equipment: {_escape(stage.process.equipment)}"
                        if stage.process.equipment
                        else "",
                        (
                            f"{stage.process.rotational_speed_rpm} rpm"
                            if stage.process.rotational_speed_rpm
                            else ""
                        ),
                        (
                            f"{stage.process.temperature_c}°C"
                            if stage.process.temperature_c is not None
                            else ""
                        ),
                        (
                            f"{stage.process.duration_min} min"
                            if stage.process.duration_min is not None
                            else ""
                        ),
                    ],
                )
            )
            if details:
                story.append(Paragraph(f"<i>{details}</i>", styles["BodyText"]))

        rows: list[list[str]] = [["Component", "CAS", "Function", "Mass %", "± %"]]
        total = 0.0
        for comp in stage.components:
            rows.append(
                [
                    comp.name,
                    comp.cas_number,
                    comp.function,
                    f"{comp.mass_percent:.3f}",
                    f"{comp.tolerance_percent:.2f}",
                ]
            )
            total += comp.mass_percent
        rows.append(["", "", "Total", f"{total:.3f}", ""])

        table = Table(rows, hAlign="LEFT", repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5e7eb")),
                    ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f3f4f6")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#9ca3af")),
                    ("ALIGN", (-2, 1), (-1, -1), "RIGHT"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        story.append(table)
        story.append(Spacer(1, 12))

    # ---- Source ---------------------------------------------------
    story.append(
        Paragraph(
            f"<b>Primary source:</b> {_escape(str(recipe.primary_source))}",
            styles["Italic"],
        )
    )
    if recipe.cross_references:
        story.append(Spacer(1, 4))
        story.append(Paragraph("<b>Cross-references:</b>", styles["BodyText"]))
        for ref in recipe.cross_references:
            story.append(Paragraph(f"• {_escape(str(ref))}", styles["BodyText"]))

    return story


def _escape(text: str) -> str:
    """Minimal HTML escape for ReportLab Paragraph markup."""
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_recipe_pdf(recipe: Recipe, output_path: Path) -> None:
    """Render ``recipe`` to a PDF file at ``output_path``."""
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        title=f"Recipe {recipe.id}",
        author="Formulation Workbench",
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36,
    )
    doc.build(_build_story(recipe))


def render_recipe_pdf_bytes(recipe: Recipe) -> bytes:
    """Render ``recipe`` to a PDF in memory and return the bytes.

    Used by the HTTP export endpoint so we don't have to touch the
    filesystem (safer + faster in a container).
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        title=f"Recipe {recipe.id}",
        author="Formulation Workbench",
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36,
    )
    doc.build(_build_story(recipe))
    return buf.getvalue()


def render_catalog_pdf_bytes(recipes: list[Recipe], *, title: str = "Recipe catalog") -> bytes:
    """Render several recipes into one multi-page PDF, one per page.

    Used by the ``GET /catalog/export.pdf`` endpoint.  Between recipes
    a ``PageBreak`` is inserted so every entry begins fresh — the
    document reads like a printed formulary.  A table-of-contents page
    is emitted first so ops can jump straight to a recipe when
    printing a hundred pages.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

    styles = getSampleStyleSheet()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        title=title,
        author="Formulation Workbench",
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36,
    )

    story: list[Any] = []
    story.append(Paragraph(f"<b>{_escape(title)}</b>", styles["Title"]))
    story.append(
        Paragraph(
            f"{len(recipes)} recipe(s) — generated by Formulation Workbench",
            styles["Italic"],
        )
    )
    story.append(Spacer(1, 12))

    # Simple TOC.  Not clickable (would require anchors + a two-pass
    # doc); for a printable formulary a numbered list is enough.
    story.append(Paragraph("<b>Contents</b>", styles["Heading2"]))
    for idx, r in enumerate(recipes, start=1):
        story.append(
            Paragraph(
                f"{idx}. {_escape(r.category)} — {_escape(r.subcategory)} "
                f"(<i>{_escape(r.binder_type)}</i>, {_escape(r.product_class.value)}) "
                f"— <font size=8 color='#666'>{_escape(r.id)}</font>",
                styles["BodyText"],
            )
        )
    story.append(PageBreak())

    for idx, r in enumerate(recipes):
        story.extend(_build_story(r))
        if idx != len(recipes) - 1:
            story.append(PageBreak())

    doc.build(story)
    return buf.getvalue()


__all__ = ["render_recipe_pdf", "render_recipe_pdf_bytes"]
