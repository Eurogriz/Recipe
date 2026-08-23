# Formulation Workbench — Architecture

**Version:** 1.0.0
**Last updated:** 2026-06-24

> Этот документ описывает архитектуру на высоком уровне. Детальные C4-диаграммы см. в [docs/00-discovery/c4-diagrams.md](docs/00-discovery/c4-diagrams.md) и ER-диаграмму в [docs/00-discovery/er-diagram.md](docs/00-discovery/er-diagram.md).

---

## 1. Архитектурный стиль

**Clean Architecture / Hexagonal Architecture** с CQRS-разделением.

```
┌─────────────────────────────────────────────────────┐
│ Presentation                                        │
│   - Typer CLI  (formulation-workbench)              │
│   - FastAPI    (formulation-api, /docs /metrics)    │
│   - One-shot commands (init-db, import-seed, …)     │
│   - PySide6 desktop (optional, [desktop] extra)     │
└─────────────────────────────────────────────────────┘
                         ↓ uses
┌─────────────────────────────────────────────────────┐
│ Application (use cases, CQRS)                       │
│   - Commands (write) / Queries (read)               │
│   - DTOs, ports (interfaces)                        │
│   - Workflow orchestration                          │
└─────────────────────────────────────────────────────┘
                         ↓ uses
┌─────────────────────────────────────────────────────┐
│ Domain (pure Python, no external deps)              │
│   - Entities, Value Objects, Domain Services        │
│   - Domain Events                                   │
└─────────────────────────────────────────────────────┘
                         ↑ implemented by
┌─────────────────────────────────────────────────────┐
│ Infrastructure                                      │
│   - SQLAlchemy repos (session-scoped adapters)      │
│   - SQLite / SQLCipher / PostgreSQL / MySQL         │
│   - ReportLab PDF · openpyxl · defusedxml (1С)      │
│   - sklearn (advisory, optional [ml] extra)         │
│   - structlog · i18n · DI container · AppSettings   │
└─────────────────────────────────────────────────────┘
```

Все слои упакованы под единый top-level пакет
`formulation_workbench` (см. [ADR-0006](docs/06-ops/ADR-0006-headless-service.md)).

## 2. Dependency Rule

**Ключевое правило**: зависимости направлены **внутрь** — к Domain.

- `domain` **не зависит** ни от чего, кроме stdlib
- `application` зависит только от `domain`
- `infrastructure` зависит от `domain` и `application` (реализует порты)
- `presentation` зависит от `application` (использует use cases)

Это обеспечивает:
- Тестируемость domain-слоя без внешних зависимостей
- Возможность заменить инфраструктуру (SQLite → PostgreSQL, ReportLab → WeasyPrint) без изменения domain
- Долгосрочную поддерживаемость

## 3. Domain Layer

### Entities (агрегаты)
- `Recipe` (aggregate root) — рецептура со всеми стадиями
- `RawMaterial` — справочник сырья (агрегат-самостоятельный, может быть вне Recipe)
- `User` — пользователь системы

### Value Objects
- `CasNumber` — CAS Registry Number (с валидацией формата и контрольной суммы)
- `Isbn` — ISBN-10/ISBN-13 (с валидацией)
- `Doi` — Digital Object Identifier
- `MassPercent` — массовая доля (0..100, с допуском)
- `VerificationStatus` — Draft / PendingReview / Verified / Rejected
- `Citation` — библиографическая ссылка

### Domain Services
- `VerificationRules` — правила верификации (3 источника, primary citation, etc.)
- `ClassRanker` — алгоритм классификации по классу (Premium / Industrial / etc.)

### Domain Events
- `RecipeCreated`, `RecipeUpdated`, `RecipeSubmittedForReview`, `RecipeVerified`, `RecipeRejected`
- `VerificationAdded`, `VerificationAchievedThreshold`

## 4. Application Layer

### Ports (interfaces)
- `RecipeRepository` — порт для чтения/записи рецептур
- `UserRepository` — порт для пользователей
- `VerificationService` — порт для workflow верификации
- `AuditLogger` — порт для записи audit log

### Use Cases (commands)
- `CreateRecipeCommand`
- `UpdateRecipeCommand`
- `SubmitRecipeForReviewCommand`
- `VerifyRecipeCommand`
- `ImportSeedDataCommand`

### Use Cases (queries)
- `GetRecipeByIdQuery`
- `SearchRecipesQuery` (с FTS5)
- `CompareRecipesQuery`
- `GetRecipeStatisticsQuery`

## 5. Infrastructure Layer

### DB
- SQLAlchemy 2.0 (async) поверх SQLite + SQLCipher
- Alembic для миграций
- FTS5 для полнотекстового поиска

### PDF
- ReportLab + Platypus для технологических карт

### 1С
- CommerceML 2.0 XML adapter для экспорта/импорта

### ML
- scikit-learn RandomForest / GradientBoosting для advisory-прогнозов

### Logging
- structlog с JSON-форматом, ротация по размеру

### Security
- Argon2id (passlib) для паролей
- SQLCipher (AES-256) для БД
- cryptography для RSA-операций (в v2)

### i18n
- Babel + gettext, .po-файлы в `locales/{ru,en}/LC_MESSAGES/`

## 6. Presentation Layer

### PySide6 / Qt 6
- QtQuick Controls 2 (Material Design 3 стиль)
- MVVM-паттерн (Qt Model/View)
- Themes: Light / Dark / High Contrast
- Command palette (Ctrl+K) с fuzzy-поиском
- DPI-aware

### Main components
- `MainWindow` — главное окно с меню, toolbar, status bar
- `RecipeEditorView` — многотабовый редактор рецептуры
- `CatalogView` — фильтруемый список с FTS-поиском
- `ComparisonView` — side-by-side до 4 рецептур
- `CalculatorView` — пересчёт партии
- `PredictorView` — прогноз характеристик
- `VerificationPanel` — workflow верификации

## 7. Cross-cutting Concerns

### Dependency Injection
- `dependency-injector` контейнер
- Scopes: singleton (repos, services), transient (use cases)

### Logging
- structlog с JSON-выводом
- Логи пишутся в `logs/` с ротацией
- Каждый доменный объект имеет свой logger

### Configuration
- YAML/JSON в `%APPDATA%\FormulationWorkbench\config.yaml`
- Переменные окружения для overrides

### Error Handling
- Domain exceptions в `domain/exceptions.py`
- Application exceptions в `application/exceptions.py`
- Infrastructure exceptions не "утекают" в application

## 8. Data Flow

### Command (write) flow
```
User → MainWindow → RecipeEditorView → CreateRecipeCommand (use case)
   → RecipeRepository (port) → SqlAlchemyRecipeRepository (impl)
   → SQLAlchemy session → SQLCipher → SQLite file
   → AuditLog entry → structlog
```

### Query (read) flow
```
User → MainWindow → CatalogView → SearchRecipesQuery (use case)
   → RecipeRepository.find_by_criteria()
   → SqlAlchemyRecipeRepository (impl) → SELECT + FTS5
   → RecipeDTO → ViewModel → Qt Model → View
```

## 9. Quality Attributes

| Attribute | Target | Strategy |
|---|---|---|
| **Maintainability** | High | Clean Architecture, type hints, ADRs |
| **Testability** | High (≥85% coverage) | Pure domain, dependency injection |
| **Security** | High | SQLCipher, Argon2id, parameterized queries, RBAC |
| **Performance** | < 500ms для типовых операций | SQLite indexes, FTS5, async |
| **Reliability** | High | Audit log, immutable Verified records |
| **Auditability** | Full | Audit log + version history |
| **i18n** | RU + EN | gettext, locale-aware formatting |

## 10. Technology Decisions

Подробности — в [docs/adr/](docs/adr/):
- ADR-0001: Python + PySide6 стек
- ADR-0002: SQLAlchemy 2.0 async
- ADR-0003: SQLCipher encryption
- ADR-0004: pytest test strategy
- ADR-0005: Babel i18n

## 11. Deployment

```
C:\Program Files\FormulationWorkbench\
├── FormulationWorkbench.exe       ← PyInstaller bundle
├── python311.dll                  ← embedded Python
├── PySide6\                       ← Qt bindings
├── app\                           ← application code
└── resources\                     ← icons, themes, locales

%APPDATA%\FormulationWorkbench\
├── formulation.db                 ← encrypted SQLite
├── config.yaml                    ← user config
├── logs\                          ← log files (rotated)
└── seed-data\                     ← imported recipes

%LOCALAPPDATA%\FormulationWorkbench\
├── pdf-cache\
└── thumbnails\
```

## 12. Future Evolution (Backlog v2.0+)

- Cloud sync (multi-device)
- Mobile companion (iOS+Android)
- LIMS integration (SampleManager, LabWare)
- PostgreSQL enterprise mode
- Advanced ML (XGBoost, neural nets on curated dataset)
- КЭП-подпись техкарт
- Code-signing для публичного распространения
