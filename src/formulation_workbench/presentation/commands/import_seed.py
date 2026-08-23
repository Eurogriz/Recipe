"""``formulation-import-seed`` — bulk import verified recipes from JSON."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

from ...application.use_cases.create_recipe import CreateRecipeCommand
from ...domain.entities.recipe import (
    Component,
    CompositionStage,
    ProcessParams,
    ProductClass,
    Recipe,
)
from ...domain.value_objects.citation import Citation
from ...domain.value_objects.doi import Doi
from ...domain.value_objects.isbn import Isbn
from ...infrastructure.config import AppSettings, get_settings
from ...infrastructure.di import Container
from ...infrastructure.logging.setup import setup_logging

logger = logging.getLogger(__name__)


def _build_citation(raw: dict[str, Any]) -> Citation:
    isbn_val = raw.get("isbn")
    doi_val = raw.get("doi")
    return Citation(
        authors=raw.get("authors", ""),
        title=raw.get("title", ""),
        year=int(raw.get("year", 0)) or 1900,
        publisher=raw.get("publisher", ""),
        isbn=Isbn(isbn_val) if isbn_val else None,
        doi=Doi(doi_val) if doi_val else None,
        url=raw.get("url", ""),
        page_or_formula=raw.get("page_or_formula", ""),
    )


def _build_recipe(raw: dict[str, Any]) -> Recipe:
    stages: list[CompositionStage] = []
    for idx, stage in enumerate(raw.get("stages", []), start=1):
        components = tuple(
            Component(
                name=c["name"],
                cas_number=c.get("cas_number", "mixture"),
                function=c.get("function", "unspecified"),
                mass_percent=float(c["mass_percent"]),
                tolerance_percent=float(c.get("tolerance_percent", 0.0)),
                inci_name=c.get("inci_name", ""),
                manufacturer_reference=c.get("manufacturer_reference", ""),
                notes=c.get("notes", ""),
            )
            for c in stage.get("components", [])
        )
        proc_raw = stage.get("process")
        process = (
            ProcessParams(
                equipment=proc_raw.get("equipment", "unspecified"),
                rotational_speed_rpm=proc_raw.get("rotational_speed_rpm"),
                peripheral_speed_m_per_s=proc_raw.get("peripheral_speed_m_per_s"),
                temperature_c=proc_raw.get("temperature_c"),
                duration_min=proc_raw.get("duration_min"),
            )
            if proc_raw
            else None
        )
        stages.append(
            CompositionStage(
                stage_number=int(stage.get("stage_number", idx)),
                name=stage.get("name", f"Stage {idx}"),
                description=stage.get("description", ""),
                components=components,
                process=process,
            )
        )

    primary = _build_citation(raw["primary_source"])
    cross = tuple(_build_citation(c) for c in raw.get("cross_references", []))
    product_class = ProductClass(raw.get("product_class", "Standard"))

    return Recipe(
        id=raw.get("id"),
        category=raw.get("category", ""),
        subcategory=raw.get("subcategory", ""),
        binder_type=raw.get("binder_type", ""),
        product_class=product_class,
        intended_use=raw.get("intended_use", ""),
        stages=tuple(stages),
        primary_source=primary,
        cross_references=cross,
        created_by=raw.get("created_by", "seed-import"),
        tags=tuple(raw.get("tags", ())),
        finish=raw.get("finish", ""),
        color=raw.get("color", ""),
    )


def _iter_recipes(source: Path) -> list[dict[str, Any]]:
    """Load a file (JSON list/object) or directory of JSON files."""
    result: list[dict[str, Any]] = []
    files = sorted(source.glob("*.json")) if source.is_dir() else [source]
    for f in files:
        try:
            with f.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except json.JSONDecodeError as e:
            logger.warning("Skipping %s: invalid JSON (%s)", f, e)
            continue
        if isinstance(data, list):
            result.extend(x for x in data if isinstance(x, dict))
        elif isinstance(data, dict) and "recipes" in data:
            result.extend(x for x in data["recipes"] if isinstance(x, dict))
        elif isinstance(data, dict):
            result.append(data)
    return result


async def import_seed_from_path(
    source: Path,
    *,
    actor: str = "seed-import",
    settings: AppSettings | None = None,
) -> tuple[int, int]:
    """Import all recipes discovered under ``source``.

    Returns ``(imported, skipped)``.
    """
    settings = settings or get_settings()
    container = await Container.build(settings)
    imported = 0
    skipped = 0
    try:
        for raw in _iter_recipes(source):
            try:
                recipe = _build_recipe(raw)
            except Exception as exc:
                logger.warning("Skipping malformed recipe: %s", exc)
                skipped += 1
                continue
            try:
                await container.create_recipe.execute(
                    CreateRecipeCommand(recipe=recipe, actor=actor)
                )
                imported += 1
            except Exception as exc:
                logger.warning("Failed to persist recipe %s: %s", getattr(recipe, "id", "?"), exc)
                skipped += 1
    finally:
        await container.close()
    return imported, skipped


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Import verified recipes from JSON seed files.")
    p.add_argument("--source", type=Path, required=True, help="File or directory with JSON seeds.")
    p.add_argument("--actor", type=str, default="seed-import")
    args = p.parse_args(argv or sys.argv[1:])

    settings = get_settings()
    setup_logging(log_level=settings.log_level, json_logs=settings.log_json)

    imported, skipped = asyncio.run(import_seed_from_path(args.source, actor=args.actor))
    logger.info("import complete", extra={"imported": imported, "skipped": skipped})
    print(json.dumps({"imported": imported, "skipped": skipped}))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
