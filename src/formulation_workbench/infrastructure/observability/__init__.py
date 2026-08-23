"""Optional OpenTelemetry bootstrap.

Activated only when ``FW_OTLP_ENDPOINT`` is set. Import failures are
logged and swallowed so the service continues to run even if the
``[observability]`` extra is not installed.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ..config import AppSettings

logger = logging.getLogger(__name__)


def configure_tracing(settings: AppSettings, app: FastAPI) -> bool:
    """Wire OpenTelemetry to the FastAPI app + SQLAlchemy engine.

    Returns ``True`` if tracing was activated, ``False`` otherwise
    (missing endpoint or missing optional dependencies).
    """
    if not settings.otlp_endpoint:
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning(
            "otel_dependencies_missing",
            extra={
                "hint": "install with: pip install 'formulation-workbench[observability]'",
                "endpoint": settings.otlp_endpoint,
            },
        )
        return False

    resource = Resource.create(
        {
            "service.name": settings.otel_service_name,
            "service.version": _package_version(),
            "deployment.environment": settings.environment,
        }
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otlp_endpoint, insecure=True))
    )
    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app, excluded_urls="health,metrics")

    # SQLAlchemy is instrumented lazily: the engine is only created after the
    # DI container spins up.  We wrap the original lifespan.
    original_lifespan = app.router.lifespan_context

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _lifespan_with_instrumentation(app_):  # type: ignore[no-untyped-def]
        async with original_lifespan(app_):
            container = getattr(app_.state, "container", None)
            if container is not None:
                try:
                    SQLAlchemyInstrumentor().instrument(
                        engine=container.database.engine.sync_engine
                    )
                except Exception:  # pragma: no cover — defensive
                    logger.exception("otel_sqlalchemy_instrumentation_failed")
            yield

    app.router.lifespan_context = _lifespan_with_instrumentation

    logger.info(
        "otel_configured",
        extra={
            "endpoint": settings.otlp_endpoint,
            "service": settings.otel_service_name,
        },
    )
    return True


def _package_version() -> str:
    from ... import __version__

    return __version__


__all__ = ["configure_tracing"]
