"""Dependency Injection container.

Small, explicit, framework-free container. It's used both by the CLI
(``formulation-workbench``) and by the FastAPI application. Constructing
individual services here keeps the presentation layer free from wiring
concerns.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ...application.use_cases.apply_lab_results import ApplyLabResultsUseCase
from ...application.use_cases.assess_recipe import AssessRecipeUseCase
from ...application.use_cases.calculate_cost import CalculateRecipeCostUseCase
from ...application.use_cases.create_recipe import CreateRecipeUseCase
from ...application.use_cases.delete_recipe import DeleteRecipeUseCase
from ...application.use_cases.get_recipe import GetAllRecipeVersionsUseCase, GetRecipeByIdUseCase
from ...application.use_cases.ml_predict import PredictPropertiesUseCase
from ...application.use_cases.ml_train import TrainPropertyModelsUseCase
from ...application.use_cases.optimise_recipe import OptimiseRecipeUseCase
from ...application.use_cases.search_recipes import (
    GetCatalogStatisticsUseCase,
    SearchRecipesUseCase,
)
from ...application.use_cases.update_recipe import UpdateRecipeUseCase
from ...application.use_cases.verification_workflow import (
    CreateNewVersionUseCase,
    RejectRecipeUseCase,
    SubmitRecipeForReviewUseCase,
    VerifyRecipeUseCase,
)
from ..config import AppSettings, get_settings
from ..db.connection import Database
from ..db.repositories.session_scoped import ScopedAuditLogger, ScopedRecipeRepository
from ..db.repositories.sqlalchemy_experiment_repository import ScopedExperimentRepository
from ..ml.jobs import JobRegistry
from ..ml.property_regressor import PropertyRegressor
from ..notifications import AlertNotifier, build_notifier
from ..regulatory import RegulatoryDataError, build_checker_from_data_dir

if TYPE_CHECKING:
    from ...application.ports.audit_logger import AuditLogger
    from ...application.ports.experiment_repository import ExperimentRepository
    from ...application.ports.recipe_repository import RecipeRepository

logger = logging.getLogger(__name__)


@dataclass
class Container:
    """Lifetime-managed container of application services.

    Create via :meth:`build` and always dispose with :meth:`close` (an
    ``async with`` helper is also provided).
    """

    settings: AppSettings
    database: Database
    recipe_repository: RecipeRepository
    audit_logger: AuditLogger

    # --- Use cases -----------------------------------------------------------
    create_recipe: CreateRecipeUseCase
    update_recipe: UpdateRecipeUseCase
    delete_recipe: DeleteRecipeUseCase
    get_recipe: GetRecipeByIdUseCase
    get_recipe_versions: GetAllRecipeVersionsUseCase
    search_recipes: SearchRecipesUseCase
    catalog_stats: GetCatalogStatisticsUseCase
    submit_for_review: SubmitRecipeForReviewUseCase
    verify_recipe: VerifyRecipeUseCase
    reject_recipe: RejectRecipeUseCase
    create_new_version: CreateNewVersionUseCase
    assess_recipe: AssessRecipeUseCase
    calculate_cost: CalculateRecipeCostUseCase
    apply_lab_results: ApplyLabResultsUseCase
    experiment_repository: ExperimentRepository
    property_regressor: PropertyRegressor
    train_property_models: TrainPropertyModelsUseCase
    predict_properties: PredictPropertiesUseCase
    optimise_recipe: OptimiseRecipeUseCase
    job_registry: JobRegistry
    alert_notifier: AlertNotifier

    @classmethod
    async def build(cls, settings: AppSettings | None = None) -> Container:
        """Construct the container and initialise the database engine."""
        settings = settings or get_settings()
        settings.enforce_production_invariants()

        # Ensure data dir exists for local SQLite
        if settings.database_url.startswith("sqlite"):
            db_path_str = settings.database_url.split("///", 1)[-1]
            Path(db_path_str).parent.mkdir(parents=True, exist_ok=True)

        database = Database.from_url(
            url=settings.database_url,
            encryption_key_hex=settings.encryption_key_hex or None,
            echo=settings.database_echo,
        )
        await database.init()

        recipe_repository = ScopedRecipeRepository(database)
        audit_logger = ScopedAuditLogger(database)
        experiment_repository = ScopedExperimentRepository(database)
        property_regressor = PropertyRegressor(storage_dir=settings.model_dir)

        # Alerts + async jobs — process-local resources, no external
        # broker required.  See ``ml.jobs`` and ``notifications`` for
        # the design notes.
        alert_notifier = build_notifier(
            webhook_url=settings.alert_webhook_url,
            format=settings.alert_webhook_format,
            min_severity=settings.alert_min_severity,
        )
        snapshot_path = (
            settings.model_dir / "jobs.snapshot.json"
            if settings.async_job_snapshot_enabled
            else None
        )
        job_registry = JobRegistry(
            snapshot_path=snapshot_path,
            max_jobs=settings.async_job_max_records,
        )

        # Load the CSV-backed regulatory tables when they exist; otherwise
        # fall back to the compiled snapshot inside RegulatoryComplianceChecker.
        regulatory_checker = None
        try:
            regulatory_checker = build_checker_from_data_dir(settings.regulatory_data_dir)
        except RegulatoryDataError as exc:
            logger.warning(
                "regulatory_csv_unavailable",
                extra={"reason": str(exc), "path": str(settings.regulatory_data_dir)},
            )

        return cls(
            settings=settings,
            database=database,
            recipe_repository=recipe_repository,
            audit_logger=audit_logger,
            experiment_repository=experiment_repository,
            create_recipe=CreateRecipeUseCase(recipe_repository, audit_logger),
            update_recipe=UpdateRecipeUseCase(recipe_repository, audit_logger),
            delete_recipe=DeleteRecipeUseCase(recipe_repository, audit_logger),
            get_recipe=GetRecipeByIdUseCase(recipe_repository),
            get_recipe_versions=GetAllRecipeVersionsUseCase(recipe_repository),
            search_recipes=SearchRecipesUseCase(recipe_repository),
            catalog_stats=GetCatalogStatisticsUseCase(recipe_repository),
            submit_for_review=SubmitRecipeForReviewUseCase(recipe_repository, audit_logger),
            verify_recipe=VerifyRecipeUseCase(recipe_repository, audit_logger),
            reject_recipe=RejectRecipeUseCase(recipe_repository, audit_logger),
            create_new_version=CreateNewVersionUseCase(recipe_repository, audit_logger),
            assess_recipe=AssessRecipeUseCase(recipe_repository, regulatory_checker),
            calculate_cost=CalculateRecipeCostUseCase(recipe_repository),
            apply_lab_results=ApplyLabResultsUseCase(
                experiment_repository, recipe_repository, audit_logger
            ),
            property_regressor=property_regressor,
            train_property_models=TrainPropertyModelsUseCase(
                experiment_repository, recipe_repository, property_regressor
            ),
            predict_properties=PredictPropertiesUseCase(recipe_repository, property_regressor),
            optimise_recipe=OptimiseRecipeUseCase(recipe_repository, property_regressor),
            job_registry=job_registry,
            alert_notifier=alert_notifier,
        )

    async def close(self) -> None:
        """Dispose of resources (database engine)."""
        # Cancel any in-flight jobs first so they do not touch a
        # torn-down database.
        try:
            await self.job_registry.shutdown()
        except Exception:
            logger.warning("job_registry_shutdown_failed", exc_info=True)
        await self.database.close()

    async def __aenter__(self) -> Container:  # pragma: no cover — trivial
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # pragma: no cover
        await self.close()


__all__ = ["Container"]
