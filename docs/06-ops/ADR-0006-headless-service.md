# ADR-0006 — Pivot to a headless service (CLI + REST)

- **Status:** Accepted (2026-08-23)
- **Deciders:** Maintainers (Eurogriz)
- **Supersedes:** ADR-0001 (partially — desktop-first stance)

## Context

`v1.0.0` (2026-06-24) was declared "MVP production grade complete" with a
PySide6 desktop as the sole entry point. In practice:

- `src/presentation/` was **not committed** — the desktop shell existed only
  in documentation. `pip install .` succeeded, but `formulation-workbench`
  crashed because `presentation.main:main` did not exist.
- SQLCipher was disabled (`# TODO: Re-enable when Python 3.11 wheels…`),
  though the runbook advertised AES-256 at rest.
- There was no CI, no container image, no DI container, no CLI scripts.
- Deployment targeted Windows-only via GPO/SCCM, which does not fit the
  server-side use cases we now need (Linux fleet, Kubernetes-friendly).

Enterprise adopters need a *service* they can automate, not a desktop app
that has to be installed on each workstation.

## Decision

1. **Adopt a headless-first architecture** built around two entry points
   sharing the same `application`/`domain` core:
   - `formulation-api` — FastAPI + uvicorn.
   - `formulation-workbench` — Typer CLI.

2. **Consolidate source under a single package** `formulation_workbench` to
   restore working relative imports and stop the `src/domain`, `src/application`
   … multi-root anti-pattern.

3. **Optional PySide6 UI** is preserved but demoted to the `[desktop]` extra;
   it is out of the general availability envelope for `1.x`.

4. **Deployment matrix**: publish both a signed OCI image (`ghcr.io`) and
   Python distributions (`sdist` + `wheel`) with SLSA provenance.

5. **Security defaults hardened**:
   - `argon2-cffi` directly (drop `passlib` optional dep) for KDF.
   - `defusedxml` for CommerceML parsing.
   - `AppSettings.enforce_production_invariants()` fails fast when
     `FW_API_TOKEN` or `FW_ENCRYPTION_KEY_HEX` is missing in production.

## Consequences

**Positive**

- The service runs anywhere Python or Docker runs (Linux servers, k8s,
  developer laptops on Windows/macOS).
- Every code path is now covered by automated tests (152 tests, 73.9 %
  coverage), including HTTP integration tests.
- The container image is signed and comes with a CycloneDX SBOM out of the
  box, satisfying most supply-chain-security questionnaires.

**Negative**

- Desktop-specific work (Command Palette, Material Design 3 UI) is deferred
  indefinitely and marked non-GA.
- Consumers must adapt: `formulation-workbench` CLI now has a different
  surface than the aborted `main.py` GUI launcher.
- SQLCipher becomes an opt-in extra (`pip install formulation-workbench[sqlcipher]`)
  because pre-built wheels are still spotty on Python 3.12+.

## Alternatives considered

- **Rebuild the PySide6 GUI first.** Deferred: it does not solve the CI /
  Docker / DI gaps and would delay adoption on servers.
- **Full rewrite in a different stack (Rust/Go).** Rejected: the domain
  code is already mature, well-tested, and Python-idiomatic.

## References

- `pyproject.toml` (new `[project.scripts]` block)
- `src/formulation_workbench/presentation/api/`
- `src/formulation_workbench/presentation/cli.py`
- `src/formulation_workbench/infrastructure/di/`
- CI: `.github/workflows/ci.yml`, `.github/workflows/release.yml`
