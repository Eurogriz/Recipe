# Formulation Workbench

Production-grade, headless service for the **verified** formulation database
of paints, coatings, adhesives, sealants, and construction chemistry.

[![CI](https://github.com/Eurogriz/Recipe/actions/workflows/ci.yml/badge.svg)](https://github.com/Eurogriz/Recipe/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/badge/coverage-≥60%25-brightgreen)](https://github.com/Eurogriz/Recipe)
[![Python](https://img.shields.io/badge/python-3.10%20|%203.11%20|%203.12-blue)](https://www.python.org/)
[![License: Proprietary](https://img.shields.io/badge/license-Proprietary-lightgrey.svg)](#license)

> ⚠️ **Disclaimer**: data is advisory. Laboratory validation is required
> before any industrial application.

---

## What it is

A headless catalog + reasoning engine for verified formulations. Two entry
points share one core:

- **`formulation-api`** — FastAPI REST facade with OpenAPI at `/docs`,
  liveness at `/health`, build metadata at `/info`, Prometheus (business +
  runtime metrics) at `/metrics`, JSON logs, request-id middleware,
  bearer-token auth, security headers and rate limiting.
- **`formulation-workbench`** — Typer CLI for day-to-day admin tasks:
  `init-db`, `import-seed`, `stats`, `search`, `recipe-get`, `verify`,
  `audit-log`, `backup`, `generate-key`, `serve`, `info`, `version`.
- **`formulation-backup`** — dedicated online backup / restore command
  (safe against concurrent writers, gzip + SHA-256 sidecar).

Both are packaged as:

- a Python distribution (`sdist` + `wheel`, PEP 517),
- a signed OCI container image (`ghcr.io/eurogriz/recipe`, cosign keyless,
  multi-arch `linux/amd64,linux/arm64`, non-root, distroless-ish).

## Product scope

- Varnishes (alkyd, PU, NC, acrylic, epoxy, UV-cured).
- Paints (water-based, alkyd, silicate, silicone, epoxy, PU).
- Tinting pastes.
- Adhesives (PVA, cyanoacrylate, epoxy, PU, contact, hot-melt, MS-polymer).
- Sealants (silicone, acrylic, PU, thiokol, butyl, MS-polymer).
- Mastics (bitumen, rubber, acrylic).
- Primers, putties, plasters, self-levelling floors, screeds.
- Anti-corrosion, fire-retardant, waterproofing coatings.

## Architecture

Clean / hexagonal, single top-level package:

```
src/formulation_workbench/
├── domain/          # pure Python: entities, value objects, services
├── application/     # use cases, CQRS, ports
├── infrastructure/  # SQLAlchemy repos, ReportLab, sklearn, 1C adapters,
│                    # DI container, config, logging, i18n
└── presentation/    # Typer CLI, FastAPI app, one-shot command scripts
```

Details: [ARCHITECTURE.md](ARCHITECTURE.md).

## Stack

| Layer         | Technology                                                  |
| ------------- | ----------------------------------------------------------- |
| Language      | Python ≥ 3.10 (tested on 3.10/3.11/3.12)                    |
| API           | FastAPI + uvicorn                                           |
| CLI           | Typer                                                       |
| Persistence   | SQLAlchemy 2 async · Alembic · SQLite (± SQLCipher AES-256) |
| Optional SQL  | PostgreSQL / MySQL via async drivers                        |
| Validation    | Pydantic v2 + pydantic-settings                             |
| Security      | argon2-cffi · cryptography · defusedxml                     |
| ML (advisory) | scikit-learn (optional `[ml]` extra)                        |
| PDF / Excel   | ReportLab · openpyxl                                        |
| 1С            | CommerceML 2.0 XML (import via defusedxml)                  |
| Observability | structlog · Prometheus · OpenTelemetry (optional)           |
| Tests         | pytest · pytest-asyncio · httpx · hypothesis                |

## Quick start

### Local (Python)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 1. Create schema
formulation-workbench init-db

# 2. (Optional) import a seed dataset
formulation-workbench import-seed seed-data/

# 3. Explore
formulation-workbench stats
formulation-workbench search "acrylic"

# 4. Serve the API
formulation-workbench serve            # http://localhost:8000/docs
```

### Docker

```bash
cp .env.example .env
# Generate a strong SQLCipher key (only if you use SQLCipher):
docker compose run --rm api formulation-workbench generate-key

docker compose up --build api          # http://localhost:8000
```

## Configuration

Every setting is loaded from environment variables (prefix `FW_`) or a `.env`
file. The full list lives in
[`src/formulation_workbench/infrastructure/config/__init__.py`](src/formulation_workbench/infrastructure/config/__init__.py).

Key variables:

| Variable                | Default                                     | Notes                                       |
| ----------------------- | ------------------------------------------- | ------------------------------------------- |
| `FW_ENVIRONMENT`        | `development`                               | `production` triggers strict invariants     |
| `FW_DATABASE_URL`       | `sqlite+aiosqlite:///./data/formulation.db` | Any SQLAlchemy async URL                    |
| `FW_ENCRYPTION_KEY_HEX` | *(empty)*                                   | 64 hex chars → SQLCipher AES-256            |
| `FW_API_TOKEN`          | *(empty)*                                   | Required in production; enables Bearer auth |
| `FW_LOG_JSON`           | `true`                                      | JSON structured logs                        |
| `FW_METRICS_ENABLED`    | `true`                                      | Exposes `/metrics` (Prometheus format)      |

Running in production without `FW_API_TOKEN` or `FW_ENCRYPTION_KEY_HEX`
(SQLite only) fails fast at startup.

## Operations

| Task | Command |
| --- | --- |
| Fresh install | `formulation-workbench init-db` |
| Backup (cron / Task Scheduler) | `scripts/ops/backup.sh` / `scripts/ops/backup.ps1` |
| One-off backup | `formulation-backup backup --output-dir ./backups` |
| Restore | `formulation-backup restore backup.db.gz --force` |
| Audit trail | `formulation-workbench audit-log --limit 100` |
| Peer review | `formulation-workbench verify RECIPE_ID --verifier alice` |
| Health probe | `curl http://localhost:8000/health` |
| Build info | `curl http://localhost:8000/info` |
| Metrics scrape | `curl http://localhost:8000/metrics` (Prometheus format) |

Business metrics exposed at `/metrics`:

- `formulation_recipe_operations_total{operation,outcome}` — counter per
  use case per outcome.
- `formulation_recipe_operation_seconds{operation}` — latency histogram.
- `formulation_recipe_search_results` — result-size histogram.
- `formulation_catalog_size` and `formulation_catalog_size_by_status{state}`.
- `formulation_app_info{version,environment}`.

## Testing & quality

```bash
make lint            # ruff + bandit
make type-check      # mypy (strict)
make test            # pytest -n auto with coverage
```

CI templates live in [`ci-templates/workflows/`](ci-templates/workflows/) —
copy them into `.github/workflows/` when your GitHub App has the
`workflows` permission. They run on every push:

- Ruff (lint + format check)
- Bandit + pip-audit
- MyPy (`strict`, non-blocking today)
- pytest matrix (Python 3.10/3.11/3.12 × Linux; Python 3.11 × macOS + Windows)
- Docker image build + `/health` smoke test
- CycloneDX SBOM generation

## Release

Tag a version (`v1.1.0`) to trigger `.github/workflows/release.yml`:

- Builds signed wheels + sdist (SLSA v1 provenance attestation).
- Builds a multi-arch container image, pushes to GHCR.
- Signs the image with **cosign** (keyless via GitHub OIDC).
- Attaches an SBOM and a signed manifest to the GitHub release.

See [`SECURITY.md`](SECURITY.md) for the hardening baseline.

## Repository layout

```
.
├── src/formulation_workbench/    # application source
├── tests/                         # unit + integration + security + perf
├── migrations/                    # Alembic
├── docs/                          # ADRs, C4 diagrams, runbooks, user manual
├── seed-data*/                    # verified recipe datasets (JSON)
├── scripts/                       # generators, release helpers
├── Dockerfile                     # multi-stage, non-root, tini
├── docker-compose.yml             # local production-like stack
├── .github/                       # CI, release, dependabot, PR template
├── pyproject.toml                 # PEP 517/518 + ruff + mypy + pytest + bandit
├── SECURITY.md                    # disclosure policy
└── CHANGELOG.md                   # Keep-a-Changelog format
```

## Documentation

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — architectural overview and layer contracts
- [`SECURITY.md`](SECURITY.md) — vulnerability policy and cryptography notes
- [`docs/USER_MANUAL.md`](docs/USER_MANUAL.md) — end-user guide
- [`docs/05-release/OPERATIONS_RUNBOOK.md`](docs/05-release/OPERATIONS_RUNBOOK.md) — deployment, backup, monitoring
- [`docs/00-discovery/`](docs/00-discovery) — ADR 0001-0005 (foundational decisions)
- [`docs/06-ops/ADR-0006-headless-service.md`](docs/06-ops/ADR-0006-headless-service.md) — 1.x pivot to headless service

## License

Proprietary. See individual files for authorship information.
