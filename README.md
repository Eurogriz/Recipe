# Formulation Workbench

Enterprise desktop-приложение для работы с **верифицированной** базой рецептур лакокрасочных материалов и строительной химии.

> ⚠️ **Дисклеймер**: данные носят справочный характер. Перед промышленным применением требуется лабораторная валидация и адаптация под конкретное сырьё.

---

## 🎯 Назначение

Хранение, поиск, прогнозирование характеристик и генерация технологических карт для рецептур в следующих категориях:

- Лаки (алкидные, ПУ, НЦ, акриловые, эпоксидные, УФ-отверждаемые)
- Краски (водно-дисперсионные, масляные, алкидные, силикатные, силиконовые, эпоксидные, ПУ)
- Колеры и пигментные пасты (универсальные, водные, органоразбавляемые)
- Клеи (ПВА, цианоакрилатные, эпоксидные, ПУ, контактные, термоплавкие, MS-полимерные)
- Герметики (силиконовые, акриловые, ПУ, тиоколовые, бутиловые, MS-полимерные)
- Мастики (битумные, битумно-полимерные, каучуковые, акриловые)
- Грунтовки, шпатлёвки, штукатурки, наливные полы, ровнители
- Антикоррозионные покрытия, огнезащита, гидроизоляция

## 🏗️ Архитектура

**Clean Architecture / Hexagonal** с разделением на слои:

```
src/
├── domain/          ← Pure Python: entities, value objects, services (no external deps)
├── application/     ← Use cases, CQRS, ports
├── infrastructure/  ← SQLAlchemy repos, ReportLab, sklearn, 1C adapters
└── presentation/    ← PySide6 (Qt 6) UI, view-models
```

Подробнее: [ARCHITECTURE.md](ARCHITECTURE.md)

## 🛠️ Технологический стек

| Слой | Технология |
|---|---|
| Язык | Python 3.10+ |
| GUI | PySide6 / Qt 6.6 |
| DB | SQLite 3.45 + SQLCipher 4 (AES-256) |
| ORM | SQLAlchemy 2.0 (async) + Alembic |
| Validation | Pydantic v2 |
| ML | scikit-learn (advisory only) |
| PDF | ReportLab |
| Excel | openpyxl |
| 1С | CommerceML 2.0 XML |
| Логирование | structlog |
| Тесты | pytest + pytest-qt + hypothesis + coverage |

## 📋 Требования

- **OS:** Windows 10/11 (build 19041+)
- **Python:** 3.10
- **RAM:** 8 ГБ минимум, 16 ГБ рекомендуется
- **Disk:** 500 МБ для установки + место для БД

## ⚡ Быстрый старт (разработка)

```bash
# 1. Клонировать репозиторий
git clone https://github.com/your-org/formulation-workbench.git
cd formulation-workbench

# 2. Создать виртуальное окружение
python -m venv .venv
.venv\Scripts\activate  # Windows

# 3. Установить зависимости
pip install -e ".[dev]"

# 4. Установить pre-commit hooks
pre-commit install

# 5. Инициализировать БД
formulation-init-db --db-path ./data/formulation.db --create-encryption-key

# 6. Импортировать стартовый датасет (опционально)
formulation-import-seed --db-path ./data/formulation.db --source ./seed-data/flicks-water-based-vol3.json

# 7. Запустить приложение
formulation-workbench
```

## 🧪 Тестирование

```bash
# Все тесты
pytest

# Только unit
pytest -m unit

# Только integration
pytest -m integration

# С coverage отчётом
pytest --cov=src --cov-report=html

# Конкретный тест
pytest tests/unit/domain/test_recipe.py::test_recipe_validation
```

## 📦 Сборка production-сборки

```bash
# Создать .exe через PyInstaller
pyinstaller pyinstaller.spec

# Создать инсталлятор через Inno Setup
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer/inno-setup.iss

# Результат: dist/FormulationWorkbench-1.0.0-setup.exe
```

## 📚 Документация

- [ARCHITECTURE.md](ARCHITECTURE.md) — Архитектура (C4-диаграммы, паттерны, слои)
- [CONTRIBUTING.md](CONTRIBUTING.md) — Как контрибьютить
- [CHANGELOG.md](CHANGELOG.md) — История изменений
- [docs/00-discovery/](docs/00-discovery/) — Phase 0: Discovery
- [docs/01-foundation/](docs/01-foundation/) — Phase 1: Foundation (ADR-0002..0005)
- [docs/adr/](docs/adr/) — Architecture Decision Records

## 🔐 Безопасность и лицензирование

- БД шифруется SQLCipher (AES-256), ключ из passphrase пользователя (Argon2id)
- Пароли пользователей — Argon2id (passlib)
- Все SQL-запросы — только параметризованные (SQLAlchemy)
- Ролевая модель (Viewer / Technologist / Admin / Auditor)

## 📜 Лицензия

Proprietary. © 2026 Formulation Workbench Team. Все права защищены.

## 🤝 Команда

- Архитектор: [Senior Architect]
- Технолог-консультант (ЛКМ): [Senior Domain Expert]
- DevOps: [part-time]

---

**Версия:** 1.0.0 (Phase 1 — Foundation in progress)
**Последнее обновление:** 2026-06-24
