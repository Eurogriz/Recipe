# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# Formulation Workbench — production container image.
#
# Multi-stage build:
#   1. `builder` compiles the wheel with all runtime deps.
#   2. `runtime`  is a slim, non-root image running the FastAPI REST facade.
# ---------------------------------------------------------------------------

ARG PYTHON_VERSION=3.11

# ---- builder ---------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        build-essential \
        libffi-dev \
        libssl-dev \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY pyproject.toml README.md ./
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./

# Build a wheel + install into a private venv to copy over cleanly.
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip build \
 && /opt/venv/bin/python -m build --wheel --outdir /tmp/wheels . \
 && /opt/venv/bin/pip install /tmp/wheels/*.whl

# ---- runtime ---------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

# OCI labels for provenance / trace.
ARG APP_VERSION=1.1.0
ARG VCS_REF=unknown
ARG BUILD_DATE=unknown
LABEL org.opencontainers.image.title="formulation-workbench" \
      org.opencontainers.image.description="Verified formulation database REST/CLI service" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.source="https://github.com/Eurogriz/Recipe" \
      org.opencontainers.image.licenses="Proprietary"

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    FW_ENVIRONMENT=production \
    FW_LOG_JSON=true \
    FW_DATA_DIR=/data \
    FW_DATABASE_URL="sqlite+aiosqlite:////data/formulation.db"

# curl kept for the container HEALTHCHECK; tini forwards signals correctly.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl tini \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 10001 appuser \
 && useradd  --system --uid 10001 --gid 10001 --home-dir /app --create-home appuser \
 && mkdir -p /data /exports \
 && chown -R appuser:appuser /data /exports

COPY --from=builder /opt/venv /opt/venv

# Copy migrations and alembic config so `formulation-init-db` and alembic work
# inside the container.
COPY --from=builder /build/migrations /app/migrations
COPY --from=builder /build/alembic.ini /app/alembic.ini

WORKDIR /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl --fail --silent http://localhost:8000/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["formulation-api"]
