"""Structured logging setup using structlog.

Provides JSON-formatted logs with rotation, suitable for production.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

import structlog


def setup_logging(
    log_level: str = "INFO",
    log_dir: Path | None = None,
    json_logs: bool = True,
    log_to_console: bool = True,
) -> None:
    """Configure structlog + standard logging.

    Args:
        log_level: Minimum log level (DEBUG, INFO, WARNING, ERROR).
        log_dir: Directory for log files. If None, logs are not persisted.
        json_logs: If True, output JSON. If False, output colored console format.
        log_to_console: If True, also write to stderr.
    """
    # Configure standard logging (structlog uses it as backend)
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=getattr(logging, log_level.upper()),
        force=True,
    )

    # File handler with rotation
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / "formulation-workbench.log",
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(getattr(logging, log_level.upper()))
        logging.getLogger().addHandler(file_handler)

    # Structlog configuration
    if json_logs:
        processors = [
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ]
    else:
        processors = [
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S"),
            structlog.dev.set_exc_info,
            structlog.dev.ConsoleRenderer(colors=log_to_console),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, log_level.upper())),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr) if log_to_console else None,
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a structlog logger by name."""
    return structlog.get_logger(name)
