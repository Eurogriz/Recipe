# ADR-0001: Технический стек Formulation Workbench MVP

**Status:** Accepted
**Date:** 2026-06-24
**Deciders:** Архитектор, Product Owner, Технолог-эксперт

---

## Context and Problem Statement

Нужно выбрать стек для enterprise-grade desktop-приложения для работы с рецептурами ЛКМ и строительной химии. Требования:

- Single-user desktop на Windows 10/11
- Локальная embedded БД с шифрованием (SQLite + SQLCipher)
- Полнотекстовый поиск по каталогу 500+ рецептур
- Расчётные модули (PVC/CPVC, Tg/Fox, HSP, rule-of-mixtures)
- ML-advisory (sklearn)
- Генерация PDF (технологические карты)
- i18n (RU + EN)
- Material Design 3 / Fluent Design UI
- Интеграция с 1С (CommerceML 2.0 XML)
- Долгосрочная поддержка (5+ лет), production-grade

## Considered Options

### Option A: Python 3.11+ / PySide6 / SQLAlchemy 2.0 / ReportLab

**Плюсы:**
- Богатая экосистема для scientific computing: NumPy, SciPy, scikit-learn, pandas — критично для расчётных модулей и ML
- Pydantic v2 — мощная валидация данных
- SQLAlchemy 2.0 — type-safe ORM с async
- PySide6 — официальный Qt-binding для Python, LGPL, коммерчески пригодный
- Быстрая разработка (high-level API)
- Зрелое сообщество scientific Python

**Минусы:**
- Размер дистрибутива ~80–120 МБ (PyInstaller + Qt)
- Чуть медленнее cold start (~3–5 сек)
- GIL (но не критично для desktop single-user)

### Option B: C# .NET 8 / WPF / EF Core / QuestPDF

**Плюсы:**
- Native Windows look-and-feel, nullable reference types
- Малый размер дистрибутива (~30–50 МБ)
- Быстрый cold start (<1 сек)
- Отличная интеграция с Windows (XAML, MVVM-инфраструктура)
- AOT-компиляция возможна в будущем

**Минусы:**
- ML-библиотеки менее развиты (ML.NET — есть, но scikit-learn-альтернатив нет)
- Scientific computing слабее (нет NumPy/SciPy-эквивалента)
- Меньше опенсорс-калькуляторов химических параметров
- Дольше разработка (boilerplate-кода больше)

### Option C: C# .NET 8 / Avalonia UI / EF Core

**Плюсы:**
- Современный MVU-стиль, Fluent Design
- Кросс-платформа в будущем
- XAML-подобный язык

**Минусы:**
- Менее зрелая экосистема по сравнению с WPF
- Сообщество меньше, чем у Qt/WPF

## Decision

**Выбран Option A: Python 3.11+ / PySide6 / SQLAlchemy 2.0 / ReportLab**

### Обоснование

1. **Критичность scientific computing**: расчёт PVC/CPVC, Tg/Fox, HSP, rule-of-mixtures — это всё numerical methods, для которых NumPy/SciPy идеальны. C# .NET потребует переписывать эти библиотеки или тянуть большие зависимости.

2. **ML-advisory (sklearn)**: scikit-learn — де-факто стандарт для табличного ML. В .NET есть ML.NET, но порог входа выше и сообщество меньше.

3. **Pydantic v2**: валидация сложной схемы рецептур (50+ полей) критична. Pydantic решает это элегантно.

4. **Скорость разработки**: Python итеративнее; для MVP это важнее, чем минимальный размер дистрибутива.

5. **Qt 6 / PySide6**: даёт нативный вид на Windows (Qt — зрелая технология, 30+ лет), Material Design 3 через QtQuick Controls 2.

6. **Размер дистрибутива**: митигируется UPX-сжатием и исключением ненужных Qt-модулей; ожидаемый финальный размер ~70 МБ.

7. **Лицензия**: PySide6 — LGPL, коммерчески пригодный для proprietary-приложения.

### Последствия

**Положительные:**
- Быстрая разработка MVP
- Доступ к широкому стеку scientific libraries
- Лёгкое добавление новых расчётных модулей

**Отрицательные (принятые):**
- Дистрибутив ~70–100 МБ
- Cold start ~3–5 сек (митигируется splash screen)
- Необходимость тщательной оптимизации импортов для cold start

## Architecture Components

```
presentation/      ← PySide6 (Qt 6), QtQuick Controls 2 (Material Design 3)
application/       ← Use cases, CQRS, DTOs
domain/            ← Pure Python entities, value objects, services
infrastructure/    ← SQLAlchemy repos, ReportLab, sklearn, 1C adapters
```

## Compliance

- [x] Windows 10/11 only
- [x] Single-user desktop
- [x] Scientific computing support (NumPy/SciPy/sklearn)
- [x] ML advisory support (sklearn)
- [x] i18n (Babel/gettext)
- [x] Material Design 3 UI
- [x] Encrypted local DB (SQLCipher)
- [x] Long-term support (5+ years): Python 3.11+ LTS, Qt 6 LTS

## References

- Qt for Python (PySide6): https://doc.qt.io/qtforpython-6/
- SQLAlchemy 2.0: https://docs.sqlalchemy.org/en/20/
- Pydantic v2: https://docs.pydantic.dev/latest/
- scikit-learn: https://scikit-learn.org/
- ReportLab: https://www.reportlab.com/docs/reportlab-userguide.pdf
- Material Design 3 + Qt: https://doc.qt.io/qt-6/qtquickcontrols2-material.html
