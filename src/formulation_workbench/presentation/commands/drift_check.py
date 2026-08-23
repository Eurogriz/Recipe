"""``formulation-drift-check`` — scheduled drift check with webhook alerts.

Designed to run from ``cron`` / a k8s ``CronJob``: computes a
per-feature PSI+KS drift report for one property model, comparing the
model's training snapshot against either the current recipe catalog
or the ingested production feature vectors, and posts an alert to
the configured webhook when the worst-per-feature drift level is at
or above ``--dispatch-level``.

Exit codes:
    0  no drift / drift below dispatch threshold
    3  drift at/above dispatch threshold (with successful notification)
    4  drift dispatched but the webhook rejected the payload

That numeric coding makes it easy to page in a shell:

    formulation-drift-check --property gloss_60 || alert-me "$?"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from typing import Literal

from ...infrastructure.config import AppSettings, get_settings
from ...infrastructure.di import Container
from ...infrastructure.logging.setup import setup_logging
from ...infrastructure.notifications import Alert

logger = logging.getLogger(__name__)


Source = Literal["catalog", "production"]
Level = Literal["no_drift", "moderate_drift", "severe_drift"]


async def _run(
    settings: AppSettings,
    *,
    property_code: str,
    source: Source,
    limit: int,
    dispatch_level: Level,
    context: dict[str, str],
    dry_run: bool,
) -> int:
    from ...infrastructure.ml.drift import DriftLevel, compare_feature_matrices
    from ...infrastructure.ml.features import FEATURE_NAMES, to_vector

    container = await Container.build(settings)
    try:
        reference = container.property_regressor.get_training_vectors(property_code)
        if reference is None:
            logger.error("no training snapshot for property_code=%r", property_code)
            return 1

        if source == "production":
            samples = await container.production_vector_repository.list_recent(limit=limit)
            if not samples:
                logger.error(
                    "source=production but no production_feature_vector rows found "
                    "— ingest some first via formulation-production-vectors"
                )
                return 1
            current = [s.features for s in samples]
        else:
            catalog = await container.recipe_repository.find_by_criteria(
                category=None, limit=limit, offset=0
            )
            if not catalog:
                logger.error("catalog is empty")
                return 1
            current = [to_vector(r) for r in catalog]

        reports = compare_feature_matrices(reference, current, feature_names=list(FEATURE_NAMES))
        order = {
            DriftLevel.NO_DRIFT: 0,
            DriftLevel.MODERATE_DRIFT: 1,
            DriftLevel.SEVERE_DRIFT: 2,
        }
        worst = DriftLevel.NO_DRIFT
        for report in reports:
            if order[report.level] > order[worst]:
                worst = report.level
        # Sort worst-first for the payload's top-features list.
        reports.sort(
            key=lambda r: (order[r.level], r.psi, r.ks_statistic),
            reverse=True,
        )

        summary = {
            "property_code": property_code,
            "source": source,
            "n_current": len(current),
            "n_reference": len(reference),
            "worst_level": worst.value,
            "top_features": [
                {
                    "feature": r.feature_name,
                    "level": r.level.value,
                    "psi": round(r.psi, 4),
                    "ks": round(r.ks_statistic, 4),
                }
                for r in reports[:5]
            ],
        }
        # Human-friendly log first, machine-friendly JSON always second
        # so tooling can grep the last line.
        logger.info(
            "drift check: property=%s source=%s worst=%s (n_current=%d, n_reference=%d)",
            property_code,
            source,
            worst.value,
            len(current),
            len(reference),
        )
        print(json.dumps(summary, ensure_ascii=False))

        threshold = order[DriftLevel(dispatch_level)]
        if order[worst] < threshold:
            return 0

        alert = Alert(
            kind="ml.drift",
            severity="critical" if worst == DriftLevel.SEVERE_DRIFT else "warning",
            title=f"Feature drift detected for {property_code}",
            summary=(
                f"Worst level: {worst.value}. "
                f"{len(reports)} features compared "
                f"({len(current)} current vs {len(reference)} reference samples). "
                f"Source: {source}."
            ),
            fields={
                "property_code": property_code,
                "source": source,
                "worst_level": worst.value,
                "n_reference": len(reference),
                "n_current": len(current),
                "top_features": summary["top_features"],
                **context,
            },
        )
        if dry_run:
            logger.warning("dry-run: alert would be dispatched but --dry-run is set")
            print(json.dumps({"dry_run": True, "alert": alert.to_dict()}, ensure_ascii=False))
            return 3

        dispatched = await container.alert_notifier.notify(alert)
        if not dispatched:
            logger.error("notifier rejected the alert (see logs above)")
            return 4
        logger.info("alert dispatched successfully")
        return 3
    finally:
        await container.close()


def _parse_context(pairs: list[str]) -> dict[str, str]:
    """Turn ``["plant=Tallinn", "batch=42"]`` into ``{"plant":"Tallinn", ...}``."""
    ctx: dict[str, str] = {}
    for raw in pairs:
        if "=" not in raw:
            raise argparse.ArgumentTypeError(f"context entries must be key=value, got {raw!r}")
        key, _, value = raw.partition("=")
        key = key.strip()
        if not key:
            raise argparse.ArgumentTypeError(f"empty key in {raw!r}")
        ctx[key] = value.strip()
    return ctx


async def _main_async(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="formulation-drift-check",
        description=(
            "Compute per-feature drift for one property model and, when the "
            "worst level exceeds --dispatch-level, POST a Slack/webhook alert."
        ),
    )
    parser.add_argument(
        "--property",
        dest="property_code",
        required=True,
        help="Property code of the trained model to check (e.g. gloss_60).",
    )
    parser.add_argument(
        "--source",
        choices=["catalog", "production"],
        default="production",
        help="Where to pull the 'current' distribution from (default: production).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="How many rows to sample from the chosen source (default 200).",
    )
    parser.add_argument(
        "--dispatch-level",
        choices=["no_drift", "moderate_drift", "severe_drift"],
        default="moderate_drift",
        help="Minimum worst-per-feature level that triggers a dispatch.",
    )
    parser.add_argument(
        "--context",
        nargs="*",
        default=[],
        metavar="KEY=VALUE",
        help="Extra key=value fields attached to the alert (plant, batch_ref, …).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the alert that would be sent but do not POST it.",
    )
    args = parser.parse_args(argv or sys.argv[1:])

    try:
        context = _parse_context(args.context)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
        return 1

    settings = get_settings()
    setup_logging(log_level=settings.log_level, json_logs=False)

    return await _run(
        settings,
        property_code=args.property_code,
        source=args.source,
        limit=args.limit,
        dispatch_level=args.dispatch_level,
        context=context,
        dry_run=args.dry_run,
    )


def main(argv: list[str] | None = None) -> int:
    """Sync entry point for the console script."""
    return asyncio.run(_main_async(argv))


if __name__ == "__main__":
    raise SystemExit(main())
