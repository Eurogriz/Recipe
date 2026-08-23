"""Seed the local database with realistic demo recipes + experiments.

Idempotent-ish: if the target recipe ids already exist we skip them and
still make sure at least one experiment is attached, so re-running the
script keeps the UI in a good state.

Usage:
    . .venv/bin/activate
    python scripts/dev/seed_demo.py

Environment:
    FW_DATABASE_URL   defaults to sqlite+aiosqlite:///./data/formulation.db
    FW_MODEL_DIR      defaults to ./data/models
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from formulation_workbench.application.use_cases.create_recipe import CreateRecipeCommand
from formulation_workbench.application.use_cases.get_recipe import GetRecipeByIdQuery
from formulation_workbench.domain.entities.experiment import (
    BatchInfo,
    ExperimentRun,
    ExperimentStatus,
    MeasuredValue,
)
from formulation_workbench.domain.entities.recipe import (
    Component,
    CompositionStage,
    ProcessParams,
    ProductClass,
    Recipe,
)
from formulation_workbench.domain.value_objects.citation import Citation
from formulation_workbench.domain.value_objects.isbn import Isbn
from formulation_workbench.infrastructure.config import AppSettings
from formulation_workbench.infrastructure.di import Container
from formulation_workbench.infrastructure.logging.setup import setup_logging

logger = logging.getLogger("seed_demo")


# --------------------------------------------------------------------------- Recipe presets


@dataclass(slots=True)
class RecipePreset:
    id: str
    category: str
    subcategory: str
    binder_type: str
    product_class: str
    intended_use: str
    tags: tuple[str, ...]
    finish: str = ""
    color: str = ""
    # (name, cas, function, mass%)
    components: list[tuple[str, str, str, float]] = field(default_factory=list)
    # measurement seed values used by the synthetic experiment (property_code, mean, spread)
    props: list[tuple[str, float, float]] = field(default_factory=list)


PRESETS: list[RecipePreset] = [
    RecipePreset(
        id="demo_acrylic_matte_interior",
        category="Краски",
        subcategory="Водно-дисперсионные интерьерные",
        binder_type="Styrene-acrylic",
        product_class="Premium",
        intended_use="Matte interior wall paint, low-VOC, dry rooms",
        tags=("interior", "matte", "acrylic", "low-voc"),
        finish="Matte",
        color="White (base A)",
        components=[
            ("Water", "7732-18-5", "vehicle", 27.0),
            ("Dispex Ultra PA 4560", "9003-04-7", "dispersant", 0.6),
            ("Foamex 1488", "63148-62-9", "defoamer", 0.3),
            ("Kathon LX 1.5%", "26172-55-4", "biocide_in_can", 0.15),
            ("TiO2 R-902+", "13463-67-7", "pigment", 20.5),
            ("Omyacarb 5 GU", "1317-65-3", "extender", 7.5),
            ("Talc IT extra", "14807-96-6", "extender", 3.7),
            ("Rheovis PU 1191", "mixture", "rheology_modifier", 0.8),
            ("Propylene glycol", "57-55-6", "coalescent", 1.5),
            ("Texanol", "25265-77-4", "coalescent", 1.5),
            ("Acronal 290 D (50%)", "mixture", "binder", 36.45),
        ],
        props=[("gloss_60", 4.2, 0.3), ("hiding_power", 6.9, 0.2), ("viscosity_mid_shear", 380.0, 30.0), ("voc_content", 15.0, 2.0)],
    ),
    RecipePreset(
        id="demo_acrylic_satin_interior",
        category="Краски",
        subcategory="Водно-дисперсионные интерьерные",
        binder_type="Pure-acrylic",
        product_class="Standard",
        intended_use="Satin interior wall paint, washable",
        tags=("interior", "satin", "acrylic", "washable"),
        finish="Satin (60° gloss 25 GU)",
        components=[
            ("Water", "7732-18-5", "vehicle", 24.0),
            ("Dispex Ultra PA 4560", "9003-04-7", "dispersant", 0.7),
            ("Foamex 1488", "63148-62-9", "defoamer", 0.3),
            ("Kathon LX 1.5%", "26172-55-4", "biocide_in_can", 0.15),
            ("TiO2 R-706", "13463-67-7", "pigment", 18.0),
            ("Omyacarb 2 GU", "1317-65-3", "extender", 6.0),
            ("Rheovis PU 1191", "mixture", "rheology_modifier", 0.95),
            ("Texanol", "25265-77-4", "coalescent", 2.0),
            ("Acronal 296 D (50%)", "mixture", "binder", 47.9),
        ],
        props=[("gloss_60", 26.0, 2.0), ("hiding_power", 7.5, 0.2), ("viscosity_mid_shear", 520.0, 40.0), ("voc_content", 20.0, 2.0)],
    ),
    RecipePreset(
        id="demo_alkyd_gloss_enamel",
        category="Краски",
        subcategory="Алкидные эмали",
        binder_type="Long-oil alkyd (60%)",
        product_class="Standard",
        intended_use="Gloss enamel for metal and wood, outdoor",
        tags=("alkyd", "gloss", "outdoor", "metal"),
        finish="High gloss (60° gloss ≥ 85 GU)",
        components=[
            ("White spirit", "8052-41-3", "solvent", 22.0),
            ("Xylene", "1330-20-7", "solvent", 6.0),
            ("Alkydal F 48 (60%)", "mixture", "binder", 46.0),
            ("TiO2 R-902+", "13463-67-7", "pigment", 22.0),
            ("Talc IT extra", "14807-96-6", "extender", 1.8),
            ("Cobalt octoate 6%", "136-52-7", "drier", 0.35),
            ("Zirconium octoate 12%", "22464-99-9", "drier", 0.5),
            ("Anti-skin (MEKO)", "96-29-7", "anti_skinning_agent", 0.35),
            ("BYK-066 N", "mixture", "defoamer", 0.3),
            ("BYK-P 104 S", "mixture", "wetting_agent", 0.7),
        ],
        props=[("gloss_60", 88.0, 3.0), ("hiding_power", 7.0, 0.2), ("viscosity_mid_shear", 950.0, 80.0), ("voc_content", 380.0, 20.0)],
    ),
    RecipePreset(
        id="demo_2k_epoxy_floor",
        category="Краски",
        subcategory="Двухкомпонентные эпоксидные",
        binder_type="Bisphenol-A epoxy + polyamide amine",
        product_class="Premium",
        intended_use="Industrial floor coating, chemical resistance",
        tags=("2k", "epoxy", "floor", "industrial"),
        finish="Semi-gloss",
        components=[
            ("Epikote 828 (EEW 190)", "25068-38-6", "epoxy_resin", 42.0),
            ("Versamid 125 (AHEW 300)", "mixture", "curing_agent", 22.0),
            ("Xylene", "1330-20-7", "solvent", 10.0),
            ("n-Butanol", "71-36-3", "solvent", 5.0),
            ("TiO2 R-960", "13463-67-7", "pigment", 12.0),
            ("Talc HTP1c", "14807-96-6", "extender", 5.0),
            ("Aerosil 200", "112945-52-5", "rheology_modifier", 1.0),
            ("BYK-A 530", "mixture", "defoamer", 0.5),
            ("Disperbyk-110", "mixture", "dispersant", 1.0),
            ("Silane A-187", "2530-83-8", "adhesion_promoter", 1.5),
        ],
        props=[("gloss_60", 60.0, 4.0), ("viscosity_mid_shear", 1500.0, 120.0), ("voc_content", 380.0, 25.0)],
    ),
    RecipePreset(
        id="demo_pu_clear_lacquer",
        category="Лаки",
        subcategory="Полиуретановые лаки",
        binder_type="Aliphatic PU + polyester polyol",
        product_class="Premium",
        intended_use="Clear protective lacquer for wood floors",
        tags=("pu", "clear", "wood", "protective"),
        finish="Semi-matte (60° 45 GU)",
        components=[
            ("Water", "7732-18-5", "vehicle", 40.0),
            ("Bayhydrol A 2470 (45%)", "mixture", "binder", 40.0),
            ("Bayhydur XP 2547", "mixture", "curing_agent", 12.0),
            ("Byk-346", "mixture", "wetting_agent", 0.5),
            ("Byk-028", "mixture", "defoamer", 0.4),
            ("Aquacer 8500", "mixture", "wax", 3.5),
            ("Butyl glycol", "111-76-2", "coalescent", 2.6),
            ("Rheovis PE 1330", "mixture", "rheology_modifier", 1.0),
        ],
        props=[("gloss_60", 45.0, 3.0), ("hiding_power", 0.2, 0.05), ("viscosity_mid_shear", 300.0, 25.0), ("voc_content", 60.0, 5.0)],
    ),
    RecipePreset(
        id="demo_universal_primer",
        category="Грунтовки",
        subcategory="Универсальные акриловые",
        binder_type="Acrylic dispersion (55%)",
        product_class="Standard",
        intended_use="Universal wall primer for indoor use",
        tags=("primer", "acrylic", "universal", "indoor"),
        components=[
            ("Water", "7732-18-5", "vehicle", 46.0),
            ("Dispex Ultra PA 4560", "9003-04-7", "dispersant", 0.5),
            ("Foamex 1488", "63148-62-9", "defoamer", 0.25),
            ("Kathon LX 1.5%", "26172-55-4", "biocide_in_can", 0.15),
            ("Omyacarb 5 GU", "1317-65-3", "extender", 12.0),
            ("Rheovis PU 1214", "mixture", "rheology_modifier", 0.6),
            ("Propylene glycol", "57-55-6", "coalescent", 1.5),
            ("Acronal 290 D (50%)", "mixture", "binder", 39.0),
        ],
        props=[("gloss_60", 6.0, 0.5), ("hiding_power", 3.5, 0.3), ("viscosity_mid_shear", 250.0, 20.0), ("voc_content", 12.0, 1.5)],
    ),
    RecipePreset(
        id="demo_water_wood_stain",
        category="Лаки",
        subcategory="Морилки водные",
        binder_type="Acrylic dispersion (40%)",
        product_class="Standard",
        intended_use="Water-based semi-transparent wood stain",
        tags=("wood", "stain", "acrylic", "water-based"),
        finish="Matte",
        color="Walnut",
        components=[
            ("Water", "7732-18-5", "vehicle", 68.0),
            ("Acrysol RM-8W", "mixture", "rheology_modifier", 0.8),
            ("Foamex 1488", "63148-62-9", "defoamer", 0.3),
            ("Kathon LX 1.5%", "26172-55-4", "biocide_in_can", 0.15),
            ("Iron oxide brown", "1309-37-1", "pigment", 3.5),
            ("Carbon black FW 200", "1333-86-4", "pigment", 0.35),
            ("Byk-346", "mixture", "wetting_agent", 0.5),
            ("Butyl glycol", "111-76-2", "coalescent", 1.4),
            ("Acronal Optive 320", "mixture", "binder", 25.0),
        ],
        props=[("gloss_60", 3.5, 0.4), ("hiding_power", 1.2, 0.15), ("viscosity_mid_shear", 90.0, 8.0), ("voc_content", 25.0, 2.0)],
    ),
    RecipePreset(
        id="demo_facade_silicone",
        category="Краски",
        subcategory="Силиконовые фасадные",
        binder_type="Silicone-modified acrylic",
        product_class="Premium",
        intended_use="Facade paint, breathable, water-repellent",
        tags=("facade", "silicone", "breathable", "exterior"),
        finish="Matte",
        components=[
            ("Water", "7732-18-5", "vehicle", 26.0),
            ("Dispex Ultra PA 4560", "9003-04-7", "dispersant", 0.7),
            ("Foamex 1488", "63148-62-9", "defoamer", 0.3),
            ("Kathon LX 1.5%", "26172-55-4", "biocide_in_can", 0.15),
            ("TiO2 R-902+", "13463-67-7", "pigment", 15.5),
            ("Omyacarb 5 GU", "1317-65-3", "extender", 12.0),
            ("Talc IT extra", "14807-96-6", "extender", 3.5),
            ("Rheovis PU 1191", "mixture", "rheology_modifier", 1.0),
            ("Silres BS 45 (55%)", "mixture", "additive", 6.0),
            ("Texanol", "25265-77-4", "coalescent", 1.85),
            ("Acronal 296 D (50%)", "mixture", "binder", 33.0),
        ],
        props=[("gloss_60", 5.0, 0.4), ("hiding_power", 6.7, 0.25), ("viscosity_mid_shear", 460.0, 35.0), ("voc_content", 18.0, 2.0)],
    ),
]


# --------------------------------------------------------------------------- helpers


def _build_recipe(preset: RecipePreset) -> Recipe:
    components = tuple(
        Component(
            name=name,
            cas_number=cas,
            function=fn,
            mass_percent=mp,
            tolerance_percent=0.5,
        )
        for name, cas, fn, mp in preset.components
    )
    stage = CompositionStage(
        stage_number=1,
        name="Full production (consolidated)",
        description="Demo composition — single stage for UI seeding.",
        components=components,
        process=ProcessParams(
            equipment="High-speed disperser",
            rotational_speed_rpm=2000,
            temperature_c=25.0,
            duration_min=45,
        ),
    )
    citation = Citation(
        authors="Flick, E.W.",
        title="Water-Based Paint Formulations (demo seed)",
        year=1995,
        publisher="Noyes Publications",
        isbn=Isbn("9780815513773"),
        page_or_formula="Demo seed for Formulation Workbench UI",
    )
    return Recipe(
        id=preset.id,
        category=preset.category,
        subcategory=preset.subcategory,
        binder_type=preset.binder_type,
        product_class=ProductClass(preset.product_class),
        intended_use=preset.intended_use,
        stages=(stage,),
        primary_source=citation,
        cross_references=(),
        created_by="demo-seed",
        tags=preset.tags,
        finish=preset.finish,
        color=preset.color,
    )


async def _ensure_recipe(container: Container, preset: RecipePreset) -> str:
    existing = await container.get_recipe.execute(GetRecipeByIdQuery(recipe_id=preset.id))
    if existing is not None:
        logger.info("recipe already exists — skipping", extra={"recipe_id": preset.id})
        return existing.id
    recipe = _build_recipe(preset)
    saved = await container.create_recipe.execute(
        CreateRecipeCommand(recipe=recipe, actor="demo-seed")
    )
    logger.info("recipe created", extra={"recipe_id": saved.id})
    return saved.id


async def _ensure_experiments(
    container: Container,
    preset: RecipePreset,
    recipe_id: str,
    *,
    per_recipe: int = 4,
) -> None:
    existing = await container.experiment_repository.list_for_recipe(recipe_id)
    if existing:
        logger.info(
            "experiments already present — skipping",
            extra={"recipe_id": recipe_id, "count": len(existing)},
        )
        return

    rng = random.Random(hash(recipe_id) & 0xFFFF)
    for i in range(per_recipe):
        run = ExperimentRun(
            id=f"exp_{recipe_id}_{i:02d}",
            recipe_id=recipe_id,
            recipe_version=1,
            operator="demo-op",
            status=ExperimentStatus.COMPLETED,
            created_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            batch=BatchInfo(
                batch_number=f"B-{recipe_id[-4:]}-{i:03d}",
                target_mass_kg=5.0,
                actual_mass_kg=round(5.0 + rng.uniform(-0.05, 0.05), 3),
                equipment_used="High-speed disperser",
            ),
            measured_properties=tuple(
                MeasuredValue(
                    property_code=code,
                    value=round(mean + rng.uniform(-spread, spread), 3),
                    unit=_unit_for(code),
                    operator="=",
                    notes="Synthetic demo measurement",
                )
                for code, mean, spread in preset.props
            ),
        )
        await container.experiment_repository.save(run)
    logger.info(
        "experiments seeded",
        extra={"recipe_id": recipe_id, "count": per_recipe},
    )


def _unit_for(code: str) -> str:
    return {
        "gloss_60": "GU",
        "hiding_power": "m2/L",
        "viscosity_mid_shear": "mPa·s",
        "voc_content": "g/L",
    }.get(code, "")


async def main() -> int:
    settings = AppSettings()
    setup_logging(log_level=settings.log_level, json_logs=False)
    container = await Container.build(settings)
    try:
        for preset in PRESETS:
            rid = await _ensure_recipe(container, preset)
            await _ensure_experiments(container, preset, rid, per_recipe=4)
        logger.info(
            "demo seed complete",
            extra={"recipes": len(PRESETS), "experiments": len(PRESETS) * 4},
        )
    finally:
        await container.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
