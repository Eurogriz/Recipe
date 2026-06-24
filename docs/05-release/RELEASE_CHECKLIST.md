# RELEASE_CHECKLIST.md — Pre/Post Release Checklist

**Document version:** 1.0
**Date:** 2026-06-24

Структурированный чек-лист для контроля качества релиза.

---

## 🔴 Critical (Must-Pass — блокирует релиз)

### Код и архитектура

- [x] Все 5 фаз завершены (Phase 0-5)
- [x] Domain layer покрыт 100% unit-тестами
- [x] Application layer покрыт ≥90% unit-тестами (mock-based)
- [x] Infrastructure layer покрыт ≥75% тестами (integration)
- [x] Все 34+ seed recipes нормализованы и валидированы (sum ≈ 100%)
- [x] Все тесты проходят: `pytest -v` (на Linux/macOS)
- [x] Type-checking: `mypy --strict src/` (на Linux/macOS)
- [x] Linting: `ruff check src tests` (без warnings)
- [x] Pre-commit hooks установлены и активны

### Безопасность

- [x] SQLCipher AES-256 шифрование БД
- [x] Argon2id для производных ключей (OWASP-recommended params)
- [x] Только параметризованные SQL-запросы (SQLAlchemy)
- [x] Argon2id для паролей пользователей
- [x] Ролевая модель: Viewer / Technologist / Admin / Auditor
- [x] Audit log всех изменений
- [x] Никаких секретов в коде / git
- [x] Bandit (security linter) без high-severity warnings

### Документация

- [x] README.md с quick-start
- [x] ARCHITECTURE.md с C4-диаграммами (Context/Container/Component/Deployment)
- [x] CHANGELOG.md (Keep a Changelog format, semver)
- [x] CONTRIBUTING.md (для разработчиков)
- [x] User Manual на русском (≥1000 строк, 11 разделов + FAQ)
- [x] 5 ADRs (Phase 0 + Phase 1)
- [x] ER-диаграмма со всеми таблицами
- [x] Пример рецептуры в финальном формате БД

### Соответствие требованиям

- [x] Тройная верификация реализована в data model
- [x] Все расчётные значения помечены ⚠ advisory
- [x] Дисклеймер на русском и английском (RU + EN)
- [x] Disclaimer в PDF-экспорте
- [x] Disclaimer в About dialog
- [x] README содержит ⚠ предупреждение
- [x] Никаких вымышленных рецептур в seed-данных
- [x] Все seed recipes имеют source_reference с ISBN/DOI
- [x] Cross-references для каждого рецепта

### Локализация

- [x] i18n инфраструктура (Babel/gettext)
- [x] Russian (default) locale — 100% покрытие ключевых строк
- [x] English locale — 100% покрытие ключевых строк
- [x] Все UI строки переводимы (нет hardcoded text в критичных местах)
- [x] Форматирование чисел и дат locale-aware

---

## 🟡 Recommended (желательно для production)

### Тестирование

- [x] Unit-тесты для всех value objects (CAS, ISBN, MassPercent, VerificationStatus)
- [x] Property-based тесты для value objects (hypothesis)
- [x] Calibration script + 5 reference recipes
- [ ] **Manual UAT** на 3-5 реальных рабочих станциях
- [ ] **End-to-end smoke tests** на Windows VM
- [ ] **Performance benchmarks** (время запуска, поиск, импорт)

### Производительность

- [x] FTS5 индекс для поиска по 500+ рецептурам
- [x] SQLAlchemy 2.0 с async для неблокирующего I/O
- [ ] **Профилирование** реальной БД с 500+ записями
- [ ] **Cold start time** < 5 сек (нужно замерить на Windows)
- [ ] **Search latency** < 200 мс для типового запроса

### Документация для пользователей

- [x] User Manual на русском
- [ ] **Видео-демо** (5-10 мин) для onboarding
- [ ] **Quick Reference Card** (A4, печатная версия)
- [ ] **Troubleshooting guide** (FAQ расширенный)

### Развёртывание

- [x] PyInstaller spec для `.exe` сборки
- [x] Inno Setup скрипт для инсталлятора
- [x] Build pipeline скрипт
- [x] Smoke tests для release
- [ ] **Реальная сборка на Windows-машине** (требует Windows)
- [ ] **Тестирование инсталлятора** на чистой Windows VM

---

## 🟢 Optional (nice-to-have, не блокирует MVP)

### Code signing

- [x] **Внутреннее распространение** — без подписи (по выбору)
- [ ] **Публичное распространение** — требует EV/Standard certificate (~$200-500/год)

### CI/CD

- [x] GitHub Actions workflow (lint + tests)
- [ ] **Release workflow** (автоматическая сборка при tag push)
- [ ] **Signed commits** (GPG)
- [ ] **SBOM** (Software Bill of Materials) для compliance

### Enterprise features (Phase 2 v2.0)

- [ ] Cloud sync
- [ ] Multi-factory collaboration
- [ ] КЭП-подпись техкарт
- [ ] 1С 7.7 адаптер
- [ ] PostgreSQL enterprise mode
- [ ] Advanced ML models (XGBoost)

### Мониторинг (в production)

- [ ] Telemetry (опционально, opt-in)
- [ ] Crash reporting
- [ ] Update notifications
- [ ] Usage analytics (для будущих улучшений)

---

## 📋 Pre-Build Checklist (перед `python scripts/release/build.py`)

- [ ] Все git-изменения закоммичены и запушены
- [ ] Версия в `pyproject.toml` обновлена
- [ ] `CHANGELOG.md` обновлён с датой релиза
- [ ] Tag создан: `git tag -a v1.0.0 -m "Release 1.0.0"`
- [ ] На Windows-машине: `pip install -e ".[dev]"`
- [ ] `pre-commit install` выполнен
- [ ] Inno Setup 6 установлен (если нужен инсталлятор)
- [ ] Минимум 2 GB свободного места на диске
- [ ] Backup текущего `dist/` директория

---

## 📋 Post-Build Checklist (после `python scripts/release/build.py`)

- [ ] Все артефакты созданы в `dist/release/v1.0.0/`
- [ ] Smoke tests проходят: `python scripts/release/release_smoke_test.py`
- [ ] SHA-256 checksums записаны и проверены
- [ ] Размер `.exe` в диапазоне 50-200 MB
- [ ] Installer (если создан) в диапазоне 75-110 MB
- [ ] Инсталлятор протестирован на чистой Windows VM
- [ ] Приложение запускается и показывает splash screen
- [ ] Тестовая рецептура создана и сохранена
- [ ] PDF экспорт работает
- [ ] 1С экспорт работает
- [ ] Поиск по каталогу работает (FTS5)
- [ ] Все темы переключаются (Light/Dark/HC)
- [ ] Command Palette открывается (Ctrl+K)

---

## 🚨 Rollback Plan

Если в production обнаружена критическая проблема:

1. **Немедленные действия**:
   - Создать hotfix branch: `git checkout -b hotfix/v1.0.1`
   - Исправить проблему
   - Собрать новую версию: `python scripts/release/build.py`
   - Распространить через те же каналы

2. **Версионирование**:
   - Исправить → v1.0.1 (patch)
   - Новая функциональность → v1.1.0 (minor)
   - Breaking changes → v2.0.0 (major)

3. **Коммуникация**:
   - Email/Slack уведомление всем пользователям
   - Документировать в CHANGELOG.md
   - Создать incident report в docs/05-release/incidents/

---

## ✅ Final Sign-Off

Перед объявлением релиза:

| Роль | Имя | Подпись | Дата |
|---|---|---|---|
| Senior Architect | | | |
| Senior Technologist | | | |
| QA Lead | | | |
| DevOps | | | |
| Product Owner | | | |

---

**Документ обновляется по мере прохождения чек-листа.**
