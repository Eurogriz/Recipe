"""Report renderers (PDF, later maybe DOCX).

Keeps ReportLab a runtime-optional dependency: importing this package
does not touch reportlab, only calling :func:`render_recipe_pdf` does.
"""

from __future__ import annotations

from .pdf import render_catalog_pdf_bytes, render_recipe_pdf, render_recipe_pdf_bytes

__all__ = [
    "render_catalog_pdf_bytes",
    "render_recipe_pdf",
    "render_recipe_pdf_bytes",
]
