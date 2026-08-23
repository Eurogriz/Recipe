"""``formulation-train-models`` — full-catalogue ML training from the shell.

Wraps :class:`TrainPropertyModelsUseCase` so an operator can retrain
every property regressor after a bulk import, a corpus refresh, or a
schema change to :data:`FEATURE_NAMES`, without going through the
HTTP API (which is throttled by the async-job queue).

Reads ``FW_*`` env-vars exactly like the server — so pointing it at
production or staging is a matter of ``FW_DATABASE_URL=...`` before
the call.  Writes the resulting model bundles to
``FW_MODEL_DIR`` (``./data/models`` by default) — one ``.pkl`` +
``.meta.json`` + ``.samples.json`` per property code.

Flags::

    --property CODE  (repeatable)  Train only the listed property codes.
    --recipe-id ID   (repeatable)  Restrict the training set to these
                                   recipe ids (default: whole catalogue).
    --min-r2 FLOAT                 Fail with exit code 3 when any
                                   trained model's ``mean_cv_r2`` falls
                                   below this threshold.  Useful in CI
                                   to catch a regression in the data.
    --json                         Emit a machine-readable JSON report
                                   on stdout (instead of the default
                                   human summary table).

Exit codes:
    0 — every requested model trained
    1 — user error (bad flags, unreadable DB)
    2 — no training samples (empty catalogue / experiments)
    3 — at least one model fell below ``--min-r2``
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from ...application.use_cases.ml_train import TrainPropertyModelsCommand
from ...infrastructure.config import get_settings
from ...infrastructure.di import Container
from ...infrastructure.logging.setup import setup_logging

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="formulation-train-models",
        description=(
            "Retrain every property regressor from the current catalogue "
            "of experiments.  Writes weights to FW_MODEL_DIR."
        ),
    )
    parser.add_argument(
        "--property",
        dest="properties",
        action="append",
        default=[],
        metavar="CODE",
        help=(
            "Train only the listed property codes (repeat for multiple). "
            "Default: every property present in the experiment corpus."
        ),
    )
    parser.add_argument(
        "--recipe-id",
        dest="recipe_ids",
        action="append",
        default=[],
        metavar="ID",
        help=(
            "Restrict training to the listed recipe ids (repeat for "
            "multiple).  Default: full catalogue enumeration."
        ),
    )
    parser.add_argument(
        "--min-r2",
        type=float,
        default=None,
        metavar="FLOAT",
        help=(
            "Fail with exit code 3 when any trained model's "
            "``mean_cv_r2`` falls below this threshold."
        ),
    )
    parser.add_argument(
        "--json",
        dest="emit_json",
        action="store_true",
        help="Emit a JSON training report on stdout instead of a text table.",
    )
    return parser


def _print_human_summary(result: object) -> None:
    trained = list(getattr(result, "trained", []))
    skipped = dict(getattr(result, "skipped", {}))
    if trained:
        # Fixed-width table so the operator can eyeball degrading
        # metrics across runs.
        cols = ("PROPERTY", "N", "CV R²", "CV σ", "HOLDOUT R²", "HOLDOUT MAE", "ALGO")
        widths = [
            max(9, max((len(m.property_code) for m in trained), default=9)),
            5,
            7,
            7,
            10,
            11,
            30,
        ]
        fmt = "  ".join(f"{{:<{w}}}" for w in widths)
        print(fmt.format(*cols))
        print(fmt.format(*("-" * w for w in widths)))
        for m in trained:
            print(
                fmt.format(
                    m.property_code,
                    str(m.n_samples),
                    f"{m.cv_mean_r2:.3f}",
                    f"{m.cv_std_r2:.3f}",
                    f"{m.holdout_r2:.3f}" if m.holdout_r2 is not None else "-",
                    f"{m.holdout_mae:.3f}" if m.holdout_mae is not None else "-",
                    m.algorithm[:30],
                )
            )
    else:
        print("(no models trained)")
    if skipped:
        print()
        print("Skipped:")
        for code, reason in skipped.items():
            print(f"  {code}: {reason}")


def _emit_json_report(result: object) -> None:
    trained = list(getattr(result, "trained", []))
    skipped = dict(getattr(result, "skipped", {}))
    payload = {
        "trained": [
            {
                "property_code": m.property_code,
                "version": m.version,
                "n_samples": m.n_samples,
                "cv_mean_r2": m.cv_mean_r2,
                "cv_std_r2": m.cv_std_r2,
                "holdout_r2": m.holdout_r2,
                "holdout_mae": m.holdout_mae,
                "holdout_size": m.holdout_size,
                "algorithm": m.algorithm,
                "fingerprint": m.fingerprint,
                "n_features": m.n_features,
            }
            for m in trained
        ],
        "skipped": skipped,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))


async def _main_async(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    if args.min_r2 is not None and not (-1.0 <= args.min_r2 <= 1.0):
        logger.error("--min-r2 must be in the interval [-1, 1]")
        return 1

    settings = get_settings()
    setup_logging(log_level=settings.log_level, json_logs=False)

    try:
        container = await Container.build(settings)
    except Exception as exc:  # pragma: no cover — depends on env
        logger.error("failed to bootstrap container: %s", exc)
        return 1

    try:
        cmd = TrainPropertyModelsCommand(
            recipe_ids=tuple(args.recipe_ids),
            property_codes=tuple(args.properties),
        )
        result = await container.train_property_models.execute(cmd)
    finally:
        await container.close()

    trained = list(getattr(result, "trained", []))
    if not trained:
        # No samples at all → distinct exit code so CI can tell a
        # cold-start from a genuine regression.
        if args.emit_json:
            _emit_json_report(result)
        else:
            _print_human_summary(result)
        logger.error("no models trained — empty experiment corpus?")
        return 2

    if args.emit_json:
        _emit_json_report(result)
    else:
        _print_human_summary(result)

    if args.min_r2 is not None:
        weak = [m for m in trained if m.cv_mean_r2 < args.min_r2]
        if weak:
            logger.error(
                "%d model(s) below --min-r2=%.3f: %s",
                len(weak),
                args.min_r2,
                ", ".join(f"{m.property_code}={m.cv_mean_r2:.3f}" for m in weak),
            )
            return 3

    return 0


def main(argv: list[str] | None = None) -> int:
    """Sync entry point for the console script."""
    return asyncio.run(_main_async(argv))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["_main_async", "main"]
