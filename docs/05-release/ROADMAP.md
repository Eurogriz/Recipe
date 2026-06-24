# ROADMAP.md — Formulation Workbench v2.0+

**Date:** 2026-06-24
**Horizon:** 12-18 months
**Status:** Backlog (post-MVP)

Стратегический план развития после MVP v1.0.0.

---

## 🎯 Видение v2.0

**Превратить Formulation Workbench из standalone desktop-приложения в enterprise-платформу** для управления рецептурами ЛКМ с:
- Multi-factory collaboration
- Cloud sync
- Интеграцией с корпоративными LIMS/ERP
- ML-predictions как first-class feature (после 500+ verified recipes)
- Mobile companion

---

## 📅 Roadmap по кварталам

### Q3-Q4 2026 (ближайшие 3-6 месяцев)

#### Q3 2026: Foundation v2.0

- [ ] **Seed dataset расширение до 500+ рецептур** (приоритет #1)
  - Технолог full-time на верификацию
  - Парсинг техбюллетеней основных производителей (BASF, Dow, Evonik, Wacker)
  - Расширение по категориям: больше покрытие антикоррозии, огнезащиты, спецпокрытий

- [ ] **Calibration wizard**
  - UI для ввода лабораторных данных пользователем
  - Автоматическая калибровка defaults на основе введённых данных
  - Per-category calibration profiles

- [ ] **Domain model v2** (multi-stage + 2K-aware)
  - Stage-aware Recipe (каждый stage имеет свою долю)
  - component_role: A | B | post_mix
  - Backward compatibility с v1.0

- [ ] **User-override mechanism**
  - Settings UI для per-component overrides (density, Tg, oil absorption)
  - Override profiles (можно создавать и применять к разным проектам)

#### Q4 2026: Polish + Performance

- [ ] **Performance optimizations**
  - Database indexing review
  - Query optimization для каталога (1000+ рецептур)
  - Cold start < 3 сек (PyInstaller bundle optimization)

- [ ] **UX improvements** (по обратной связи от UAT)
  - Recent files, bookmarks
  - Multi-window support
  - Drag-and-drop import
  - Photo attachments к рецептурам

- [ ] **Reports module** (расширенный)
  - Сравнительные отчёты (до 8 рецептур side-by-side)
  - Отчёты по подкатегориям (все лаки категории "Алкидные")
  - Печатные формы с логотипом компании (настраиваемые шаблоны)

- [ ] **Calibration ML** (с 200+ verified recipes)
  - Переобучение ML-модели на расширенном dataset
  - Per-property ML models
  - Confidence calibration

### Q1-Q2 2027 (6-12 месяцев)

#### Q1 2027: Cloud + Mobile

- [ ] **Cloud sync** (опционально, opt-in)
  - Multi-device sync через PostgreSQL backend
  - Conflict resolution (last-write-wins + manual merge для конфликтов)
  - Cloud backup (encrypted with user's key)

- [ ] **Mobile companion** (iOS + Android)
  - Read-only каталог + поиск
  - Избранное + offline mode
  - Просмотр PDF техкарт
  - **Не редактирование** (только desktop)

- [ ] **Web interface** (lightweight)
  - Read-only каталог в браузере
  - Без установки приложения
  - Для технологов вне офиса

#### Q2 2027: Enterprise Integration

- [ ] **LIMS adapters**
  - SampleManager (Thermo Fisher)
  - LabWare
  - StarLIMS
  - OpenLab (Agilent)
  - Custom adapter framework

- [ ] **ERP full integration**
  - SAP (RFC/BAPI/OData)
  - Microsoft Dynamics 365
  - Oracle ERP Cloud
  - Already: 1С:Предприятие 8.x (CommerceML 2.0)

- [ ] **Multi-factory collaboration**
  - Role-based access (cross-factory)
  - Recipe sharing with version control
  - Audit log visible across factories
  - Centralized master catalog + factory-specific overrides

### Q3-Q4 2027 (12-18 месяцев)

#### Q3 2027: Advanced ML + AI

- [ ] **Curated ML dataset** (1000+ verified recipes)
  - Online learning (user feedback → model improvement)
  - Explainable AI (SHAP values for predictions)
  - Per-category ML models (interior/exterior/industrial)

- [ ] **Compatibility prediction**
  - Predict compatibility между рецептурой и подложкой
  - Predict stability (shelf-life estimation)
  - Predict cost based on raw material prices

- [ ] **Auto-formulation** (experimental)
  - Given target properties → generate recipe candidates
  - Constraint-based optimization (cost, VOC, performance)
  - Human-in-the-loop validation required

#### Q4 2027: Public Release

- [ ] **Code signing** (EV certificate)
  - Public distribution
  - Windows SmartScreen reputation
  - Auto-update mechanism

- [ ] **Multi-platform** (if needed)
  - macOS (Qt supports)
  - Linux (Ubuntu LTS, RHEL)

- [ ] **Telemetry + Analytics**
  - Opt-in anonymous usage statistics
  - Crash reporting
  - Usage patterns → roadmap inputs

---

## 🌟 Long-term Vision (2028+)

### Industry Standard

- **Partnership с производителями сырья** — официальные каналы для получения verified TDS
- **Standards bodies integration** — ASTM, ISO, ГОСТ автоматический импорт обновлений
- **Open data initiative** — публичный каталог non-proprietary recipes для образовательных целей

### Platform Expansion

- **API-first architecture** — все функции доступны через REST/GraphQL API
- **Headless mode** — для интеграции в CI/CD pipelines (автоматическое тестирование рецептур)
- **Microservices** — калькуляторы, ML predictor, FTS search как отдельные сервисы
- **Kubernetes-native** — для enterprise развёртывания

### Scientific Research

- **Partnership с университетами** — данные для научных публикаций
- **Open access papers** — калибровочные исследования
- **Materials science integration** — predictive models для новых материалов

---

## 📊 Success Metrics (KPIs)

### v2.0 Year 1 Targets

| Metric | Current (v1.0) | Target (v2.0) |
|---|---|---|
| Verified recipes | 34 | 500+ |
| Active installations | 0 (just released) | 50+ |
| ML accuracy (R²) | N/A | >0.85 для top-3 properties |
| Calibration accuracy (density) | 97% | 98% |
| Calibration accuracy (mass solids) | 85% | 92% |
| Calibration accuracy (VOC) | 70% | 88% |
| Uptime (для cloud mode) | N/A | 99.5% |
| User satisfaction (NPS) | TBD | >40 |

### Long-term (3-year horizon)

- **Standard de facto** для формуляции в РФ/CIS
- **1,000+ verified recipes**
- **95%+ калькуляторов откалиброваны** на лабораторных данных
- **Multi-platform** (Windows + macOS + Web)

---

## 🤝 Partnership Opportunities

### Tier 1 (Strategic)

- **Производители ЛКМ** — для official product support
- **Университеты** — для научной валидации калькуляторов
- **ГОСТ/ISO комитеты** — для интеграции стандартов

### Tier 2 (Integration)

- **1С** — углублённая интеграция (включая 7.7)
- **SAP** — enterprise ERP connector
- **LIMS vendors** — SampleManager, LabWare, StarLIMS

### Tier 3 (Distribution)

- **IT-интеграторы** в РФ/CIS для enterprise rollout
- **Обучение** — курсы для технологов по использованию приложения

---

## 💼 Business Model Considerations

### Current (Free / Open-Core)

- Бесплатно для внутреннего использования
- Premium support / training за отдельную плату

### v2.0 Options

1. **Per-seat subscription** — для крупных компаний
2. **Site license** — для средних компаний
3. **Cloud subscription** — для distributed teams
4. **OEM partnership** — для интеграции в существующие системы

### Open Source Strategy

- **Core** (domain models, calculators) — open source под MIT license
- **Extensions** (premium ML models, advanced integrations) — коммерческие
- **Community contributions** — pull requests приветствуются

---

## 📆 Quarterly Review Process

Каждый квартал:
1. **Retrospective** — что сделано, что нет, почему
2. **Customer feedback analysis** — из support, surveys, UAT
3. **Competitive analysis** — что делают конкуренты (LIMS vendors, ERP plugins)
4. **Prioritization adjustment** — на основе метрик

---

## 📞 Contributing to Roadmap

Если у вас есть предложения:
- GitHub Issues с тегом `roadmap` или `v2.0-feature`
- Email: team@formulation-workbench.local
- User research interviews (для Tier 1 customers)

---

## 📜 License

Этот roadmap публикуется под CC-BY-4.0. Свободно используйте для планирования собственных проектов.

---

**Дата последнего обновления:** 2026-06-24
**Следующее обновление:** Q3 2026 (после Q2 review)
