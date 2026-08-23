"""Uvicorn launcher (``formulation-api`` script entry point)."""

from __future__ import annotations

import logging

import uvicorn

from ...infrastructure.config import get_settings
from ...infrastructure.logging.setup import setup_logging


def run(host: str | None = None, port: int | None = None, reload: bool = False) -> None:
    """Start uvicorn using the current :class:`AppSettings`."""
    settings = get_settings()
    setup_logging(log_level=settings.log_level, json_logs=settings.log_json)

    logging.getLogger(__name__).info(
        "starting formulation-api",
        extra={
            "host": host or settings.api_host,
            "port": port or settings.api_port,
            "environment": settings.environment,
        },
    )

    uvicorn.run(
        "formulation_workbench.presentation.api.app:create_app",
        factory=True,
        host=host or settings.api_host,
        port=port or settings.api_port,
        reload=reload,
        access_log=False,  # our middleware logs already
    )


def main() -> None:  # pragma: no cover — thin wrapper
    run()


if __name__ == "__main__":  # pragma: no cover
    main()
