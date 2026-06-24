# ADR-0004: Pytest Test Strategy

**Status:** Accepted
**Date:** 2026-06-24
**Deciders:** Архитектор, QA Lead

---

## Context

We need a test strategy for a production-grade application. Requirements:

- Coverage ≥ 85% (target: domain layer 100%, application ≥90%, infrastructure ≥75%)
- Fast feedback loop for developers
- Property-based testing for value objects
- Integration tests with real (encrypted) SQLite
- E2E tests with PySide6 (in CI on Windows runners)

## Decision

**pytest + pytest-asyncio + pytest-qt + pytest-cov + hypothesis + pytest-xdist.**

Test pyramid:
- **Unit tests** (70%): Domain layer, fast, no I/O
- **Integration tests** (20%): Real SQLCipher DB, file I/O
- **E2E tests** (10%): Full Qt UI, in CI on Windows runners

## Rationale

1. **pytest:** Industry standard, mature, excellent plugin ecosystem
2. **pytest-asyncio:** Native async/await support (no `asyncio.run` boilerplate)
3. **pytest-qt:** Qt-specific testing utilities (signal testing, widget assertions)
4. **pytest-cov:** Coverage reporting with branch coverage
5. **hypothesis:** Property-based testing — critical for value objects with invariants (CAS, ISBN, MassPercent)
6. **pytest-xdist:** Parallel test execution for faster CI

## Test Structure

```
tests/
├── conftest.py                # Shared fixtures
├── unit/
│   ├── domain/                # 100% coverage target
│   │   ├── test_cas_number.py
│   │   ├── test_isbn.py
│   │   ├── test_mass_percent.py
│   │   ├── test_verification_status.py
│   │   ├── test_recipe.py
│   │   └── test_class_ranker.py
│   └── application/           # ≥90% coverage target
│       └── test_use_cases.py
├── integration/               # ≥75% coverage target
│   ├── test_db_connection.py
│   ├── test_recipe_repository.py
│   └── test_audit_logger.py
└── e2e/                       # Smoke tests for UI
    └── test_main_window.py
```

## Property-Based Testing Examples

```python
@given(st.integers(min_value=10_000_000, max_value=99_999_999))
def test_random_cas_format_validated(digits: int):
    """Random CAS-formatted strings are validated by checksum logic."""
    # ...
```

## Coverage Targets

| Layer | Target |
|---|---|
| Domain (entities, value objects, services) | **100%** |
| Application (use cases, DTOs) | ≥ 90% |
| Infrastructure (DB, repos) | ≥ 75% |
| Presentation (Qt widgets) | ≥ 60% (UI tests are expensive) |
| **Overall** | **≥ 85%** |

## CI Strategy

- **Lint + Unit tests:** Every push to any branch (Linux runner, ~3 min)
- **Integration tests:** Every PR (Windows runner, ~10 min)
- **E2E tests:** Nightly + before release (Windows runner, ~20 min)
- **Full matrix:** Manual trigger before release

## Consequences

### Positive
- High confidence in domain correctness (100% coverage + property tests)
- Fast feedback during development
- Reproducible test failures via hypothesis seed
- Parallel execution via pytest-xdist

### Negative (mitigated)
- **E2E tests are slow:** Acceptable; run only nightly
- **Qt tests require display:** Use `xvfb` on Linux or Windows runners

## References

- pytest: https://docs.pytest.org/
- hypothesis: https://hypothesis.readthedocs.io/
- pytest-qt: https://pytest-qt.readthedocs.io/
- pytest-asyncio: https://pytest-asyncio.readthedocs.io/
