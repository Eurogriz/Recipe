# C4 Diagrams — Formulation Workbench

**Notation:** C4 model (Context, Container, Component, Code)
**Tool:** Mermaid (text-based, renders in most markdown viewers)

---

## Level 1: System Context

Показывает, как Formulation Workbench взаимодействует с пользователями и внешними системами.

```mermaid
graph TB
    subgraph "R&D / Production Environment"
        Tech["Технолог R&D<br/>(creates/edits recipes)"]
        Admin["Admin<br/>(manages users, settings)"]
        Auditor["Auditor<br/>(reviews verification trail)"]
        Viewer["Viewer<br/>(searches, reads)"]
    end

    subgraph "External Systems"
        OneC["1С: Предприятие 8.x<br/>(ERP/Accounting)"]
        ChemSupplier["Сырьевые поставщики<br/>(BASF, Dow, Evonik,<br/>Wacker, etc.)"]
        VerificationSources["Верифицированные источники<br/>(Flick, Wicks/Jones/Pappas,<br/>Goldschmidt/Streitberger,<br/>Petrie, Ebnesajjad)"]
    end

    subgraph "Formulation Workbench"
        System["Formulation Workbench<br/>Desktop Application<br/>(Python 3.11+ / PySide6)"]
    end

    Tech -->|"Создаёт/редактирует<br/>рецептуры"| System
    Admin -->|"Управляет пользователями"| System
    Auditor -->|"Проверяет audit log"| System
    Viewer -->|"Ищет/просматривает"| System

    System -->|"Экспорт рецептур<br/>(CommerceML 2.0 XML)"| OneC
    System -->|"Импорт справочника сырья"| OneC

    System -->|"Ссылается на"| VerificationSources
    System -->|"Валидирует сырьё по<br/>техбюллетеням"| ChemSupplier
```

---

## Level 2: Containers

Декомпозиция Formulation Workbench на контейнеры (отдельные процессы/приложения).

```mermaid
graph TB
    subgraph "Workstation (Windows 10/11)"
        DesktopApp["Desktop Application<br/>[Python 3.11+ / PySide6 / Qt 6.6]<br/>Single user, native desktop<br/>~70-100 MB installer"]

        LocalDB["Local SQLite DB<br/>[SQLite 3.45 + SQLCipher]<br/>Encrypted (AES-256)<br/>FTS5 for search"]

        ConfigFiles["Configuration<br/>[JSON/YAML files<br/>in %APPDATA%]"]

        CacheDir["Cache Directory<br/>[Generated PDFs,<br/>thumbnails, logs]"]

        DesktopApp -->|"Reads/Writes"| LocalDB
        DesktopApp -->|"Reads"| ConfigFiles
        DesktopApp -->|"Writes"| CacheDir
    end

    OneC["1С: Предприятие 8.x<br/>(External)"]
    VerificationSources["Верифицированные<br/>источники<br/>(PDF books,<br/>ISO standards)"]

    DesktopApp -->|"CommerceML<br/>2.0 XML<br/>(export/import)"| OneC
    DesktopApp -.->|"Manually referenced<br/>(ISBN, page)"| VerificationSources
```

---

## Level 3: Components

Декомпозиция Desktop Application на основные компоненты.

```mermaid
graph TB
    subgraph "Presentation Layer (PySide6)"
        MainWindow["MainWindow<br/>(Qt Main Window)"]
        RecipeEditor["RecipeEditor View<br/>(multi-tab form)"]
        CatalogView["CatalogView<br/>(filterable list)"]
        ComparisonView["ComparisonView<br/>(side-by-side, up to 4)"]
        CalculatorView["CalculatorView<br/>(batch scaling)"]
        PredictorView["PredictorView<br/>(properties prediction)"]
        VerificationPanel["VerificationPanel<br/>(workflow UI)"]
        CommandPalette["Command Palette<br/>(Ctrl+K fuzzy search)"]
        ThemeManager["ThemeManager<br/>(Light/Dark/HC)"]
    end

    subgraph "Application Layer (Use Cases + CQRS)"
        RecipeCommands["Recipe Commands<br/>(Create, Update,<br/>Delete, SubmitForReview,<br/>Verify)"]
        RecipeQueries["Recipe Queries<br/>(GetById, Search,<br/>Filter, Compare)"]
        VerificationService["Verification Service<br/>(triple-verification<br/>workflow)"]
        CalculatorService["Calculator Service<br/>(batch, PVC/CPVC,<br/>Tg, HSP, RoM)"]
        PredictorService["Predictor Service<br/>(rule-based +<br/>sklearn ML advisory)"]
        AuditService["Audit Service<br/>(log every change)"]
        ExportService["Export Service<br/>(PDF, XLSX, CSV,<br/>JSON, CommerceML)"]
    end

    subgraph "Domain Layer (Pure Python)"
        Recipe["Recipe Entity"]
        Component["Component Value Object"]
        Source["Source Reference<br/>Value Object"]
        Verification["Verification Status<br/>Value Object"]
        CasNumber["CAS Number<br/>Value Object"]
        MassPercent["Mass Percent<br/>Value Object"]
        DomainEvents["Domain Events"]
        DomainServices["Domain Services<br/>(ClassRanker,<br/>ValidationRules)"]
    end

    subgraph "Infrastructure Layer"
        RecipeRepo["Recipe Repository<br/>(SQLAlchemy +<br/>SQLCipher)"]
        FTSSearch["FTS5 Search Adapter"]
        PDFGen["PDF Generator<br/>(ReportLab)"]
        OneCAdapter["1С CommerceML<br/>Adapter"]
        MLPredictor["sklearn ML Predictor<br/>(advisory only)"]
        RuleEngine["Rule Engine<br/>(PVC/CPVC, Tg/Fox,<br/>HSP, RoM)"]
        Logger["Structured Logger<br/>(structlog)"]
        i18n["i18n (Babel/gettext)"]
    end

    MainWindow --> RecipeEditor
    MainWindow --> CatalogView
    MainWindow --> ComparisonView
    MainWindow --> CalculatorView
    MainWindow --> PredictorView
    MainWindow --> VerificationPanel
    MainWindow --> CommandPalette
    MainWindow --> ThemeManager

    RecipeEditor --> RecipeCommands
    CatalogView --> RecipeQueries
    ComparisonView --> RecipeQueries
    CalculatorView --> CalculatorService
    PredictorView --> PredictorService
    VerificationPanel --> VerificationService
    VerificationPanel --> AuditService

    RecipeCommands --> Recipe
    RecipeCommands --> Source
    RecipeCommands --> Verification
    RecipeCommands --> DomainEvents
    RecipeCommands --> RecipeRepo
    RecipeCommands --> AuditService
    RecipeCommands --> VerificationService

    RecipeQueries --> RecipeRepo
    RecipeQueries --> FTSSearch

    CalculatorService --> DomainServices
    CalculatorService --> RuleEngine
    PredictorService --> RuleEngine
    PredictorService --> MLPredictor

    ExportService --> PDFGen
    ExportService --> OneCAdapter
    ExportService --> RecipeRepo

    RecipeRepo --> Logger
    FTSSearch --> Logger
    PDFGen --> i18n
```

---

## Level 4: Code (пример для Recipe Entity)

```python
# domain/entities/recipe.py

class Recipe:
    """Aggregate root для рецептуры."""

    def __init__(
        self,
        id: RecipeId,
        metadata: RecipeMetadata,
        composition: CompositionStages,
        source_reference: SourceReference,
        status: VerificationStatus,
        audit_log: AuditLog,
    ):
        self._id = id
        self._metadata = metadata
        self._composition = composition
        self._source_reference = source_reference
        self._status = status
        self._audit_log = audit_log

        self._validate_invariants()

    def _validate_invariants(self) -> None:
        """Domain invariants — pure validation, no I/O."""
        self._composition.validate_mass_percent_sums_to_100()
        if self._status == VerificationStatus.VERIFIED:
            self._source_reference.assert_has_three_independent_verifications()
            self._composition.assert_all_components_have_cas_numbers()

    def submit_for_review(self, reviewer: UserId) -> ReviewSubmission:
        """Domain operation."""
        if self._status not in {VerificationStatus.DRAFT, VerificationStatus.REJECTED}:
            raise InvalidStateTransition(...)
        return ReviewSubmission(...)

    def verify(self, verifier: UserId, source_citation: Citation) -> None:
        self._status.increment_verification_count()
        if self._status.verification_count >= 3:
            self._status = VerificationStatus.VERIFIED
            self._audit_log.record_verification(...)
```

---

## Deployment View

```mermaid
graph TB
    subgraph "Workstation (Windows 10/11, single-user)"
        UserAppDir["C:\\Program Files\\<br/>FormulationWorkbench\\"]
        UserDataDir["%APPDATA%\\<br/>FormulationWorkbench\\"]
        UserLocalApp["%LOCALAPPDATA%\\<br/>FormulationWorkbench\\cache\\"]

        Installer["FormulationWorkbench-1.0.0-setup.exe<br/>(Inno Setup)"]

        subgraph "AppDir contents"
            MainEXE["FormulationWorkbench.exe"]
            Python["python311.dll"]
            PySide6["PySide6\\"]
            AppModules["app\\"]
            Resources["resources\\<br/>icons, themes,<br/>locales, models"]
        end

        subgraph "UserData contents"
            DB["formulation.db<br/>(SQLite + SQLCipher)"]
            Config["config.json"]
            Logs["logs\\<br/>(rotated)"]
            Seed["seed_data.json<br/>(imported recipes)"]
        end

        subgraph "UserLocalApp contents"
            Cache["pdf_cache\\"]
            Thumbnails["thumbnails\\"]
        end
    end

    Installer -->|Extracts to| UserAppDir
    UserAppDir --> MainEXE
    UserAppDir --> Python
    UserAppDir --> PySide6
    UserAppDir --> AppModules
    UserAppDir --> Resources

    MainEXE -->|Creates/Reads| UserDataDir
    MainEXE -->|Creates/Reads| UserLocalApp

    UserDataDir --> DB
    UserDataDir --> Config
    UserDataDir --> Logs
    UserDataDir --> Seed

    UserLocalApp --> Cache
    UserLocalApp --> Thumbnails
```
