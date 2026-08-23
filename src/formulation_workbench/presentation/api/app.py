"""FastAPI application factory.

The container is initialised in the ``lifespan`` context so it is
shared across all requests, and disposed cleanly on shutdown.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ... import __version__
from ...infrastructure.config import AppSettings, get_settings
from ...infrastructure.di import Container
from .routes import router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: AppSettings = app.state.settings
    container = await Container.build(settings)
    app.state.container = container
    try:
        yield
    finally:
        await container.close()


def create_app(settings: AppSettings | None = None) -> FastAPI:
    """Build the FastAPI app.

    Passing an explicit :class:`AppSettings` is intended for tests. In
    production the settings singleton is used.
    """
    settings = settings or get_settings()
    settings.enforce_production_invariants()

    app = FastAPI(
        title="Formulation Workbench API",
        version=__version__,
        description=(
            "REST facade for the verified formulation database. "
            "See /docs for OpenAPI and /health for probes."
        ),
        root_path=settings.api_root_path,
        lifespan=_lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    app.state.settings = settings

    if settings.api_cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.api_cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["*"],
        )

    @app.middleware("http")
    async def _request_id_and_timing(request: Request, call_next):  # type: ignore[no-untyped-def]
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        started = time.perf_counter()
        try:
            response: Response = await call_next(request)
        except Exception:
            logger.exception(
                "unhandled exception", extra={"request_id": rid, "path": request.url.path}
            )
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal server error", "code": "internal_error"},
                headers={"x-request-id": rid},
            )
        elapsed_ms = (time.perf_counter() - started) * 1000
        response.headers["x-request-id"] = rid
        response.headers["x-response-time-ms"] = f"{elapsed_ms:.1f}"
        logger.info(
            "request",
            extra={
                "request_id": rid,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round(elapsed_ms, 2),
            },
        )
        return response

    app.include_router(router)

    if settings.metrics_enabled:
        try:
            from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

            @app.get("/metrics", include_in_schema=False)
            async def _metrics() -> Response:
                return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
        except ImportError:  # pragma: no cover
            logger.warning("prometheus_client not installed; /metrics disabled")

    return app


__all__ = ["create_app"]
