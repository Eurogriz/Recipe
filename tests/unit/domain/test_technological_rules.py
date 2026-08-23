"""Tests for the technological validity rules."""

from __future__ import annotations

from formulation_workbench.domain.entities.recipe import (
    Component,
    CompositionStage,
    ProcessParams,
    ProductClass,
    Recipe,
)
from formulation_workbench.domain.services.technological_rules import (
    Severity,
    evaluate,
    voc_ceiling_for,
)
from formulation_workbench.domain.value_objects.citation import Citation
from formulation_workbench.domain.value_objects.functions import ComponentFunction
from formulation_workbench.domain.value_objects.isbn import Isbn
from formulation_workbench.domain.value_objects.physical_properties import PhysicalProperties
from formulation_workbench.domain.value_objects.target_properties import (
    TargetSpecification,
    ToleranceMode,
)


def _cite() -> Citation:
    return Citation(
        authors="Flick",
        title="WBPF",
        year=1995,
        publisher="Noyes Publications",
        isbn=Isbn("9780815513773"),
    )


def _make_recipe(
    components: list[Component],
    *,
    category: str = "Краски",
    subcategory: str = "Водно-дисперсионные",
    targets: tuple[TargetSpecification, ...] = (),
) -> Recipe:
    return Recipe(
        category=category,
        subcategory=subcategory,
        binder_type="Acrylic",
        product_class=ProductClass.STANDARD,
        intended_use="Test",
        stages=(
            CompositionStage(
                stage_number=1,
                name="Mix",
                description="",
                components=tuple(components),
                process=ProcessParams(equipment="Disperser"),
            ),
        ),
        primary_source=_cite(),
        target_properties=targets,
    )


def _c(
    name: str,
    role: ComponentFunction,
    mass: float,
    *,
    cas: str = "mixture",
    props: PhysicalProperties | None = None,
) -> Component:
    return Component(
        name=name,
        cas_number=cas,
        function=role.value,
        mass_percent=mass,
        functional_role=role,
        properties=props,
    )


class TestNoBinder:
    def test_missing_binder_is_error(self) -> None:
        recipe = _make_recipe(
            [
                _c("Water", ComponentFunction.VEHICLE, 50.0, cas="7732-18-5"),
                _c("TiO2", ComponentFunction.PIGMENT, 30.0, cas="13463-67-7"),
                _c("Talc", ComponentFunction.EXTENDER, 20.0, cas="14807-96-6"),
            ]
        )
        findings = evaluate(recipe)
        assert any(f.rule_id == "T1" and f.severity is Severity.ERROR for f in findings)


class TestAdditiveEnvelope:
    def test_moderate_defoamer_overdose_warns(self) -> None:
        # 1.5 % is above the 0.8 % max but well under the ≥ 5× ERROR
        # threshold, so it stays a WARNING.
        recipe = _make_recipe(
            [
                _c("Water", ComponentFunction.VEHICLE, 40.0, cas="7732-18-5"),
                _c("Acrylic", ComponentFunction.BINDER, 38.5),
                _c("TiO2", ComponentFunction.PIGMENT, 20.0, cas="13463-67-7"),
                _c("Foamex", ComponentFunction.DEFOAMER, 1.5),
            ]
        )
        findings = evaluate(recipe)
        assert any(f.rule_id == "T3" and f.severity is Severity.WARNING for f in findings)

    def test_gross_defoamer_overdose_is_an_error(self) -> None:
        # 5 % is ≥ 5× the 0.8 % envelope maximum — must escalate to ERROR
        # so a broken formulation cannot reach production-ready maturity.
        recipe = _make_recipe(
            [
                _c("Water", ComponentFunction.VEHICLE, 40.0, cas="7732-18-5"),
                _c("Acrylic", ComponentFunction.BINDER, 35.0),
                _c("TiO2", ComponentFunction.PIGMENT, 20.0, cas="13463-67-7"),
                _c("Foamex", ComponentFunction.DEFOAMER, 5.0),
            ]
        )
        findings = evaluate(recipe)
        assert any(f.rule_id == "T3" and f.severity is Severity.ERROR for f in findings)

    def test_biocide_within_envelope_ok(self) -> None:
        recipe = _make_recipe(
            [
                _c("Water", ComponentFunction.VEHICLE, 40.0, cas="7732-18-5"),
                _c("Acrylic", ComponentFunction.BINDER, 35.0),
                _c("TiO2", ComponentFunction.PIGMENT, 20.0, cas="13463-67-7"),
                _c("Kathon", ComponentFunction.IN_CAN_BIOCIDE, 0.2),
                _c("Foamex", ComponentFunction.DEFOAMER, 0.3),
                _c("Dispex", ComponentFunction.DISPERSANT, 0.5),
                _c("Rheo", ComponentFunction.RHEOLOGY_MODIFIER, 0.5),
                _c("pH mod", ComponentFunction.PH_MODIFIER, 0.2),
                _c("Wet", ComponentFunction.WETTING_AGENT, 0.3),
                _c("Antifz", ComponentFunction.ANTIFREEZE, 3.0),
            ]
        )
        findings = evaluate(recipe)
        # No error, no envelope-based warning for these additives.
        assert not any(f.severity is Severity.ERROR for f in findings)


class TestWaterBasedRules:
    def test_water_without_biocide_warns(self) -> None:
        recipe = _make_recipe(
            [
                _c("Water", ComponentFunction.VEHICLE, 40.0, cas="7732-18-5"),
                _c("Acrylic", ComponentFunction.BINDER, 40.0),
                _c("TiO2", ComponentFunction.PIGMENT, 20.0, cas="13463-67-7"),
            ]
        )
        findings = evaluate(recipe)
        assert any(f.rule_id == "T4" for f in findings)

    def test_high_tg_binder_needs_coalescent(self) -> None:
        recipe = _make_recipe(
            [
                _c("Water", ComponentFunction.VEHICLE, 45.0, cas="7732-18-5"),
                _c(
                    "Acrylic-hard",
                    ComponentFunction.BINDER,
                    35.0,
                    props=PhysicalProperties(glass_transition_c=25.0),
                ),
                _c("TiO2", ComponentFunction.PIGMENT, 20.0, cas="13463-67-7"),
            ]
        )
        findings = evaluate(recipe)
        assert any(f.rule_id == "T6" and f.severity is Severity.WARNING for f in findings)


class TestVOCceiling:
    def test_voc_ceiling_lookup(self) -> None:
        recipe = _make_recipe(
            [
                _c("Water", ComponentFunction.VEHICLE, 40.0, cas="7732-18-5"),
                _c("Acrylic", ComponentFunction.BINDER, 40.0),
                _c("TiO2", ComponentFunction.PIGMENT, 20.0, cas="13463-67-7"),
            ]
        )
        assert voc_ceiling_for(recipe) == 30.0

    def test_voc_target_exceeds_ceiling(self) -> None:
        target = TargetSpecification(
            property_code="voc_content",
            target_value=250.0,
            tolerance_mode=ToleranceMode.MAX,
        )
        recipe = _make_recipe(
            [
                _c("Water", ComponentFunction.VEHICLE, 40.0, cas="7732-18-5"),
                _c("Acrylic", ComponentFunction.BINDER, 40.0),
                _c("TiO2", ComponentFunction.PIGMENT, 20.0, cas="13463-67-7"),
            ],
            targets=(target,),
        )
        findings = evaluate(recipe)
        assert any(f.rule_id == "T7" and f.severity is Severity.ERROR for f in findings)


class TestHardenerRatio:
    def test_low_ratio_warns(self) -> None:
        recipe = _make_recipe(
            [
                _c("Water", ComponentFunction.VEHICLE, 20.0, cas="7732-18-5"),
                _c("PU resin", ComponentFunction.BINDER, 70.0),
                _c("Isocyanate", ComponentFunction.HARDENER, 1.0),
                _c("TiO2", ComponentFunction.PIGMENT, 9.0, cas="13463-67-7"),
            ]
        )
        findings = evaluate(recipe)
        assert any(f.rule_id == "T8" for f in findings)


class TestSolventWaterMix:
    def test_hybrid_water_solvent_warning(self) -> None:
        recipe = _make_recipe(
            [
                _c("Water", ComponentFunction.VEHICLE, 30.0, cas="7732-18-5"),
                _c("Xylene", ComponentFunction.SOLVENT, 20.0),
                _c("Acrylic", ComponentFunction.BINDER, 40.0),
                _c("TiO2", ComponentFunction.PIGMENT, 10.0, cas="13463-67-7"),
            ]
        )
        findings = evaluate(recipe)
        assert any(f.rule_id == "T9" for f in findings)
