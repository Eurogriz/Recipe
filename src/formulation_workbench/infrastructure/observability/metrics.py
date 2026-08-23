"""Business-level Prometheus metrics.

All metrics are declared here so they show up on ``/metrics`` even before
the first request has hit the corresponding code path (`prometheus_client`
lazily registers, which makes empty deployments confusing).

Metrics are guarded behind ``prometheus_client`` being importable — the
service still runs headlessly if the dependency is absent.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Sentinel used when prometheus_client is not installed.  All public
# helpers become no-ops so that call sites don't have to check.
_ENABLED = True

try:
    from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram
except ImportError:  # pragma: no cover
    _ENABLED = False


if _ENABLED:
    # A dedicated registry keeps our metrics separate from the process-wide
    # default one, which is useful in tests but also cleaner in production.
    REGISTRY = CollectorRegistry(auto_describe=True)

    RECIPE_OPERATIONS_TOTAL = Counter(
        "formulation_recipe_operations_total",
        "Recipe operations executed, labelled by action and outcome.",
        labelnames=("operation", "outcome"),
        registry=REGISTRY,
    )
    RECIPE_OPERATION_SECONDS = Histogram(
        "formulation_recipe_operation_seconds",
        "Latency of individual recipe operations, in seconds.",
        labelnames=("operation",),
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
        registry=REGISTRY,
    )
    RECIPE_SEARCH_RESULTS = Histogram(
        "formulation_recipe_search_results",
        "Number of recipes returned by a search query.",
        buckets=(0, 1, 5, 10, 25, 50, 100, 250, 500),
        registry=REGISTRY,
    )
    CATALOG_SIZE = Gauge(
        "formulation_catalog_size",
        "Total number of recipes stored in the catalog.",
        registry=REGISTRY,
    )
    CATALOG_SIZE_BY_STATUS = Gauge(
        "formulation_catalog_size_by_status",
        "Number of recipes per verification state.",
        labelnames=("state",),
        registry=REGISTRY,
    )
    APP_INFO = Gauge(
        "formulation_app_info",
        "Static application information exposed as labels.",
        labelnames=("version", "environment"),
        registry=REGISTRY,
    )


class _NullMetric:
    """Fallback that swallows any operation when prometheus is missing."""

    def labels(self, *_args: Any, **_kwargs: Any) -> _NullMetric:
        return self

    def inc(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def observe(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def set(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def get_recipe_operations_total() -> Any:
    return RECIPE_OPERATIONS_TOTAL if _ENABLED else _NullMetric()


def get_recipe_operation_seconds() -> Any:
    return RECIPE_OPERATION_SECONDS if _ENABLED else _NullMetric()


def get_recipe_search_results() -> Any:
    return RECIPE_SEARCH_RESULTS if _ENABLED else _NullMetric()


def get_catalog_size() -> Any:
    return CATALOG_SIZE if _ENABLED else _NullMetric()


def get_catalog_size_by_status() -> Any:
    return CATALOG_SIZE_BY_STATUS if _ENABLED else _NullMetric()


def render_metrics() -> tuple[bytes, str]:
    """Return ``(payload, content_type)`` for the /metrics endpoint."""
    if not _ENABLED:
        return b"# prometheus_client not installed\n", "text/plain; version=0.0.4"
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


def record_app_info(version: str, environment: str) -> None:
    """Set the ``formulation_app_info{version,environment}`` gauge to 1."""
    if _ENABLED:
        with contextlib.suppress(Exception):
            APP_INFO.labels(version=version, environment=environment).set(1)


__all__ = [
    "get_catalog_size",
    "get_catalog_size_by_status",
    "get_recipe_operation_seconds",
    "get_recipe_operations_total",
    "get_recipe_search_results",
    "record_app_info",
    "render_metrics",
]
