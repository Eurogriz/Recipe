"""Smoke test: verify all critical modules can be imported.

This is a basic sanity check that the codebase is structurally valid.
Run early in CI to catch import errors before deeper tests.
"""

from __future__ import annotations

import pytest


class TestSmokeImports:
    """Verify all public modules can be imported without errors."""

    def test_domain_value_objects_importable(self) -> None:
        from domain.value_objects.cas_number import CasNumber
        from domain.value_objects.isbn import Isbn
        from domain.value_objects.doi import Doi
        from domain.value_objects.mass_percent import MassPercent
        from domain.value_objects.verification_status import VerificationStatus
        from domain.value_objects.citation import Citation
        # All imports succeeded
        assert CasNumber is not None
        assert Isbn is not None
        assert Doi is not None
        assert MassPercent is not None
        assert VerificationStatus is not None
        assert Citation is not None

    def test_domain_entities_importable(self) -> None:
        from domain.entities.recipe import (
            Recipe,
            Component,
            CompositionStage,
            ProcessParams,
            ProductClass,
        )
        assert Recipe is not None
        assert Component is not None
        assert CompositionStage is not None
        assert ProcessParams is not None
        assert ProductClass is not None

    def test_domain_services_importable(self) -> None:
        from domain.services.verification_rules import VerificationRules
        from domain.services.class_ranker import ClassRanker, ClassRanking
        assert VerificationRules is not None
        assert ClassRanker is not None
        assert ClassRanking is not None

    def test_domain_events_importable(self) -> None:
        from domain.events import (
            RecipeCreated,
            RecipeUpdated,
            RecipeSubmittedForReview,
            RecipeVerified,
            RecipeRejected,
        )
        assert RecipeCreated is not None
        assert RecipeVerified is not None

    def test_application_layer_importable(self) -> None:
        from application.ports.recipe_repository import RecipeRepository
        from application.ports.audit_logger import AuditLogger
        from application.use_cases.create_recipe import (
            CreateRecipeCommand,
            CreateRecipeUseCase,
        )
        assert RecipeRepository is not None
        assert AuditLogger is not None
        assert CreateRecipeUseCase is not None

    def test_infrastructure_db_importable(self) -> None:
        from infrastructure.db.connection import Database
        from infrastructure.db.models import Base, RecipeModel, ComponentModel
        assert Database is not None
        assert Base is not None
        assert RecipeModel is not None
        assert ComponentModel is not None

    def test_infrastructure_logging_importable(self) -> None:
        from infrastructure.logging.setup import setup_logging, get_logger
        assert setup_logging is not None
        assert get_logger is not None

    def test_infrastructure_i18n_importable(self) -> None:
        from infrastructure.i18n import _, ngettext, setup_i18n
        assert _ is not None
        assert ngettext is not None
        assert setup_i18n is not None


class TestSmokeInstantiation:
    """Verify key objects can be instantiated with valid inputs."""

    def test_recipe_full_lifecycle(self) -> None:
        """Create a Recipe, submit for review, verify, then check Verified state."""
        from domain.entities.recipe import (
            Component,
            CompositionStage,
            ProcessParams,
            ProductClass,
            Recipe,
        )
        from domain.value_objects.citation import Citation
        from domain.value_objects.isbn import Isbn
        from domain.value_objects.verification_status import VerificationState

        # Create citation
        citation = Citation(
            authors="Flick, E.W.",
            title="Water-Based Paint Formulations, Vol. 3",
            year=1995,
            publisher="Noyes Publications",
            isbn=Isbn("9780815513773"),
        )

        # Create recipe
        components = (
            Component(name="Water", cas_number="7732-18-5", function="vehicle", mass_percent=50.0),
            Component(name="Binder", cas_number="mixture", function="binder", mass_percent=40.0),
            Component(name="TiO2", cas_number="13463-67-7", function="pigment", mass_percent=10.0),
        )
        recipe = Recipe(
            category="Краски",
            subcategory="Водно-дисперсионные",
            binder_type="Акриловая",
            product_class=ProductClass.PREMIUM,
            intended_use="Interior walls",
            stages=(
                CompositionStage(
                    stage_number=1,
                    name="Mixing",
                    description="",
                    components=components,
                    process=ProcessParams(equipment="Disperser"),
                ),
            ),
            primary_source=citation,
        )

        # Verify lifecycle
        assert recipe.status.state == VerificationState.DRAFT

        submitted = recipe.submit_for_review()
        assert submitted.status.state == VerificationState.PENDING_REVIEW

        v1 = submitted.verify()
        v2 = v1.verify()
        v3 = v2.verify()
        assert v3.status.state == VerificationState.VERIFIED
        assert v3.status.verification_count == 3

    def test_class_ranker_end_to_end(self) -> None:
        """Run ClassRanker on a complete recipe."""
        from domain.entities.recipe import (
            Component,
            CompositionStage,
            ProcessParams,
            ProductClass,
            Recipe,
        )
        from domain.services.class_ranker import ClassRanker
        from domain.value_objects.citation import Citation

        recipe = Recipe(
            category="Краски",
            subcategory="Водно-дисперсионные",
            binder_type="Acrylic polyurethane",
            product_class=ProductClass.PREMIUM,
            intended_use="Test",
            stages=(
                CompositionStage(
                    stage_number=1,
                    name="Mixing",
                    description="",
                    components=(
                        Component(name="Water", cas_number="7732-18-5", function="vehicle", mass_percent=30.0),
                        Component(name="Binder", cas_number="mixture", function="binder", mass_percent=40.0),
                        Component(
                            name="TiO2 rutile",
                            cas_number="13463-67-7",
                            function="pigment",
                            mass_percent=20.0,
                            notes="rutile",
                        ),
                        Component(name="HALS", cas_number="proprietary", function="uv stabilizer", mass_percent=2.0),
                        Component(name="Defoamer", cas_number="63148-62-9", function="defoamer", mass_percent=0.5),
                        Component(name="Coalescent", cas_number="25265-77-4", function="coalescent", mass_percent=2.0),
                        Component(name="Biocide", cas_number="26172-55-4", function="biocide", mass_percent=0.5),
                        Component(name="Thickener", cas_number="proprietary", function="thickener", mass_percent=1.0),
                        Component(name="Glycol", cas_number="57-55-6", function="antifreeze", mass_percent=4.0),
                    ),
                    process=ProcessParams(equipment="Disperser"),
                ),
            ),
            primary_source=Citation(
                authors="Flick, E.W.",
                title="Water-Based Paint Formulations, Vol. 3",
                year=1995,
                publisher="Noyes Publications",
            ),
        )

        ranking = ClassRanker.rank(recipe)
        assert ranking.recommended_class in [c for c in ProductClass]
        assert 0.0 <= ranking.confidence <= 1.0
