# Contributing to Formulation Workbench

> Document version: 1.1.0 · 2026-08-23

Thanks for your interest! This is a **proprietary** project, but contributions
via pull requests from approved contributors are welcome.

---

## 1. Environment setup

```bash
git clone https://github.com/Eurogriz/Recipe.git
cd Recipe
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
```

Optional extras: `[postgres]`, `[sqlcipher]`, `[ml]`, `[observability]`,
`[desktop]`.

Run the API locally:

```bash
formulation-workbench init-db
formulation-workbench serve --reload   # http://localhost:8000/docs
```

## 2. Code style

- **Python 3.10+** (CI covers 3.10 / 3.11 / 3.12).
- **Ruff** for linting *and* formatting (`make format`).
- **MyPy** with progressive strictness (`make type-check`). The strict list
  is declared in `pyproject.toml` under `[[tool.mypy.overrides]]` and grows
  every release — new modules should be added to it.
- **Docstrings**: Google-style for public classes and methods.
- **Type hints**: required on every new function / method signature.
- **Naming**: `PascalCase` classes, `snake_case` functions and variables,
  `UPPER_SNAKE_CASE` constants.
- **Error suffix**: new exception classes end with `Error`. The domain
  layer keeps historical `…Violation` names for backwards compatibility.

## 3. Repository layout

```
src/formulation_workbench/
├── domain/          # pure Python — no framework, no I/O
├── application/     # use cases (CQRS), ports, DTOs
├── infrastructure/  # SQLAlchemy, ReportLab, OTEL, DI, config, logging
└── presentation/    # Typer CLI, FastAPI app, one-shot commands
```

**Dependency rule** — inward only:

- `domain` depends on stdlib only.
- `application` depends on `domain`.
- `infrastructure` depends on `domain` + `application` (implements ports).
- `presentation` depends on `application` (uses cases via the DI container).

## 4. Testing

```bash
make test            # unit + integration + security + coverage
pytest -m unit       # only unit tests
pytest -m api        # only FastAPI tests
pytest -k middleware # match by name
```

- Every new module ships with at least a smoke test.
- Bugfixes must include a regression test.
- API changes require an integration test in
  `tests/integration/test_api*.py`.
- Coverage gate is 60 % (real level currently ~74 %).

## 5. Migrations

- SQLAlchemy models live in `src/formulation_workbench/infrastructure/db/models.py`.
- Any schema change must be followed by:

  ```bash
  alembic revision --autogenerate -m "describe change"
  ```

- Review the generated file: prune noise, add data migrations if needed.
- `tests/integration/test_migrations.py` asserts that the schema produced
  by migrations equals the schema produced by ORM metadata. This test **will
  fail** until you commit the new revision.

## 6. Configuration & secrets

- All runtime configuration is loaded via `AppSettings` from environment
  variables prefixed with `FW_` (see `.env.example`).
- Never check in real secrets. Use `.env` locally (git-ignored) and a
  proper secret manager in production.
- Adding a new setting: extend `AppSettings`, add a documented default in
  `.env.example`, add a validation test in
  `tests/unit/infrastructure/test_config.py`.

## 7. Commit / PR conventions

- Follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/).
  Common types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `ci`,
  `perf`. Breaking changes: append `!` (e.g. `feat!:`).
- Fill in the PR template checklist honestly — CI enforces most of it.
- Keep PRs focused. Cross-layer refactors should be split.

## 8. Release process

Tag a version (`v1.2.0`) on `main`. GitHub Actions (`release.yml`) will:

1. build signed `sdist` + `wheel` with SLSA provenance;
2. build and push a multi-arch OCI image to `ghcr.io/eurogriz/recipe`;
3. sign the image with **cosign** (keyless);
4. attach SBOM + provenance to the GitHub release;
5. generate release notes automatically.

Pre-tag checklist:

- [ ] `CHANGELOG.md` updated with the new version.
- [ ] Version bumped in `src/formulation_workbench/__init__.py` and
      `pyproject.toml`.
- [ ] `make lint && make type-check && make test && make sbom` all pass.

## 9. Security

See [`SECURITY.md`](SECURITY.md) for how to report vulnerabilities and
what the hardened baseline covers.
