# Formulation Workbench — Makefile
# Usage:
#   make help          — show available targets
#   make install       — install package in dev mode
#   make test          — run tests
#   make lint          — run linters
#   make format        — format code
#   make db-migrate    — apply DB migrations
#   make build         — build production executable
#   make clean         — remove build artifacts

# Detect OS
ifeq ($(OS),Windows_NT)
    PYTHON := python
    RM := rmdir /S /Q
    MKDIR := mkdir
    SEP := \\
else
    PYTHON := python3
    RM := rm -rf
    MKDIR := mkdir -p
    SEP := /
endif

.PHONY: help install install-dev test test-unit test-integration lint format type-check \
        db-init db-migrate db-revision clean build run discover-disclaimer

help: ## Show this help message
	@echo "Formulation Workbench — Makefile targets:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""

install: ## Install package
	$(PYTHON) -m pip install -e .

install-dev: ## Install package with dev dependencies
	$(PYTHON) -m pip install -e ".[dev]"
	$(PYTHON) -m pre_commit install

test: ## Run all tests with coverage
	$(PYTHON) -m pytest

test-unit: ## Run only unit tests
	$(PYTHON) -m pytest -m unit

test-integration: ## Run only integration tests
	$(PYTHON) -m pytest -m integration

lint: ## Run all linters (ruff + mypy + bandit)
	$(PYTHON) -m ruff check src tests
	$(PYTHON) -m bandit -c pyproject.toml -r src/

format: ## Format code with ruff
	$(PYTHON) -m ruff format src tests
	$(PYTHON) -m ruff check --fix src tests

type-check: ## Run mypy strict type checking
	$(PYTHON) -m mypy src

db-init: ## Initialize database (create tables from migrations)
	$(PYTHON) -m alembic upgrade head

db-migrate: ## Apply pending migrations
	$(PYTHON) -m alembic upgrade head

db-revision: ## Create new migration from model changes
	$(PYTHON) -m alembic revision --autogenerate -m "describe change"

build: ## Build production executable (PyInstaller)
	$(PYTHON) -m PyInstaller pyinstaller.spec
	@echo "Built: dist/FormulationWorkbench/FormulationWorkbench.exe"

run: ## Run the application
	$(PYTHON) -m presentation.main

clean: ## Remove build artifacts
	$(RM) build dist .pytest_cache .mypy_cache .ruff_cache htmlcov
	$(RM) *.egg-info
	find . -type d -name "__pycache__" -exec $(RM) {} \;
	find . -type d -name ".venv" -exec $(RM) {} \;
