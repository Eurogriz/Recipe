# Formulation Workbench — Makefile
#
# Usage:
#   make help              — show available targets
#   make install-dev       — install package with dev extras + pre-commit
#   make test              — pytest with coverage
#   make lint              — ruff check + bandit
#   make format            — ruff format + ruff --fix
#   make type-check        — mypy strict
#   make security          — bandit + pip-audit
#   make sbom              — CycloneDX SBOM
#   make db-init           — create DB schema
#   make serve             — run FastAPI (development mode)
#   make docker-build      — build the container image
#   make docker-run        — run the container locally
#   make clean             — remove build/test artefacts

PYTHON ?= python3

.PHONY: help install install-dev test test-fast test-unit test-integration \
        lint format type-check security sbom \
        db-init db-migrate db-revision \
        serve run build docker-build docker-run clean

help:
	@echo "Formulation Workbench — make targets:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""

install: ## Install package (runtime only)
	$(PYTHON) -m pip install -e .

install-dev: ## Install package with dev extras + pre-commit hooks
	$(PYTHON) -m pip install -e ".[dev]"
	$(PYTHON) -m pre_commit install || true

test: ## Run all tests with coverage
	$(PYTHON) -m pytest

test-fast: ## Run tests in parallel, fail fast
	$(PYTHON) -m pytest -n auto -x

test-unit: ## Run unit tests only
	$(PYTHON) -m pytest -m unit

test-integration: ## Run integration tests only
	$(PYTHON) -m pytest -m integration

lint: ## Ruff (lint) + Bandit
	$(PYTHON) -m ruff check src tests
	$(PYTHON) -m ruff format --check src tests
	$(PYTHON) -m bandit -c pyproject.toml -r src

format: ## Format code (ruff format + autofix)
	$(PYTHON) -m ruff format src tests
	$(PYTHON) -m ruff check --fix src tests

type-check: ## mypy strict
	$(PYTHON) -m mypy src/formulation_workbench

security: ## Bandit + pip-audit
	$(PYTHON) -m bandit -c pyproject.toml -r src
	$(PYTHON) -m pip_audit --strict

sbom: ## Generate a CycloneDX SBOM to sbom.cdx.json
	$(PYTHON) -m cyclonedx_py environment --output-format json --output-file sbom.cdx.json

db-init: ## Initialise the database schema
	formulation-workbench init-db

db-backup: ## Take an online backup to ./backups
	formulation-backup backup --output-dir ./backups

db-migrate: ## Apply pending Alembic migrations
	$(PYTHON) -m alembic upgrade head

db-revision: ## Create a new Alembic migration (autogenerate)
	$(PYTHON) -m alembic revision --autogenerate -m "describe change"

serve: ## Run the FastAPI service (development)
	formulation-workbench serve --reload

run: serve ## Alias of serve

build: ## Build sdist + wheel
	$(PYTHON) -m build

docker-build: ## Build the OCI image
	docker build -t formulation-workbench:local .

docker-run: ## Run the OCI image
	docker run --rm -it -p 8000:8000 \
		-e FW_ENVIRONMENT=development \
		formulation-workbench:local

clean: ## Remove build/test artefacts
	rm -rf build dist *.egg-info .pytest_cache .mypy_cache .ruff_cache \
	       htmlcov coverage.xml sbom.cdx.json tmp_*.db data/*.db
	find . -type d -name "__pycache__" -exec rm -rf {} +
