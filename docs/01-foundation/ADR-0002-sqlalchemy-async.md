# ADR-0002: SQLAlchemy 2.0 Async ORM

**Status:** Accepted
**Date:** 2026-06-24
**Deciders:** Архитектор, Backend Lead

---

## Context

We need an ORM for the local SQLite + SQLCipher database. SQLAlchemy 2.0 has been released and introduces several improvements:

- Async/await native support via `AsyncSession`
- Type-annotated queries (improved IDE support)
- Improved relationship loading
- Better error messages

We must choose between:
- **Option A:** SQLAlchemy 2.0 (sync + async via `AsyncSession`)
- **Option B:** SQLAlchemy 1.4 (legacy)
- **Option C:** Tortoise ORM (async-first, Django-like)
- **Option D:** SQLModel (Pydantic + SQLAlchemy wrapper)

## Decision

**SQLAlchemy 2.0 with AsyncSession.**

## Rationale

1. **Mature ecosystem:** SQLAlchemy is the de-facto standard Python ORM, with 15+ years of development and extensive documentation.

2. **Migration tooling:** Alembic is the standard migration tool and works seamlessly with SQLAlchemy 2.0.

3. **Async support without compromise:** `AsyncSession` provides full async/await support while maintaining access to all SQLAlchemy features.

4. **Type hints:** SQLAlchemy 2.0's new declarative API has excellent type hint support, which complements our `mypy --strict` policy.

5. **SQLCipher integration:** Documented pattern using `event.listens_for` + `PRAGMA key` is well-tested with SQLAlchemy.

6. **Future PostgreSQL option:** If we add PostgreSQL enterprise mode later, the same code works with minimal changes (just URL).

## Consequences

### Positive
- Mature, well-documented ORM
- Excellent async/await support
- Strong typing with mypy
- Easy migration to PostgreSQL if needed in v2

### Negative (mitigated)
- **Async quirks:** AsyncSession requires careful transaction management — mitigated via context managers (`async with session:`)
- **greenlet dependency:** Adds `greenlet>=3.0` as transitive dependency
- **SQLCipher requires raw SQL for PRAGMA:** Handled via event listener pattern

## Implementation Pattern

```python
# Connection setup with SQLCipher PRAGMAs
from sqlalchemy import event

@event.listens_for(engine.sync_engine, "connect")
def set_sqlcipher_pragmas(dbapi_connection, _):
    cursor = dbapi_connection.cursor()
    cursor.execute(f"PRAGMA key = \"x'{key_hex}'\"")
    for pragma in pragmas:
        cursor.execute(pragma)
    dbapi_connection.commit()

# Async session usage
async with session_factory() as session:
    async with session.begin():
        session.add(recipe_model)
    # Auto-commit on context exit
```

## References
- SQLAlchemy 2.0 docs: https://docs.sqlalchemy.org/en/20/
- Async ORM: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
- Alembic: https://alembic.sqlalchemy.org/
- SQLCipher + SQLAlchemy: https://www.zetetic.net/sqlcipher/sqlcipher-api/
