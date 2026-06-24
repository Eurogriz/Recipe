# Contributing to Formulation Workbench

**Версия документа:** 1.0.0
**Дата:** 2026-06-24

Спасибо за интерес к проекту! Это **проприетарное** приложение, но мы приветствуем вклад в формате pull requests от утверждённых контрибьюторов.

---

## 🏗️ Code Style

### Python
- **Версия:** Python 3.11+
- **Линтер:** ruff (запускается через pre-commit)
- **Форматтер:** ruff-format
- **Type hints:** обязательны для всех публичных API; mypy --strict для production-кода
- **Docstrings:** Google-style для классов и публичных методов

### Naming Conventions
- Классы: `PascalCase`
- Функции/переменные: `snake_case`
- Константы: `UPPER_SNAKE_CASE`
- Приватные: `_leading_underscore`
- Type aliases: `PascalCase`

### Imports
- `from __future__ import annotations` для forward references
- `isort`-compatible (ruff handles)
- Никаких звёздочных импортов

## 🧪 Testing

### Coverage
- **Минимум:** 85% для production-кода
- Domain layer должен быть **100%** покрыт
- Каждый PR должен поддерживать или увеличивать coverage

### Test Structure
```
tests/
├── unit/                ← быстрые, без I/O
│   ├── domain/          ← entity, value object, domain service tests
│   └── application/     ← use case tests с mock-репозиториями
├── integration/         ← реальная БД (in-memory SQLite), внешние сервисы
│   ├── db/
│   └── pdf/
└── e2e/                 ← полный стек, требует display server
    └── qt/
```

### Property-Based Testing
- Используем `hypothesis` для value objects (CAS, ISBN, MassPercent)
- Минимум 100 примеров на property

## 📝 Commit Messages

Следуем [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Types
- `feat`: новая функциональность
- `fix`: bugfix
- `docs`: только документация
- `style`: форматирование (не меняет логику)
- `refactor`: рефакторинг (не новая функциональность, не bugfix)
- `perf`: улучшение производительности
- `test`: добавление/исправление тестов
- `chore`: build/CI/tools
- `revert`: откат коммита

### Scopes
- `domain`, `application`, `infrastructure`, `presentation`
- `db`, `pdf`, `ml`, `i18n`, `ui`
- `ci`, `build`, `docs`, `tests`

### Examples
```
feat(domain): add VerificationStatus value object

- Add VerificationStatus enum with state transitions
- Add VerificationRules domain service
- Add property tests for state transitions

Closes #42
```

## 🔀 Pull Request Process

1. **Создайте feature branch** от `main`:
   ```bash
   git checkout -b feat/my-feature
   ```

2. **Реализуйте изменения** с тестами (coverage не должен падать)

3. **Убедитесь что pre-commit проходит**:
   ```bash
   pre-commit run --all-files
   ```

4. **Запустите тесты**:
   ```bash
   pytest
   ```

5. **Убедитесь что mypy strict проходит**:
   ```bash
   mypy src/
   ```

6. **Обновите документацию** (если меняется публичный API)

7. **Обновите CHANGELOG.md** (в секции "Unreleased")

8. **Создайте PR** с описанием:
   - Что изменилось
   - Почему
   - Как тестировалось
   - Связанные issues

9. **Дождитесь ревью** (минимум 1 approval от maintainer)

## 🐛 Bug Reports

Используйте GitHub Issues. Включите:
- Версию приложения
- ОС и версию
- Шаги для воспроизведения
- Ожидаемое поведение
- Фактическое поведение
- Логи (если есть)
- Скриншоты (если UI-related)

## 📚 Документация

- **Public API docstrings:** обязательны (Google-style)
- **ADRs:** для каждого значимого архитектурного решения — `docs/adr/NNNN-title.md`
- **CHANGELOG.md:** обновляется при каждом PR
- **README/ARCHITECTURE:** обновляются при изменении архитектуры

## 🔒 Security

- **Не коммитьте** секреты, ключи, пароли
- **Все SQL** — только через SQLAlchemy (параметризованные запросы)
- **Пароли** — только Argon2id (passlib)
- **Внешние данные** — всегда валидируйте через Pydantic

## 📜 License

Все контрибуции подпадают под проприетарную лицензию проекта.

## 🤝 Code Review Guidelines

Ревьюер проверяет:
- [ ] Код соответствует архитектурным слоям (Clean Architecture)
- [ ] Domain не зависит от инфраструктуры
- [ ] Все edge cases покрыты тестами
- [ ] Type hints полные (mypy --strict passes)
- [ ] Pre-commit hooks проходят
- [ ] Coverage не упал
- [ ] Документация обновлена
- [ ] Нет "магических" значений без обоснования
- [ ] Нет фабрикаций данных (особенно для рецептур!)

## 🆘 Getting Help

- Архитектурные вопросы → [ARCHITECTURE.md](ARCHITECTURE.md) или ADRs
- Domain knowledge (ЛКМ) → задать в `#tech-support` Slack
- Tooling issues → создать GitHub Issue

---

**Спасибо за вклад!** 🙏
