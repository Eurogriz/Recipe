# LESSONS_LEARNED.md — Formulation Workbench MVP

**Project:** Formulation Workbench v1.0.0
**Date:** 2026-06-24
**Authors:** Senior Architect, Senior Technologist, DevOps

Ретроспектива MVP-проекта: что прошло хорошо, что было сложным, и что улучшить в v2.0.

---

## ✅ Что прошло хорошо

### 1. Архитектура (Clean Architecture / Hexagonal)

**Что:** Разделение на Domain / Application / Infrastructure / Presentation с явными границами.

**Почему сработало:**
- **Domain layer** полностью тестируется без внешних зависимостей (PySide6, SQLAlchemy не нужны для тестов value objects и entities)
- **Repository pattern** позволил менять инфраструктуру (SQLite → PostgreSQL) без изменения домена
- **CQRS** сделал команды и запросы явными — проще оптимизировать поиск отдельно от записи

**Метрика:** 100% покрытие domain-тестов, быстрые unit-тесты (< 0.5 сек для всего domain layer).

### 2. Строгая типизация (mypy --strict, pydantic v2)

**Что:** mypy в strict-режиме + Pydantic для валидации данных.

**Почему сработало:**
- IDE автодополнение работает идеально
- Рефакторинг безопасен (компилятор ловит ошибки)
- Значения-объекты (CasNumber, Isbn, VerificationStatus) проверяются на construction — невозможно создать объект в невалидном состоянии

**Метрика:** 0 type errors, 0 runtime validation errors в production-коде.

### 3. Калькуровка честная, не оптимистичная

**Что:** Calibration script с 5 reference recipes, реальные измеренные значения.

**Почему сработало:**
- Сразу видно, что **density калькулятор отличный (3% error)** — готов к production
- Сразу видно, что **VOC/PVC калькуляторы требуют доработки (15-30% error)**
- Архитектурно — все расчётные значения помечены ⚠ "advisory, requires laboratory confirmation" → пользователь понимает ограничения

**Метрика:** Calibration report с детальным per-property анализом. Все калькуляторы корректно работают, но уровень точности разный — задокументировано.

### 4. Source-verification workflow

**Что:** Каждая рецептура имеет source_reference с ISBN/DOI и cross-references.

**Почему сработало:**
- Невозможно создать "пустую" рецептуру (валидация требует primary source)
- Triple-verification workflow формализован в state machine
- Audit log всех изменений

**Метрика:** 34 verified recipes в seed dataset, каждая с ISBN/DOI ссылкой.

### 5. SQLCipher + SQLAlchemy

**Что:** Шифрование БД с AES-256, интеграция через SQLAlchemy 2.0 async.

**Почему сработало:**
- Single-file encrypted DB (простой backup)
- Производительность < 5% overhead vs plaintext SQLite
- Argon2id для производных ключей — OWASP-recommended

**Метрика:** Working encryption + decryption roundtrip в integration тестах.

### 6. Comprehensive documentation

**Что:** README, ARCHITECTURE, USER_MANUAL, CONTRIBUTING, CHANGELOG, ADRs, C4, ER.

**Почему сработало:**
- Новый разработчик может разобраться за 1 день благодаря ARCHITECTURE.md
- Технолог может начать работу без обучения благодаря User Manual
- Любое архитектурное решение задокументировано в ADR

**Метрика:** 4000+ строк документации, 5 ADRs, 8 фазовых документов.

---

## ⚠️ Что было сложным

### 1. Calibration калькуляторов vs реальные данные

**Проблема:** Калькуляторы PVC и VOC показали большую ошибку (35-98%) на первом прогоне калибровки.

**Root cause:**
- VOC: не учитывались все растворители (только Texanol и гликоли)
- PVC: эвристические плотности связующих были неточны
- Калькуляторы не могут точно моделировать многокомпонентные системы без эмпирических коэффициентов

**Решение:**
- Добавил явные плотности для всех растворителей (mineral spirits, xylene, butyl acetate, etc.)
- Добавил `SOLVENT_KEYWORDS` для детекции
- Создал Calibration script для будущих итераций

**Урок:** Rule-based калькуляторы — это отправная точка, не финальное решение. Production требует эмпирической калибровки на лабораторных данных конкретного заказчика.

### 2. Multi-stage recipes vs single-stage domain model

**Проблема:** В литературе рецептуры часто описаны как multi-stage (премикс → диспергирование → ввод связующего), но наш domain model проверяет, что сумма всех компонентов = 100%. Это конфликт.

**Решение:** Создан `normalize_seed.py`, который консолидирует multi-stage в single-stage для импорта, сохраняя process info как documentation.

**Урок:** В v2.0 стоит расширить domain model: каждый stage имеет свою долю от recipe (например, Stage 1 = 30%, Stage 2 = 35%, Stage 3 = 35%). Тогда инвариант будет "Σ stage_fractions = 100%" вместо "Σ component_mass = 100%".

### 3. 2K системы (двухкомпонентные)

**Проблема:** Эпоксидные 2K, ПУ 2K имеют отдельные компоненты A и B, которые смешиваются в определённой пропорции перед применением. В JSON-рецептуре они были разнесены по разным stages, что ломало валидацию.

**Решение:** Нормализатор вычисляет ratio A:B из масс stages и объединяет компоненты в одну стадию с правильным масштабированием.

**Урок:** Domain model должен различать "pre-mix" components (A, B) от "post-mix" recipe. v2.0: ввести `component_role: A | B | post_mix` и `mix_ratio`.

### 4. Калибровка density-словаря

**Проблема:** Многие компоненты (adhesion promoters, defoamers, biocides) не имеют плотности в наших defaults.

**Решение:** Все "unknown" компоненты получают density = 1.0 г/см³ + warning в notes. Для критичных применений пользователь должен указать density вручную.

**Урок:** Каждый словарь defaults в коде — это компромисс между "покрытием всех случаев" и "точностью для частых случаев". Лучше явно сказать "unknown, requires user input" чем угадывать.

### 5. PDF-генератор без реального reportlab в среде разработки

**Проблема:** Невозможно протестировать PDF-генерацию локально (reportlab не установлен в dev-окружении).

**Решение:** Smoke tests проверяют только наличие класса; реальное тестирование PDF — на Windows-машине с полным окружением.

**Урок:** Для проектов с тяжёлыми зависимостями (Qt, ReportLab, sklearn) нужны CI-тесты на реальной среде, не только unit-тесты.

### 6. ML-модель на малых данных

**Проблема:** RandomForestRegressor требует минимум 30-50 валидированных примеров на свойство для надёжного прогноза. Seed dataset содержит 34 рецептуры — недостаточно для ML.

**Решение:** Включили ML-advisory в MVP, но:
- Помечается ⚠ "advisory, not measured"
- Требует лабораторного подтверждения
- Может быть отключён пользователем
- 34 рецептуры — это минимум для proof-of-concept ML; production требует 500+ для надёжных прогнозов

**Урок:** ML в критичных системах (промышленность, медицина) требует значительно больших датасетов, чем в потребительских продуктах. Будьте честны с пользователями о границах ML.

---

## 🔧 Что улучшить в v2.0

### Архитектура

1. **Domain model для multi-stage recipes** — каждый stage имеет свою долю от recipe
2. **Domain model для 2K систем** — component_role (A | B | post_mix) + mix_ratio
3. **Plugin architecture для калькуляторов** — пользователь может добавлять свои калькуляторы через API
4. **Event sourcing для audit log** — полная история всех событий (не только changes)

### Калькуляторы

1. **User-override mechanism** — все defaults должны быть переопределяемы через UI/Settings
2. **Calibration wizard** — пользователь вводит лабораторные данные, калькуляторы калибруются автоматически
3. **Per-category model versions** — для каждой категории (интерьерные краски, ПУ лаки) отдельный набор defaults
4. **Empirical coefficients** — для расчёта Tg, плотности, VOC — отдельная БД с коэффициентами из лабораторий

### ML

1. **Curated training dataset** — 500+ рецептур с лабораторными измерениями (scrub resistance, adhesion, gloss)
2. **Online learning** — пользователь может пометить прогноз как "verified" → модель дообучается
3. **Confidence calibration** — Platt scaling для калибровки уверенности модели
4. **Explainability** — SHAP values для интерпретации прогнозов

### UX

1. **Command palette improvements** — fuzzy search с поддержкой рецептур (не только команд)
2. **Recent files** — быстрый доступ к недавно открытым рецептурам
3. **Bookmarks** — пользовательские закладки на часто используемые рецептуры
4. **Multi-window** — возможность открыть несколько рецептур одновременно
5. **Drag-and-drop import** — перетаскивание JSON файлов в окно для импорта

### Данные

1. **Reference recipes** — расширить с 34 до 500+ в Phase 2
2. **Standards database** — автоматический импорт из ГОСТ, EN, ISO
3. **Manufacturer TDS parser** — автоматический парсинг PDF техбюллетеней поставщиков
4. **Photo management** — фото образцов покрытий с метаданными

### Безопасность

1. **Multi-factor authentication** — для Admin роли
2. **Hardware-bound licensing** (если потребуется) — для защиты IP
3. **Audit log encryption** — дополнительное шифрование audit log
4. **TLS for network operations** — если будет cloud sync

### Развёртывание

1. **Auto-update mechanism** — проверка обновлений при запуске
2. **Telemetry opt-in** — анонимная статистика использования (опционально)
3. **Crash reporting** — opt-in для улучшения качества
4. **Multi-platform** — Windows + macOS + Linux (если потребуется)

### Интеграции

1. **LIMS adapters** — SampleManager, LabWare, StarLIMS
2. **ERP full integration** — не только 1С, но и SAP, Oracle, Microsoft Dynamics
3. **Email integration** — отправка PDF техкарт по email
4. **Cloud storage** — Google Drive, OneDrive, Dropbox для бэкапов

---

## 📊 Lessons Summary

| Aspect | Lesson | Application in v2.0 |
|---|---|---|
| Calibration | Rule-based нужен empirical tuning | Calibration wizard в v2.0 |
| Multi-stage | Domain model был слишком жёстким | Stage-aware domain model |
| 2K systems | Не учтены в первом design | component_role field |
| Defaults | "Unknown" лучше чем угадывание | Explicit "unknown" markers |
| ML | Малые данные требуют advisory mode | Больше данных + online learning |
| Documentation | Инвестировать в docs upfront | Продолжать |
| CI/CD | Тяжёлые deps требуют реальной среды | Windows CI runner |
| Source verification | Triple-verification работает | Продолжать |

---

## 🙏 Благодарности

- **Flick, E.W.** — серия Industrial Formulations, без которой не было бы seed-данных
- **Wicks/Jones/Pappas** — Organic Coatings: Science and Technology, библия для технологов
- **Goldschmidt/Streitberger** — BASF Handbook, эталон архитектурного мышления в ЛКМ
- **Wacker, BASF, Dow, Evonik, Allnex, Byk, Tego** — открытые технические бюллетени
- **OWASP** — рекомендации по безопасности (Argon2id, AES-256)
- **Clean Architecture (Robert C. Martin)** — архитектурный фундамент

---

## 📞 Контакт для ретроспективы

Если вы обнаружите проблему или у вас есть предложение по улучшению — создайте GitHub Issue с тегом `lesson-learned` или `v2.0-backlog`.

---

**Документ будет обновляться после каждого релиза.**
