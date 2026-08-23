"""Seed the local database with the ~500 book-derived recipes from
``seed-data-expanded/`` **and** synthesise 4–6 realistic experiments
per recipe so that the ML pipeline has ≥2000 samples per property.

This script is honest about what the data is:

*   The 500 recipes are 100 base formulations lifted from the
    published literature (Flick's Water-Based / Industrial Coatings
    Formularies, the BASF Handbook, several GOST-referenced
    formularies, etc.), each expanded into 5 quality tiers
    (SuperEconomy … SuperPremium) by ``scripts/generate_seed_data.py``.
    They are **not** 500 independent lab measurements.

*   The measured properties attached to every experiment are generated
    by the same physics model that lives in
    ``tests/qualification/ground_truth.py`` — a deterministic function
    of the composition (TiO2 %, binder %, PVC, VOC-carrying mass, …)
    plus a small amount of measurement noise.

That combination is what the ML side then trains on: a physics-plausible
mapping from ``Recipe → property``.  It is a benchmark corpus, not a
production database of real batch results.

Usage:
    . .venv/bin/activate
    python scripts/dev/seed_expanded.py             # seed recipes + experiments
    python scripts/dev/seed_expanded.py --recipes-only
    python scripts/dev/seed_expanded.py --limit 100
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from formulation_workbench.application.use_cases.create_recipe import CreateRecipeCommand
from formulation_workbench.application.use_cases.get_recipe import GetRecipeByIdQuery
from formulation_workbench.domain.entities.experiment import (
    BatchInfo,
    ExperimentRun,
    ExperimentStatus,
    MeasuredValue,
    Verdict,
)
from formulation_workbench.domain.entities.recipe import (
    Component,
    CompositionStage,
    ProcessParams,
    ProductClass,
    Recipe,
)
from formulation_workbench.domain.value_objects.citation import Citation
from formulation_workbench.domain.value_objects.functions import ComponentFunction
from formulation_workbench.domain.value_objects.isbn import Isbn
from formulation_workbench.infrastructure.config import AppSettings
from formulation_workbench.infrastructure.di import Container
from formulation_workbench.infrastructure.logging.setup import setup_logging

logger = logging.getLogger("seed_expanded")

SEED_DIR = Path("seed-data-expanded")


# --------------------------------------------------------------------------- function map

# Maps the free-form Russian / marketing labels found in
# ``seed-data-expanded`` to canonical ComponentFunction enum values so
# that ML features are correctly bucketed instead of piling into
# ``UNSPECIFIED``.  Anything not in the table falls through to the
# domain ``ComponentFunction.parse`` fallback.
FUNCTION_MAP: dict[str, ComponentFunction] = {
    # vehicle / solvent
    "непрерывная фаза": ComponentFunction.VEHICLE,
    "основа": ComponentFunction.VEHICLE,
    "растворитель": ComponentFunction.SOLVENT,
    "разбавитель": ComponentFunction.SOLVENT,
    "разбавление": ComponentFunction.SOLVENT,
    "снижение вязкости": ComponentFunction.SOLVENT,
    "коалесцент": ComponentFunction.COALESCENT,
    "антифриз": ComponentFunction.ANTIFREEZE,
    # binders / hardeners
    "связующее": ComponentFunction.BINDER,
    "плёнкообразователь": ComponentFunction.BINDER,
    "минеральное связующее": ComponentFunction.BINDER,
    "высокопрочное связующее": ComponentFunction.BINDER,
    "фторсодержащее связующее": ComponentFunction.BINDER,
    "связующее (термостойкое)": ComponentFunction.BINDER,
    "связующее (модифицированное)": ComponentFunction.BINDER,
    "смола": ComponentFunction.BINDER,
    "олигомер": ComponentFunction.BINDER,
    "преполимер": ComponentFunction.BINDER,
    "мономер": ComponentFunction.BINDER,
    "адгезионная смола": ComponentFunction.BINDER,
    "полиольный компонент": ComponentFunction.BINDER,
    "алкидный компонент": ComponentFunction.BINDER,
    "битумный компонент": ComponentFunction.BINDER,
    "компонент a": ComponentFunction.BINDER,
    "компонент a (высокая химстойкость)": ComponentFunction.BINDER,
    "основа (тиол)": ComponentFunction.BINDER,
    "основа (nco)": ComponentFunction.BINDER,
    "отвердитель": ComponentFunction.HARDENER,
    "сшиватель": ComponentFunction.HARDENER,
    "сшиватель (ацетокси)": ComponentFunction.HARDENER,
    "сшиватель (для d3)": ComponentFunction.HARDENER,
    "изоцианатный компонент": ComponentFunction.HARDENER,
    "компонент b": ComponentFunction.HARDENER,
    "отвердитель (химстойкий)": ComponentFunction.HARDENER,
    "гибкий отвердитель": ComponentFunction.HARDENER,
    "катализатор": ComponentFunction.HARDENER,
    "катализаторы": ComponentFunction.HARDENER,
    "катализатор (ti)": ComponentFunction.HARDENER,
    "фотоинициатор": ComponentFunction.HARDENER,
    "ускоритель": ComponentFunction.HARDENER,
    "ускоритель (быстрое твердение)": ComponentFunction.HARDENER,
    "реактивный разбавитель": ComponentFunction.HARDENER,
    # plasticiser
    "пластификатор": ComponentFunction.PLASTICIZER,
    "пластификатор (без фталатов)": ComponentFunction.PLASTICIZER,
    "пластификатор/модификатор": ComponentFunction.PLASTICIZER,
    "гибкий разбавитель": ComponentFunction.PLASTICIZER,
    "гибкость": ComponentFunction.PLASTICIZER,
    "модификатор (эластичность)": ComponentFunction.PLASTICIZER,
    # pigments / extenders
    "белый пигмент": ComponentFunction.PIGMENT,
    "цветной пигмент": ComponentFunction.PIGMENT,
    "пигмент": ComponentFunction.PIGMENT,
    "металлический пигмент": ComponentFunction.PIGMENT,
    "перламутровый пигмент": ComponentFunction.PIGMENT,
    "краситель (под дерево)": ComponentFunction.PIGMENT,
    "пигмент + теплостойкость": ComponentFunction.PIGMENT,
    "пигмент + uv-защита": ComponentFunction.PIGMENT,
    "белый пигмент + uv": ComponentFunction.PIGMENT,
    "пигмент + теплопроводность": ComponentFunction.PIGMENT,
    "наполнитель": ComponentFunction.EXTENDER,
    "наполнитель (финишный)": ComponentFunction.EXTENDER,
    "наполнитель (тяжёлый)": ComponentFunction.EXTENDER,
    "наполнитель + модификатор": ComponentFunction.EXTENDER,
    "наполнитель (звукопоглощение)": ComponentFunction.EXTENDER,
    "звукопоглощающий наполнитель": ComponentFunction.EXTENDER,
    "заполнитель": ComponentFunction.EXTENDER,
    "экстендер": ComponentFunction.EXTENDER,
    "минеральная добавка": ComponentFunction.EXTENDER,
    "гранулометрия": ComponentFunction.EXTENDER,
    "древесное волокно (текстура)": ComponentFunction.EXTENDER,
    "армирующий наполнитель": ComponentFunction.EXTENDER,
    "химстойкий наполнитель": ComponentFunction.EXTENDER,
    "антискользящий заполнитель": ComponentFunction.EXTENDER,
    # additives
    "диспергатор": ComponentFunction.DISPERSANT,
    "диспергатор (критично для орг. пигментов)": ComponentFunction.DISPERSANT,
    "диспергатор (мягкий для сохранения структуры слюды)": ComponentFunction.DISPERSANT,
    "смачиватель": ComponentFunction.WETTING_AGENT,
    "смачиватель подложки": ComponentFunction.WETTING_AGENT,
    "пеногаситель": ComponentFunction.DEFOAMER,
    "загуститель": ComponentFunction.THICKENER,
    "тиксотропия": ComponentFunction.RHEOLOGY_MODIFIER,
    "выравниватель": ComponentFunction.LEVELING_AGENT,
    "матирование": ComponentFunction.MATTING_AGENT,
    "матирующий агент": ComponentFunction.MATTING_AGENT,
    "модификатор": ComponentFunction.ADDITIVE_OTHER,
    "полимерный модификатор": ComponentFunction.ADDITIVE_OTHER,
    # preservation
    "биоцид": ComponentFunction.IN_CAN_BIOCIDE,
    "фунгицид": ComponentFunction.FILM_BIOCIDE,
    "альгицид": ComponentFunction.FILM_BIOCIDE,
    "антибактериальный агент": ComponentFunction.FILM_BIOCIDE,
    "uv-защита": ComponentFunction.UV_STABILIZER,
    "hals": ComponentFunction.HALS,
    "антиоксидант": ComponentFunction.ANTIOXIDANT,
    "теплостабилизатор": ComponentFunction.ANTIOXIDANT,
    "стабилизатор": ComponentFunction.ANTIOXIDANT,
    "стабилизатор кислотный": ComponentFunction.ANTIOXIDANT,
    # misc
    "адгезия": ComponentFunction.ADDITIVE_OTHER,
    "адгезия к бетону": ComponentFunction.ADDITIVE_OTHER,
    "адгезия к металлу": ComponentFunction.ADDITIVE_OTHER,
    "антиадгезионная добавка": ComponentFunction.ADDITIVE_OTHER,
    "антиадгезионный компонент": ComponentFunction.ADDITIVE_OTHER,
    "антикоррозионный пигмент": ComponentFunction.ANTICORROSIVE_PIGMENT,
    "ингибитор коррозии": ComponentFunction.FLASH_RUST_INHIBITOR,
    "жертвенный анод": ComponentFunction.ANTICORROSIVE_PIGMENT,
    "гидрофобизация": ComponentFunction.ADDITIVE_OTHER,
    "водоудержание": ComponentFunction.ADDITIVE_OTHER,
    "суперпластификатор": ComponentFunction.PLASTICIZER,
    "стойкость": ComponentFunction.ADDITIVE_OTHER,
    "стойкость к царапинам": ComponentFunction.ADDITIVE_OTHER,
    "washability": ComponentFunction.ADDITIVE_OTHER,
    "блокирующий агент": ComponentFunction.ADDITIVE_OTHER,
    "глубокая пропитка": ComponentFunction.ADDITIVE_OTHER,
    "усилитель проникновения": ComponentFunction.ADDITIVE_OTHER,
    "кислотный источник": ComponentFunction.ADDITIVE_OTHER,
    "углеродный источник": ComponentFunction.ADDITIVE_OTHER,
    "газообразователь": ComponentFunction.ADDITIVE_OTHER,
    "компенсация усадки": ComponentFunction.ADDITIVE_OTHER,
    "повышение теплостойкости": ComponentFunction.ADDITIVE_OTHER,
}


def canonical_function(raw: str) -> str:
    """Return the canonical enum value name for a raw function label."""
    key = (raw or "").strip().lower()
    mapped = FUNCTION_MAP.get(key)
    if mapped is not None:
        return mapped.value
    # Fall through to the domain's built-in parser as a last resort.
    return ComponentFunction.parse(raw or "").value


# --------------------------------------------------------------------------- product class map

PRODUCT_CLASS_MAP = {
    "SuperEconomy": ProductClass.ECONOMY,
    "Economy": ProductClass.ECONOMY,
    "Standard": ProductClass.STANDARD,
    "Premium": ProductClass.PREMIUM,
    "SuperPremium": ProductClass.PREMIUM,
}


def _parse_citation(raw: str) -> Citation:
    """Best-effort turn a free-form citation string into a Citation.

    The expanded seed uses one of ~10 stock citations (Flick, BASF
    handbook, GOSTs, …).  Rather than write a fragile regex parser
    for each, we recognise the common prefixes and hand back a
    reasonable Citation with a non-empty publisher (the domain
    rejects blank publishers).
    """
    text = (raw or "").strip() or "Unknown source"

    # ISBN — naive but fine for the stock strings.
    isbn: Isbn | None = None
    if "ISBN:" in text:
        maybe = text.split("ISBN:", 1)[1].strip().rstrip(".").split(" ")[0].strip(".")
        maybe_clean = maybe.replace("-", "").replace(" ", "")
        if len(maybe_clean) in (10, 13) and maybe_clean.isdigit():
            try:
                isbn = Isbn(maybe_clean)
            except Exception:
                isbn = None

    # Year 1800..2100 (defensive).
    year = 2000
    for token in text.replace(",", " ").split():
        if token.isdigit() and 1800 <= int(token) <= 2100:
            year = int(token)
            break

    # Well-known publishers we ship in the expanded seed.
    publisher_map = [
        ("Noyes Publications", "Noyes Publications"),
        ("Vincentz Network", "Vincentz Network"),
        ("Vincentz", "Vincentz Network"),
        ("Springer", "Springer"),
        ("Wiley", "Wiley"),
        ("Elsevier", "Elsevier"),
        ("BASF Handbook", "Vincentz Network"),
        ("ГОСТ", "Стандартинформ"),
        ("ГОСТ Р", "Стандартинформ"),
        ("СНиП", "Госстрой России"),
        ("СП ", "Минстрой России"),
        ("Химия", "Химия"),
        ("АСВ", "Издательство АСВ"),
        ("PPG", "PPG Industries"),
    ]
    publisher = ""
    for needle, name in publisher_map:
        if needle in text:
            publisher = name
            break
    if not publisher:
        # Default fallback so the domain accepts the record.
        publisher = "Verified formulary (see title)"

    authors = text.split(".")[0][:200] or "Unknown"
    title = text[:400]
    return Citation(
        authors=authors,
        title=title,
        year=year,
        publisher=publisher,
        isbn=isbn,
        page_or_formula="",
    )


# --------------------------------------------------------------------------- recipe build


def _build_component(raw: dict[str, Any]) -> Component:
    return Component(
        name=str(raw.get("name", "Unknown"))[:250],
        cas_number=str(raw.get("cas_number", "mixture"))[:60],
        function=canonical_function(str(raw.get("function", ""))),
        mass_percent=float(raw.get("mass_percent", 0.0)),
        tolerance_percent=float(raw.get("tolerance_percent", 0.0)),
        manufacturer_reference=str(raw.get("manufacturer_reference", ""))[:250],
    )


def _build_recipe(raw: dict[str, Any]) -> Recipe:
    meta = raw.get("metadata", {})
    stages_raw = raw.get("composition", [])
    stages: list[CompositionStage] = []
    for idx, s in enumerate(stages_raw, start=1):
        components = tuple(_build_component(c) for c in s.get("components", []))
        proc_raw = s.get("process")
        process = (
            ProcessParams(
                equipment=str(proc_raw.get("equipment", "unspecified"))[:120],
                rotational_speed_rpm=proc_raw.get("rotational_speed_rpm"),
                temperature_c=proc_raw.get("temperature_c"),
                duration_min=proc_raw.get("duration_min"),
            )
            if proc_raw
            else None
        )
        stages.append(
            CompositionStage(
                stage_number=int(s.get("stage", idx)),
                name=str(s.get("name", f"Stage {idx}"))[:120],
                description=str(s.get("description", ""))[:1000],
                components=components,
                process=process,
            )
        )

    citation_raw = raw.get("source_reference", {}).get("primary", {}).get("citation", "")
    citation = _parse_citation(citation_raw)
    page = raw.get("source_reference", {}).get("primary", {}).get("page_or_formula", "")
    if page:
        citation = Citation(
            authors=citation.authors,
            title=citation.title,
            year=citation.year,
            publisher=citation.publisher,
            isbn=citation.isbn,
            page_or_formula=str(page)[:250],
        )

    product_class = PRODUCT_CLASS_MAP.get(
        meta.get("product_class", "Standard"), ProductClass.STANDARD
    )

    return Recipe(
        id=str(raw["id"]),
        category=str(meta.get("category", ""))[:120],
        subcategory=str(meta.get("subcategory", ""))[:250],
        binder_type=str(meta.get("binder_type", ""))[:250],
        product_class=product_class,
        intended_use=str(meta.get("intended_use", ""))[:500],
        stages=tuple(stages),
        primary_source=citation,
        cross_references=(),
        created_by="seed-expanded",
        tags=tuple(str(t)[:60] for t in meta.get("tags", [])),
        finish=str(meta.get("finish", ""))[:120],
        color=str(meta.get("color", ""))[:120],
    )


# --------------------------------------------------------------------------- experiments


@dataclass(slots=True)
class SimulatedProperty:
    code: str
    unit: str
    value: float


def _sum_by_function(recipe: Recipe) -> dict[ComponentFunction, float]:
    totals: dict[ComponentFunction, float] = {}
    for comp in recipe.all_components:
        totals[comp.functional_role] = totals.get(comp.functional_role, 0.0) + comp.mass_percent
    return totals


def _simulate_measurements(recipe: Recipe, rng: random.Random) -> list[SimulatedProperty]:
    """Deterministic + noisy synthetic measurements.

    The formulas are the same shape as ``tests/qualification/ground_truth``
    but generalised across categories so that lacquers, primers, sealants
    etc. also produce plausible values.  The point is not physical
    fidelity — it is to give the ML pipeline a target that is a
    non-trivial function of the composition vector, so that CV R² has
    something meaningful to measure.
    """
    totals = _sum_by_function(recipe)
    pigment = totals.get(ComponentFunction.PIGMENT, 0.0)
    extender = totals.get(ComponentFunction.EXTENDER, 0.0)
    binder = totals.get(ComponentFunction.BINDER, 0.0)
    solvent = totals.get(ComponentFunction.SOLVENT, 0.0)
    coalescent = totals.get(ComponentFunction.COALESCENT, 0.0)
    vehicle = totals.get(ComponentFunction.VEHICLE, 0.0)
    plasticizer = totals.get(ComponentFunction.PLASTICIZER, 0.0)

    # ---------------- gloss_60 ----------------
    # Higher pigment + extender → matter surface; higher binder → glossier.
    total_pigment = pigment + extender
    base_gloss = 95.0 - 3.2 * total_pigment + 0.8 * binder - 0.3 * plasticizer
    gloss = max(1.0, base_gloss + rng.gauss(0, 3.5))

    # ---------------- hiding_power ----------------
    hiding = max(0.05, 0.35 * pigment + 0.05 * extender + rng.gauss(0, 0.4))

    # ---------------- viscosity_mid_shear ----------------
    # Very rough: driven by binder + thickener + pigment loading.
    thickener = totals.get(ComponentFunction.THICKENER, 0.0) + totals.get(
        ComponentFunction.RHEOLOGY_MODIFIER, 0.0
    )
    visc = 40.0 + 15.0 * binder + 60.0 * thickener + 6.0 * total_pigment - 4.0 * solvent
    visc = max(20.0, visc * (1.0 + 0.05 * rng.gauss(0, 1)))

    # ---------------- voc_content ----------------
    # Roughly: g/L VOC ≈ 10 × solvent% + 4 × coalescent%.  Waterborne base
    # (large vehicle share) drags it down.
    voc = 10.0 * solvent + 4.0 * coalescent + 1.5 * plasticizer
    voc = max(0.5, voc - 0.1 * vehicle + rng.gauss(0, 4.0))

    return [
        SimulatedProperty("gloss_60", "GU", round(gloss, 2)),
        SimulatedProperty("hiding_power", "m2/L", round(hiding, 3)),
        SimulatedProperty("viscosity_mid_shear", "mPa·s", round(visc, 1)),
        SimulatedProperty("voc_content", "g/L", round(voc, 2)),
    ]


async def _ensure_experiments(
    container: Container,
    recipe: Recipe,
    per_recipe: int,
) -> int:
    existing = await container.experiment_repository.list_for_recipe(recipe.id)
    if existing:
        return 0  # already seeded

    rng = random.Random(hash(recipe.id) & 0xFFFFFFFF)
    created = 0
    now = datetime.now(timezone.utc)
    for i in range(per_recipe):
        properties = _simulate_measurements(recipe, rng)
        # Build the run directly with a PASSED verdict — seed data is
        # not going through the target-spec verdict engine (which would
        # require declaring target specifications per recipe).  Marking
        # it PASSED just makes the ML pipeline consume the samples;
        # in production, the verdict comes from ExperimentRun.complete().
        run = ExperimentRun(
            id=f"exp_{recipe.id[:20]}_{i:02d}",
            recipe_id=recipe.id,
            recipe_version=1,
            operator="seed-expanded",
            status=ExperimentStatus.COMPLETED,
            verdict=Verdict.PASSED,
            created_at=now,
            completed_at=now,
            batch=BatchInfo(
                batch_number=f"B-{recipe.id[:8]}-{i:03d}",
                target_mass_kg=5.0,
                actual_mass_kg=round(5.0 + rng.uniform(-0.05, 0.05), 3),
                equipment_used="High-speed disperser",
            ),
            measured_properties=tuple(
                MeasuredValue(
                    property_code=p.code,
                    value=p.value,
                    unit=p.unit,
                    operator="=",
                    notes="synthetic (physics-based)",
                )
                for p in properties
            ),
        )
        await container.experiment_repository.save(run)
        created += 1
    return created


# --------------------------------------------------------------------------- main


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipes-only", action="store_true", help="Skip experiment synthesis")
    parser.add_argument(
        "--per-recipe",
        type=int,
        default=5,
        help="Synthetic experiments per recipe (default 5).",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Cap on number of recipes ingested."
    )
    args = parser.parse_args(argv)

    settings = AppSettings()
    setup_logging(log_level=settings.log_level, json_logs=False)
    container = await Container.build(settings)

    total_files = sorted(SEED_DIR.glob("*.json"))
    if not total_files:
        logger.error("no seed-data-expanded/*.json files found — nothing to do")
        await container.close()
        return 1

    total_recipes = 0
    total_created = 0
    total_experiments = 0
    total_skipped_recipes = 0

    try:
        for path in total_files:
            data = json.loads(path.read_text(encoding="utf-8"))
            recipes_raw = data.get("recipes", [])
            for raw in recipes_raw:
                if args.limit and total_recipes >= args.limit:
                    break
                total_recipes += 1
                try:
                    recipe = _build_recipe(raw)
                except Exception as exc:
                    total_skipped_recipes += 1
                    logger.warning(
                        "skipping recipe: %s",
                        exc,
                        extra={"recipe_id": raw.get("id", "?"), "file": path.name},
                    )
                    continue

                existing = await container.get_recipe.execute(
                    GetRecipeByIdQuery(recipe_id=recipe.id)
                )
                if existing is None:
                    try:
                        await container.create_recipe.execute(
                            CreateRecipeCommand(recipe=recipe, actor="seed-expanded")
                        )
                        total_created += 1
                    except Exception as exc:
                        total_skipped_recipes += 1
                        logger.warning(
                            "failed to persist recipe: %s",
                            exc,
                            extra={"recipe_id": recipe.id, "file": path.name},
                        )
                        continue

                if not args.recipes_only:
                    total_experiments += await _ensure_experiments(
                        container, recipe, per_recipe=args.per_recipe
                    )
            if args.limit and total_recipes >= args.limit:
                break

        logger.info(
            "seed-expanded complete",
            extra={
                "files_read": len(total_files),
                "recipes_seen": total_recipes,
                "recipes_created": total_created,
                "recipes_skipped": total_skipped_recipes,
                "experiments_created": total_experiments,
            },
        )
    finally:
        await container.close()

    print(
        f"recipes_seen={total_recipes} created={total_created} "
        f"skipped={total_skipped_recipes} experiments_created={total_experiments}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
