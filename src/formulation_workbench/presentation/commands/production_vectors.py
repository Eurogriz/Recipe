"""``formulation-production-vectors`` — ingest drift telemetry from CSV / JSON.

Intended for plant IT and CI jobs: a cron pulls the last N lots from
the plant's ERP into a temporary file and pipes it to this CLI, which
turns each row into a ``production_feature_vector`` row without
needing the HTTP API to be reachable.

Two input formats are auto-detected by extension:

- ``*.json`` — array of ``{"recipe_id": str, "features": [...], "source": str, "notes": str}``.
  ``features`` is optional; when omitted the CLI looks up the recipe
  in the current catalog and extracts the 37-column vector itself.
- ``*.csv``  — header row must include ``recipe_id`` and optionally
  ``source`` + ``notes``; every other column that starts with
  ``mass_percent_``, ``sum_``, ``weighted_``, ``voc_``, ``stage_``
  or ``component_`` (i.e. the canonical FEATURE_NAMES prefixes) is
  read as the feature vector.  Missing feature columns → server-side
  extraction as with JSON.

The command prints a summary in the same shape as
``POST /ml/production-vectors``:

    accepted=N  skipped={item#3: 'recipe not found: ...'}

Exits non-zero when nothing was accepted.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import sys
from pathlib import Path
from typing import Any

from ...application.use_cases.get_recipe import GetRecipeByIdQuery
from ...infrastructure.config import AppSettings, get_settings
from ...infrastructure.di import Container
from ...infrastructure.logging.setup import setup_logging

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- parsing


def _parse_json(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "items" in data:
        data = data["items"]
    if not isinstance(data, list):
        raise ValueError(f"{path.name}: expected a JSON array of items")
    out: list[dict[str, Any]] = []
    for i, row in enumerate(data):
        if not isinstance(row, dict):
            raise ValueError(f"{path.name} item #{i}: expected an object, got {type(row).__name__}")
        out.append(row)
    return out


def _parse_csv(path: Path) -> list[dict[str, Any]]:
    from ...infrastructure.ml.features import FEATURE_NAMES

    feature_prefixes = (
        "mass_percent_",
        "sum_",
        "weighted_",
        "voc_",
        "stage_",
        "component_",
    )
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise ValueError(f"{path.name}: empty file (no header row)")
        header = reader.fieldnames
        # Collect feature columns in the same order they appear in the
        # header — we accept a subset but reject when the ORDER doesn't
        # follow FEATURE_NAMES; the risk of silently mis-aligning
        # columns is too high otherwise.
        feature_cols = [c for c in header if c.startswith(feature_prefixes)]
        if feature_cols and feature_cols != list(FEATURE_NAMES):
            raise ValueError(
                f"{path.name}: feature columns must exactly match FEATURE_NAMES "
                f"(order matters).  Got {feature_cols[:4]}…, expected "
                f"{list(FEATURE_NAMES)[:4]}… (length {len(FEATURE_NAMES)})."
            )
        for row_idx, row in enumerate(reader):
            recipe_id = (row.get("recipe_id") or "").strip()
            if not recipe_id:
                raise ValueError(f"{path.name} row {row_idx + 1}: recipe_id is required")
            item: dict[str, Any] = {
                "recipe_id": recipe_id,
                "source": (row.get("source") or "lab").strip() or "lab",
                "notes": (row.get("notes") or "").strip(),
            }
            if feature_cols:
                try:
                    item["features"] = [float(row[c]) for c in feature_cols]
                except (ValueError, KeyError) as exc:
                    raise ValueError(
                        f"{path.name} row {row_idx + 1}: cannot parse feature "
                        f"columns as float ({exc})"
                    ) from exc
            out.append(item)
    return out


def _parse(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".json":
        return _parse_json(path)
    if path.suffix.lower() == ".csv":
        return _parse_csv(path)
    raise ValueError(f"unsupported extension: {path.suffix!r}; use .csv or .json")


# --------------------------------------------------------------------------- action


async def _ingest(items: list[dict[str, Any]], settings: AppSettings) -> tuple[int, dict[str, str]]:
    from ...infrastructure.ml.features import FEATURE_NAMES, to_vector

    container = await Container.build(settings)
    accepted = 0
    skipped: dict[str, str] = {}
    try:
        rows: list[tuple[str, list[float], str, str]] = []
        for i, item in enumerate(items):
            recipe_id = str(item.get("recipe_id", "")).strip()
            if not recipe_id:
                skipped[f"item#{i}"] = "missing recipe_id"
                continue
            features = item.get("features")
            source = str(item.get("source") or "lab")
            notes = str(item.get("notes") or "")
            if features is not None:
                if not isinstance(features, list) or len(features) != len(FEATURE_NAMES):
                    skipped[f"item#{i}"] = f"features must be a list of {len(FEATURE_NAMES)} floats"
                    continue
                try:
                    vector = [float(v) for v in features]
                except (TypeError, ValueError):
                    skipped[f"item#{i}"] = "features contain a non-numeric value"
                    continue
            else:
                recipe = await container.get_recipe.execute(GetRecipeByIdQuery(recipe_id=recipe_id))
                if recipe is None:
                    skipped[f"item#{i}"] = f"recipe not found: {recipe_id}"
                    continue
                vector = to_vector(recipe)
            rows.append((recipe_id, vector, source, notes))

        if rows:
            ids = await container.production_vector_repository.add_many(rows)
            accepted = len(ids)
    finally:
        await container.close()
    return accepted, skipped


# --------------------------------------------------------------------------- CLI


async def _main_async(argv: list[str] | None = None) -> int:
    """Async body of ``main`` — factored so tests can ``await`` it
    from inside an existing event loop."""
    parser = argparse.ArgumentParser(
        prog="formulation-production-vectors",
        description=(
            "Ingest production feature vectors from a CSV or JSON file (used by drift monitoring)."
        ),
    )
    parser.add_argument(
        "--source",
        type=Path,
        required=True,
        help="Path to a .csv or .json file with rows to ingest.",
    )
    parser.add_argument(
        "--fail-on-any-skip",
        action="store_true",
        help="Exit 2 when at least one row was skipped (default: exit 0 as long as ≥1 was accepted).",
    )
    args = parser.parse_args(argv or sys.argv[1:])

    settings = get_settings()
    setup_logging(log_level=settings.log_level, json_logs=False)

    if not args.source.exists():
        logger.error("source file does not exist: %s", args.source)
        return 1
    try:
        items = _parse(args.source)
    except (ValueError, json.JSONDecodeError) as exc:
        logger.error("failed to parse %s: %s", args.source, exc)
        return 1
    if not items:
        logger.warning("no items to ingest (parser returned an empty list)")
        return 1

    accepted, skipped = await _ingest(items, settings)
    print(f"accepted={accepted}  skipped={skipped}")
    if accepted == 0:
        logger.error("nothing was accepted")
        return 1
    if skipped and args.fail_on_any_skip:
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    """Sync entry point for the console script."""
    return asyncio.run(_main_async(argv))


if __name__ == "__main__":
    raise SystemExit(main())
