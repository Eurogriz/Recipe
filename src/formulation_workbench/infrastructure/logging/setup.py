"""Structured logging bootstrap.

The whole application logs through the standard :mod:`logging` module. This
bootstrap wires ``structlog`` as the *formatter* for every stdlib log record
so any handler in the tree (including uvicorn, SQLAlchemy, FastAPI, our own
code) automatically produces JSON (or a friendly console renderer in dev).

Callers should keep using ``logging.getLogger(__name__)``. To attach
structured fields to a record simply pass ``extra={...}`` — those keys are
merged into the JSON payload thanks to
:class:`structlog.stdlib.ProcessorFormatter`.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Any

import structlog


def _build_shared_processors(json_logs: bool) -> list[Any]:
    """Processors applied to *every* record before rendering."""
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.ExtraAdder(),
    ]
    if not json_logs:
        shared.append(structlog.dev.set_exc_info)
    return shared


def setup_logging(
    log_level: str = "INFO",
    log_dir: Path | None = None,
    json_logs: bool = True,
) -> None:
    """Configure ``logging`` + ``structlog`` for the whole process.

    Idempotent: calling it multiple times keeps the last configuration.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)
    shared = _build_shared_processors(json_logs)

    if json_logs:
        renderer: Any = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    handler.setLevel(level)

    root = logging.getLogger()
    # Remove any handler installed by earlier bootstraps (e.g. uvicorn's default).
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)
    root.setLevel(level)

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / "formulation-workbench.log",
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
        root.addHandler(file_handler)

    structlog.configure(
        processors=[
            *shared,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Tame the noisy talkers.
    for noisy in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        lg = logging.getLogger(noisy)
        lg.handlers.clear()
        lg.propagate = True
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger."""
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger


__all__ = ["get_logger", "setup_logging"]
