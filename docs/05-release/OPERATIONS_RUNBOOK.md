# Operations Runbook — Formulation Workbench v1.0.0

**Document version:** 1.0
**Last updated:** 2026-06-24

Production operations guide для IT-администраторов и DevOps.

---

## 📑 Содержание

1. [Архитектура развёртывания](#архитектура-развёртывания)
2. [Установка](#установка)
3. [Backup и восстановление](#backup-и-восстановление)
4. [Мониторинг](#мониторинг)
5. [Incident response](#incident-response)
6. [Performance tuning](#performance-tuning)
7. [Обновления](#обновления)
8. [Troubleshooting](#troubleshooting)

---

## 🏗️ Архитектура развёртывания

```
Windows 10/11 Workstation
├── C:\Program Files\FormulationWorkbench\
│   ├── FormulationWorkbench.exe    (PyInstaller bundle, ~70-100 MB)
│   ├── *.dll, *.pyd                (Qt6, Python, dependencies)
│   └── resources\                   (icons, themes, locales)
│
└── %APPDATA%\FormulationWorkbench\   (user-specific data)
    ├── formulation.db               (SQLCipher-encrypted SQLite, ~5 MB with 500 recipes)
    ├── config.yaml                  (user settings, overrides)
    ├── logs\                        (rotated, max 50 MB total)
    │   ├── fw-app.log
    │   ├── fw-app.log.1
    │   └── fw-error.log
    └── cache\                       (PDF cache, thumbnails)
```

---

## 🚀 Установка

### Минимальные требования

| Параметр | Минимум | Рекомендуется |
|---|---|---|
| **OS** | Windows 10 (build 19041+) | Windows 11 |
| **CPU** | x64, 2 cores | x64, 4+ cores |
| **RAM** | 4 GB | 8 GB |
| **Disk** | 500 MB | 1 GB SSD |
| **Display** | 1920×1080 | 2560×1440 |
| **DPI** | 100% | 150-200% |

### Шаги установки

#### 1. Установка через инсталлятор (рекомендуется)

```powershell
# Скачать FormulationWorkbench-1.0.0-setup.exe
# Запустить с правами администратора
FormulationWorkbench-1.0.0-setup.exe

# Или тихая установка (для IT-развёртывания):
FormulationWorkbench-1.0.0-setup.exe /SILENT /NORESTART

# Проверить установку:
Test-Path "C:\Program Files\FormulationWorkbench\FormulationWorkbench.exe"
# Должно вернуть True
```

#### 2. Установка через GPO/SCCM/Intune

```powershell
# PowerShell скрипт для IT-деплоймента
$msiPath = "\\server\share\FormulationWorkbench-1.0.0-setup.exe"
$installArgs = "/SILENT /NORESTART /SUPPRESSMSGBOXES"
Start-Process -FilePath $msiPath -ArgumentList $installArgs -Wait
```

#### 3. Первоначальная настройка

```powershell
# Запустить приложение для создания БД и конфига
# БД создаётся при первом запуске с запросом мастер-пароля
& "C:\Program Files\FormulationWorkbench\FormulationWorkbench.exe"
```

⚠️ **ВАЖНО**: Мастер-пароль НЕВОЗМОЖНО восстановить. Сохраните его в корпоративном
password manager (KeePass, Bitwarden, etc.).

---

## 💾 Backup и восстановление

### Что backup-ить

| Что | Где | Критичность |
|---|---|---|
| `formulation.db` | `%APPDATA%\FormulationWorkbench\` | ⚠️ CRITICAL |
| `config.yaml` (overrides) | `%APPDATA%\FormulationWorkbench\` | ⚠️ CRITICAL |
| `seed-data-normalized/` | Внутри установки (можно экспортировать) | LOW (восстановимо) |
| Логи | `%LOCALAPPDATA%\FormulationWorkbench\logs\` | LOW |

### Рекомендуемая стратегия backup

#### Ежедневный автоматический backup (PowerShell)

```powershell
# scripts/backup-fw.ps1
$source = "$env:APPDATA\FormulationWorkbench\formulation.db"
$backupDir = "\\backup-server\FormulationWorkbench\$env:COMPUTERNAME"
$date = Get-Date -Format "yyyy-MM-dd_HH-mm"

# Создать резервную копию
New-Item -ItemType Directory -Path $backupDir -Force
Copy-Item $source "$backupDir\formulation_$date.db"

# Удалить копии старше 30 дней
Get-ChildItem $backupDir -Filter "formulation_*.db" |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } |
    Remove-Item
```

#### Запуск через Task Scheduler

```powershell
# Создать задачу в Task Scheduler
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-File C:\Scripts\backup-fw.ps1"
$trigger = New-ScheduledTaskTrigger -Daily -At "23:00"
Register-ScheduledTask -TaskName "FormulationWorkbench-Backup" -Action $action -Trigger $trigger
```

### Восстановление из backup

```powershell
# Остановить приложение (если запущено)
Stop-Process -Name "FormulationWorkbench" -ErrorAction SilentlyContinue

# Восстановить БД
Copy-Item "\\backup-server\FormulationWorkbench\PC-001\formulation_2026-06-24_22-00.db" `
          "$env:APPDATA\FormulationWorkbench\formulation.db" -Force

# Запустить приложение (пользователь должен ввести мастер-пароль)
& "C:\Program Files\FormulationWorkbench\FormulationWorkbench.exe"
```

---

## 📊 Мониторинг

### Ключевые метрики (мониторить через Zabbix/Prometheus + Windows exporter)

| Метрика | Норма | Warning | Critical |
|---|---|---|---|
| **Process CPU** | < 5% idle, < 30% search | > 50% | > 80% sustained |
| **Process RAM** | < 200 MB idle, < 500 MB search | > 800 MB | > 1.5 GB |
| **Database size** | < 50 MB (500 recipes) | > 200 MB | > 1 GB |
| **Logs size** | < 50 MB total | > 100 MB | > 500 MB |
| **Cold start time** | < 5 sec | > 10 sec | > 30 sec |
| **Search latency (FTS5)** | < 50 ms | > 200 ms | > 1 sec |

### Windows Performance Counter

```powershell
# CPU usage (FormulationWorkbench process)
Get-Counter "\Process(FormulationWorkbench)\% Processor Time" -SampleInterval 5 -MaxSamples 12

# Memory usage (Working Set)
Get-Counter "\Process(FormulationWorkbench)\Working Set" -SampleInterval 5 -MaxSamples 12

# Disk I/O
Get-Counter "\Process(FormulationWorkbench)\IO Data Bytes/sec" -SampleInterval 5 -MaxSamples 12
```

### Логи для мониторинга

**Где:** `%LOCALAPPDATA%\FormulationWorkbench\logs\fw-app.log`

**Что мониторить:**
- `ERROR` строки (должны быть пустыми)
- `CRITICAL` строки (требуют немедленного реагирования)
- Частота `WARNING` (если > 10/min — проблема)
- Длина файла (если > 50 MB — нужна ротация)

```powershell
# Real-time monitoring (PowerShell)
Get-Content "$env:LOCALAPPDATA\FormulationWorkbench\logs\fw-app.log" -Wait |
    Where-Object { $_ -match "ERROR|CRITICAL" } |
    ForEach-Object { Send-AlertToMonitoringSystem $_ }
```

---

## 🚨 Incident Response

### Incident Classification

| Severity | Definition | Response Time | Examples |
|---|---|---|---|
| **P1** | Приложение не запускается, БД не читается | 1 час | DLL missing, DB corrupt |
| **P2** | Функция не работает, потеря данных | 4 часа | Recipe save fails |
| **P3** | Косметический дефект, медленная работа | 1 день | UI не реагирует |

### P1: Приложение не запускается

**Диагностика:**
```powershell
# 1. Проверить event log
Get-EventLog -LogName Application -Source "FormulationWorkbench" -Newest 20

# 2. Проверить crash dumps (если включены)
Get-ChildItem "$env:APPDATA\FormulationWorkbench\crashdumps\" -ErrorAction SilentlyContinue

# 3. Запустить в debug mode
& "C:\Program Files\FormulationWorkbench\FormulationWorkbench.exe" --debug --log-level=DEBUG
```

**Типичные причины:**
1. **DLL missing** — переустановить Visual C++ Redistributable
2. **DB corrupted** — restore from backup
3. **Master password lost** — создать новую БД + import seed data
4. **Disk full** — очистить логи и кэш

### P2: Потеря данных

**Действия:**
1. Остановить приложение (`Stop-Process`)
2. Проверить integrity БД: `python -c "import sqlite3; sqlite3.connect('formulation.db').integrity_check()"`
3. Restore from последнего backup
4. Если backup нет — отправить БД в support для forensic recovery

### P3: Медленная работа

**Диагностика:**
```powershell
# 1. Проверить размер БД и логов
Get-ChildItem "$env:APPDATA\FormulationWorkbench\" -Recurse |
    Sort-Object Length -Descending | Select-Object -First 10

# 2. Проверить антивирус (может сканировать .exe при каждом запуске)
Get-MpPreference | Select-Object ExclusionPath

# 3. Включить debug logging для bottleneck identification
# (через Settings UI: Advanced → Logging → DEBUG)
```

---

## ⚡ Performance Tuning

### Windows-level

```powershell
# 1. Отключить антивирусное сканирование для папки приложения
Add-MpPreference -ExclusionPath "C:\Program Files\FormulationWorkbench"
Add-MpPreference -ExclusionPath "$env:APPDATA\FormulationWorkbench"

# 2. Отключить Windows Search indexing для БД
# (через свойства файла)

# 3. Включить High Performance power plan
powercfg /setactive 8e5e7fa6-a0ab-4f65-9f3a-67a3b3f3f8c4
```

### Application-level

В Settings UI (Settings → Performance):

- **Cache size:** Увеличить до 500 MB для больших dataset
- **Search optimization:** Включить FTS5 кэш
- **Background recalculation:** Отключить для слабых машин
- **GPU acceleration:** Включить если доступна discrete GPU

### Database-level

```sql
-- Оптимизация SQLite для production workload
PRAGMA journal_mode = WAL;        -- Concurrent reads
PRAGMA synchronous = NORMAL;      -- Faster, safe enough
PRAGMA cache_size = -64000;        -- 64 MB cache
PRAGMA temp_store = MEMORY;
PRAGMA mmap_size = 268435456;     -- 256 MB memory-mapped I/O
```

---

## 🔄 Обновления

### Процедура обновления (minor version, например 1.0 → 1.1)

```powershell
# 1. Backup current installation
Copy-Item "C:\Program Files\FormulationWorkbench\" "\\backup\fw-pre-update\" -Recurse
Copy-Item "$env:APPDATA\FormulationWorkbench\formulation.db" "\\backup\fw-pre-update\"

# 2. Run new installer (handles upgrade in-place)
FormulationWorkbench-1.1.0-setup.exe /SILENT

# 3. Launch — schema migration runs automatically
& "C:\Program Files\FormulationWorkbench\FormulationWorkbench.exe"

# 4. Verify
# Check Settings → About → Version = 1.1.0
# Check that recipes count matches
```

### Миграция БД (major version, 1.x → 2.x)

```powershell
# 1. Stop application
Stop-Process -Name "FormulationWorkbench" -Force

# 2. Backup
Copy-Item "$env:APPDATA\FormulationWorkbench\formulation.db" `
          "\\backup\fw-v1-pre-migration.db"

# 3. Run migration tool (если предусмотрен)
& "C:\Program Files\FormulationWorkbench\migrate.exe" --from v1 --to v2

# 4. Verify migration
& "C:\Program Files\FormulationWorkbench\migrate.exe" --verify
```

---

## 🆘 Troubleshooting

### Частые проблемы

#### "Failed to load database" при запуске

**Причина:** БД повреждена или мастер-пароль неверный.

**Решение:**
1. Проверить, что вводите правильный мастер-пароль
2. Если забыли — нет recovery, нужна новая БД (с потерей данных, если нет backup)
3. Если БД повреждена: `python -c "import sqlite3; sqlite3.connect('formulation.db').integrity_check()"`

#### Приложение запускается, но тормозит

**Причина:** Большая БД (> 5000 recipes) или слабое железо.

**Решение:**
1. Settings → Performance → увеличить cache
2. Settings → Search → отключить live preview
3. Архивировать старые рецепты (Export → Archive)
4. Vacuum БД: `python -c "import sqlite3; sqlite3.connect('formulation.db').execute('VACUUM')"`

#### "Cannot import seed data"

**Причина:** JSON файл повреждён или содержит невалидные данные.

**Решение:**
1. Валидировать JSON: `python -m json.tool seed.json`
2. Проверить, что масса компонентов = 100% ± 0.5%
3. Использовать нормализатор: `python -m src.infrastructure.scripts.normalize_seed`

#### Темная тема не применяется

**Причина:** Qt theme не подхватывает системную тему Windows.

**Решение:**
1. Settings → Theme → выбрать вручную
2. Перезапустить приложение
3. Если не помогло — Settings → Reset → Theme

---

## 📞 Эскалация

| Проблема | Первый уровень | Второй уровень |
|---|---|---|
| P1 (приложение не запускается) | IT-департамент | Vendor Support |
| P2 (функциональная ошибка) | Senior Technologist | Vendor Support |
| P3 (медленная работа, UI) | IT-департамент | — |
| Запрос на новую функциональность | Product Owner | — |
| Вопрос по химии рецептур | Senior Technologist | — |

**Vendor support:** support@formulation-workbench.local (TBD)

---

## 📋 Регулярные процедуры

### Еженедельно

- [ ] Проверить размер логов (< 100 MB)
- [ ] Проверить backup успешно создан
- [ ] Проверить свободное место на диске (> 1 GB)

### Ежемесячно

- [ ] Vacuum БД (`VACUUM`)
- [ ] Обновить антивирусные исключения (если менялись пути)
- [ ] Проверить обновления Qt / Python (security advisories)
- [ ] Review audit log на предмет необычных действий

### Ежеквартально

- [ ] Test disaster recovery procedure
- [ ] Review performance metrics
- [ ] Audit user permissions (RBAC)
- [ ] Plan capacity upgrades (if dataset > 1000 recipes)

### Ежегодно

- [ ] Rotate master passwords (если политика требует)
- [ ] Archive old recipes (> 2 years unused)
- [ ] Backup retention cleanup (keep only 1 year)
- [ ] Update documentation (changes from operations)

---

## 🔗 Связанные документы

- [ARCHITECTURE.md](../../ARCHITECTURE.md) — Архитектура системы
- [RELEASE.md](RELEASE.md) — Процесс сборки и выпуска
- [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) — Чек-лист релиза
- [LESSONS_LEARNED.md](LESSONS_LEARNED.md) — Ретроспектива
- [ROADMAP.md](ROADMAP.md) — План развития v2.0
- [USER_MANUAL.md](../../USER_MANUAL.md) — Руководство пользователя

---

**Документ обновляется по мере изменения production-среды.**
