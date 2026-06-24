# Formulation Workbench — MVP Scope Agreement (Phase 0 deliverable)

**Document version:** 1.0.0
**Date:** 2026-06-24
**Status:** Awaiting sign-off

---

## 1. Executive Summary

Enterprise-grade desktop-приложение для технологов R&D и производства, работающих с **верифицированной** базой рецептур ЛКМ и строительной химии. Позиционирование — внутренний "Formulation Workbench" уровня BASF Formulation Studio / Henkel R&D Suite. Ключевая особенность — **строгая политика верификации источников** и **разделение расчётных и измеренных значений**.

## 2. Locked Decisions

| # | Параметр | Решение |
|---|---|---|
| 1 | Target OS | Windows 10/11 (build 19041+) |
| 2 | Distribution | Internal (MSI через IT-деплоймент / GPO / SCCM / прямой .exe) |
| 3 | User mode | Single-user (per-workstation) |
| 4 | DB | SQLite 3.45 + SQLCipher 4 (AES-256) |
| 5 | ORM | SQLAlchemy 2.0 (async) + Alembic |
| 6 | GUI framework | PySide6 / Qt 6.6+ |
| 7 | Язык приложения | Python 3.11+ |
| 8 | Локализация | RU (default) + EN (i18n через Babel/gettext) |
| 9 | Packaging | PyInstaller + Inno Setup (`.exe` инсталлятор) |
| 10 | PDF generation | ReportLab + Platypus |
| 11 | ML | scikit-learn (RandomForest / GradientBoosting) — advisory only, помечается ⚠ |
| 12 | Интеграция с 1С | CommerceML 2.0 XML (экспорт рецептур + импорт справочника сырья) |
| 13 | Лицензирование | Нет (free / open-core, без модуля лицензирования) |
| 14 | Code-signing | Не требуется для MVP (внутреннее распространение) |
| 15 | Hardware target | Стандартные Windows-рабочие станции (i5/i7, 16+ ГБ RAM, 1920×1080+ / HiDPI ready) |
| 16 | Mobile companion | Нет в v1.0, в backlog v2.0 |
| 17 | Data migration | Нет (clean start, контент собирается заново из верифицированных источников) |
| 18 | Seed data | ≥ 500 верифицированных рецептур в 7 категориях |

## 3. Категории продуктов в MVP (7)

1. **Лаки** (алкидные, ПУ, НЦ, акриловые, эпоксидные, УФ-отверждаемые) — ~60 рецептур
2. **Краски** (водно-дисперсионные, масляные, алкидные, силикатные, силиконовые, эпоксидные, ПУ) — ~100 рецептур
3. **Колеры и пигментные пасты** (универсальные, водные, органоразбавляемые) — ~60 рецептур
4. **Клеи** (ПВА, цианоакрилатные, эпоксидные, ПУ, контактные, термоплавкие, MS-полимерные) — ~80 рецептур
5. **Герметики** (силиконовые, акриловые, ПУ, тиоколовые, бутиловые, MS-полимерные) — ~60 рецептур
6. **Мастики** (битумные, битумно-полимерные, каучуковые, акриловые) — ~50 рецептур
7. **Грунтовки, шпатлёвки, штукатурки, наливные полы, ровнители + Антикоррозия/Огнезащита/Гидроизоляция** — ~90 рецептур

**Итого:** ≥ 500 записей.

По классам продукта (SuperEconomy / Economy / Standard / Premium / SuperPremium / Industrial / Specialty) — пропорция 10/20/30/20/5/10/5 %.

## 4. Архитектурный паттерн

**Clean Architecture / Hexagonal:**

```
┌─────────────────────────────────────────────────────┐
│ Presentation (PySide6 / Qt 6)                       │
│   - ViewModels (MVVM), Command Palette (Ctrl+K)     │
│   - Material Design 3 / Fluent Design              │
│   - Themes: Light / Dark / High Contrast            │
└─────────────────────────────────────────────────────┘
                         ↓ uses
┌─────────────────────────────────────────────────────┐
│ Application (use cases, CQRS)                       │
│   - Commands (write)  / Queries (read)               │
│   - DTOs, ports (interfaces)                        │
│   - Workflow: Draft → Peer Review → Verified        │
└─────────────────────────────────────────────────────┘
                         ↓ uses
┌─────────────────────────────────────────────────────┐
│ Domain (pure Python, no external deps)              │
│   - Entities: Recipe, Component, Source, AuditLog   │
│   - Value Objects: MassPercent, CAS, ISBN, DOI      │
│   - Domain Services: VerificationRule, ClassRanker  │
│   - Domain Events                                    │
└─────────────────────────────────────────────────────┘
                         ↑ implemented by
┌─────────────────────────────────────────────────────┐
│ Infrastructure                                       │
│   - SQLite+SQLCipher repo, FTS5 adapter             │
│   - PDF generator (ReportLab)                       │
│   - 1C CommerceML exporter/importer                 │
│   - Rule-based calculators (PVC, Tg, HSP, RoM)      │
│   - sklearn predictor (advisory)                    │
│   - structlog, i18n, DI container                   │
└─────────────────────────────────────────────────────┘
```

## 5. Технический стек (locked)

| Слой | Технология | Версия |
|---|---|---|
| Язык | Python | 3.11+ |
| GUI | PySide6 (Qt 6) | 6.6+ |
| ORM | SQLAlchemy | 2.0 (async) |
| Миграции | Alembic | 1.13+ |
| Валидация | Pydantic | 2.x |
| DB | SQLite + SQLCipher | 3.45 + 4 |
| PDF | ReportLab + Platypus | 4.x |
| Charts | QtCharts (PySide6.QtCharts) | built-in |
| Excel | openpyxl | 3.1+ |
| Поиск | SQLite FTS5 + trigram tokenizer | built-in |
| ML | scikit-learn | 1.4+ |
| Логирование | structlog | 24.x |
| Безопасность | passlib[argon2], cryptography | latest |
| Локализация | Babel, gettext | latest |
| Тесты | pytest, pytest-qt, pytest-asyncio, hypothesis, coverage | latest |
| Линтеры | ruff, mypy --strict, bandit | latest |
| Сборка | PyInstaller | 6.x |
| Инсталлятор | Inno Setup | 6.x |
| CI/CD | GitHub Actions | — |
| Pre-commit | pre-commit framework | latest |

## 6. Модули MVP

### 6.1. Каталог рецептур
- Фильтрация по: категория, подкатегория, связующее, класс продукта, диапазон VOC/PVC/density, теги
- Полнотекстовый поиск (SQLite FTS5): по названию, описанию, ингредиентам, источникам
- Side-by-side сравнение до 4 рецептур (по составу и характеристикам)
- Сортировка, группировка, экспорт списка в CSV/XLSX

### 6.2. Калькулятор пересчёта
- Масштабирование на любой объём партии (от 100 г до 100 000 кг)
- Пересчёт % ↔ кг ↔ литры с учётом плотности каждого компонента
- Расчёт стоимости партии (по опциональной БД цен сырья)
- Сохранение расчёта как "Derived Batch" с привязкой к рецептуре

### 6.3. Прогнозирование характеристик (rule-based)
- **Rule of mixtures** для density, mass solids, volume solids, VOC
- **PVC/CPVC** расчёт с определением "matte/semi-gloss/gloss" по PVC/CPVC ratio
- **Tg по Fox** для смесей полимеров: 1/Tg_mix = Σ(wᵢ/Tgᵢ)
- **Hansen Solubility Parameters** для оценки совместимости растворителей (R₀ distance)
- **Volume solids ↔ DFT/WFT** калькулятор

### 6.4. ML-advisory модуль
- RandomForestRegressor / GradientBoostingRegressor на верифицированном датасете
- Помечает прогнозы ⚠ "advisory hint, not measured"
- Метрики: MAE, R², top-k feature importance
- Возможность отключения пользователем (настройка)
- Версионирование модели (включена в build)

### 6.5. Классификатор по классам
- Алгоритм многокритериальной оценки:
  - Тип и доля связующего (вес 30%)
  - Качество пигментов (TiO₂ rutile vs anatase, blue tone undertone) (вес 15%)
  - Функциональные добавки (HALS, UV-absorbers, биоциды премиум) (вес 20%)
  - Прогнозируемые эксплуатационные характеристики (scrub, adhesion, scrub resistance) (вес 25%)
  - Relative cost index (опционально, если заполнен пользователем) (вес 10%)
- Выход: рекомендация класса с обоснованием (какие факторы «тянут» вверх/вниз)

### 6.6. Технологические карты
- Генерация PDF с полной прописью процесса:
  - Шапка: наименование, класс, область применения, источник
  - Состав (таблица по стадиям)
  - Технологический режим (оборудование, T, об/мин, время, контрольные точки)
  - Условия применения и хранения
  - Безопасность (GHS, H/P-фразы, СИЗ)
  - Подпись технолога, дата, версия рецептуры
- Шаблон настраивается (логотип компании, формат шапки)

### 6.7. Управление качеством данных
- Workflow: **Draft → Pending Review → Verified** (требуется 3 независимых подтверждения)
- Роли: Viewer / Technologist / Admin / Auditor
- Правила:
  - Запись со статусом Draft не попадает в основную выдачу (видна только Admin/Auditor)
  - Verified запись неизменяема без создания новой версии
  - Каждое изменение фиксируется в audit_log
- Чек-лист верификации (UI):
  - [ ] Первичный источник указан с ISBN и страницей
  - [ ] Кросс-референс во втором источнике
  - [ ] Технолог-ревьюер подтвердил реалистичность состава
  - [ ] Все компоненты имеют CAS-номера
  - [ ] Прогнозные значения помечены ⚠
- Статистика: X verified / Y pending / Z rejected / W draft

### 6.8. Аудит и версионирование
- Каждая запись имеет историю изменений (audit_log)
- Версионирование: при редактировании Verified записи создаётся новая версия со ссылкой на предыдущую
- Diff-просмотр между версиями
- Экспорт полной истории записи в PDF/JSON

### 6.9. Импорт seed-датасета
- CLI-скрипт: `python -m formulation.import_seed --source flicks-water-based-vol3`
- Идемпотентный: можно перезапускать
- Валидация на этапе импорта (Pydantic schema)
- Автоматическое создание CrossReference записей
- Dry-run режим

### 6.10. Экспорт данных
- **PDF**: технологическая карта (ReportLab)
- **XLSX**: каталог рецептур, состав с формулами
- **CSV**: для импорта в другие системы (1С, SAP)
- **JSON**: полный dump (с audit log)
- **CommerceML 2.0 XML**: для 1С (экспорт рецептур + импорт справочника сырья)

### 6.11. UX/UI
- Material Design 3 (Qt Quick Controls 2 + Material стиль)
- Темы: Light / Dark / High Contrast (переключение в реальном времени)
- Адаптивность к DPI (тестирование на 100% / 150% / 200%)
- Горячие клавиши: Ctrl+K (command palette), F1 (help), Ctrl+N (new recipe), Ctrl+F (search), Ctrl+P (print), Ctrl+E (export)
- Command palette (Ctrl+K): fuzzy-поиск по командам и рецептурам
- Встроенная справка F1 с индексом и поиском
- Splash screen с логотипом и disclaimer
- Локализация: все строки в .po-файлах, ru.po (default), en.po

### 6.12. Безопасность
- DB: SQLCipher с AES-256, ключ из passphrase пользователя (Argon2id → key derivation)
- Пароли пользователей: Argon2id (passlib)
- Защита от SQL-инъекций: только параметризованные запросы (SQLAlchemy)
- Ролевая модель (Viewer / Technologist / Admin / Auditor)
- Логирование всех изменений (audit_log) с указанием пользователя
- Disclaimer на старте приложения (юридическая оговорка)
- Disclaimer в PDF-экспорте

## 7. Команда и трудозатраты

| Роль | Трудозатраты | Функция |
|---|---|---|
| Senior full-stack (Python/Qt) | 30–42 недели | Разработка, CI/CD, тесты |
| Senior domain-technologist (ЛКМ) | 20–28 недель | Верификация контента, ревью рецептур |
| DevOps part-time | 4 недели | CI/CD, инфраструктура сборки |
| UX/UI дизайнер part-time | 4 недели | Material Design 3, темы |

## 8. Updated MVP — детальный план по фазам

| Фаза | Содержание | Недели | Deliverables |
|---|---|---|---|
| **0 — Discovery** ✅ | Скоуп, ADR, диаграммы, пример | 1 (готово) | Этот документ |
| **1 — Foundation** | Repo skeleton, CI/CD, linting, DDL+Alembic, domain models, DI, logging, security | 4–6 | ADR-0001..0005, ER-diagram, миграции, скелет, ≥80% покрытие domain |
| **2 — Core CRUD + Seed** | Каталог, поиск (FTS5), CRUD, verification workflow, аудит, ролевая модель, **импорт 500+ рецептур** | 8–10 | 500 verified recipes, все CRUD-операции с тестами, E2E основных сценариев |
| **3 — Intelligence** | Калькулятор партии, PVC/CPVC, Tg, HSP, RoM, классификатор, **sklearn ML-advisory** | 6–8 | Все расчётные модули + ML-модель с метриками |
| **4 — Polish + Integration** | Material Design 3, темы, command palette, **1С CommerceML**, RU/EN, F1-help, PDF/XLSX/CSV | 6–8 | Полный UX, локализация 100%, 1С-импорт/экспорт работает |
| **5 — Release** | PyInstaller → Inno Setup, smoke-тесты, **user manual PDF**, dev docs, lessons learned | 3–4 | Установщик `.exe`, документация, видео-демо |
| **TOTAL** | | **28–37 недель** | |

## 9. Backlog v2.0 (после MVP)

- Cloud sync (опционально, для enterprise-режима)
- Mobile companion (iOS+Android, read-only)
- LIMS-интеграция (SampleManager / LabWare)
- Advanced ML-модели (XGBoost, neural nets на curated dataset)
- Multi-factory collaboration
- Электронная подпись техкарт (КЭП)
- Код-сигнинг и публичное распространение
- PostgreSQL enterprise-режим

## 10. Риски (high-level)

| # | Риск | Вероятность | Импакт | Митигация |
|---|---|---|---|---|
| R1 | Недостаточный объём верифицированных источников для 500 рецептур | M | H | Договориться о доступе к Goldschmidt/Streitberger, Wicks/Jones/Pappas в библиотеке заказчика; альтернатива — технические бюллетени сырьевых производителей |
| R2 | Контент-менеджер (технолог) недоступен на полный цикл | H | H | Привлечь 2 технологов part-time; подготовить детальный playbook для контент-команды |
| R3 | Размер дистрибутива Python+PySide6 (~80–120 МБ) | M | M | Оптимизация (UPX, исключение ненужных Qt-модулей); ожидаемый размер ~70 МБ |
| R4 | Производительность SQLite при ≥500 рецептур + FTS5 | L | M | Бенчмарки в Phase 1; при необходимости — индексы + WAL mode |
| R5 | ML-модель на малых данных переобучается | M | M | Кросс-валидация, регуляризация, отключаемая пользователем, всегда помечается ⚠ |
| R6 | 1С: разные версии (7.7/8.x) и форматы обмена | M | M | Начать с CommerceML 2.0 (8.x); для 7.7 — отдельный модуль в v2 |

## 11. Open Questions (для обсуждения)

Все критические вопросы сняты. Открытые вопросы для подтверждения на Phase 1 kick-off:

- OQ1: Какой именно реестр сырья предполагается в 1С — БД производителей или собственный справочник компании?
- OQ2: Требуется ли поддержка фотографий образцов покрытий (color rendering) в каталоге?
- OQ3: Нужен ли модуль для работы с SDS (Safety Data Sheet) — отдельный workflow?
- OQ4: Нужна ли интеграция с электронным документооборотом (например, Directum, 1С:ДО)?

---

## 12. Phase 0 Review Checklist

Перед переходом к Phase 1 подтвердите:

- [ ] Скоуп понятен и согласован
- [ ] Технический стек утверждён
- [ ] Трудозатраты реалистичны
- [ ] Состав команды определён
- [ ] Пример рецептуры соответствует ожиданиям по качеству данных
- [ ] Все обязательные источники верификации доступны
- [ ] Открытые вопросы (OQ1-OQ4) отложены или решены
- [ ] Approval на Phase 1 (Foundation)
