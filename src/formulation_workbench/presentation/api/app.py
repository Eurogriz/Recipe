"""FastAPI application factory.

The DI container is initialised in the ``lifespan`` context so it is
shared across all requests and disposed cleanly on shutdown.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import Response

from ... import __version__
from ...infrastructure.config import AppSettings, get_settings
from ...infrastructure.di import Container
from ...infrastructure.observability import configure_tracing
from .middleware import (
    RateLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
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

    # Middleware stack — the last one added runs first on the request path.
    # Order we want on the request path:
    #   RequestContext → SecurityHeaders → CORS → RateLimit → router
    if settings.rate_limit_enabled:
        app.add_middleware(
            RateLimitMiddleware,
            requests_per_minute=settings.rate_limit_per_minute,
        )
    if settings.api_cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.api_cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["*"],
        )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestContextMiddleware)

    app.include_router(router)

    if settings.metrics_enabled:
        try:
            from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

            @app.get("/metrics", include_in_schema=False)
            async def _metrics() -> Response:
                return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
        except ImportError:  # pragma: no cover
            logger.warning("prometheus_client not installed; /metrics disabled")

    configure_tracing(settings, app)

    return app


__all__ = ["create_app"]
