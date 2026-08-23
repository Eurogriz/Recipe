# ADR-0007 — Formulation domain model becomes production-grade

- **Status:** Accepted (2026-08-23)
- **Deciders:** Maintainers (Eurogriz)
- **Related:** ADR-0006 (headless service pivot).

## Context

Up to v1.1.3 the *infrastructure* was production-grade (CI, JWT, K8s,
Trivy, HPA, OTEL) but the *formulation domain itself* still exposed the
weaknesses of the original MVP:

- `Component.function` was a free-text string — no controlled vocabulary,
  no per-function dosing envelopes, no way to plug in the calculators
  automatically.
- Every physical parameter (density, VOC fraction, Tg, oil absorption,
  Hansen parameters, …) had to be guessed by the calculators from the
  component name via `str.lower().contains(...)` — accurate only for the
  most textbook materials.
- Raw materials existed only as embedded rows inside recipes, so
  identical ingredients could not be shared, deprecated, or tied to
  suppliers.
- Verification consisted of five bibliographic rules (`R1-R5`) —
  publisher whitelist, CAS format, primary source ISBN/DOI. There was
  **no** technological check: a recipe with no binder, defoamer at 5 %,
  or VOC above the EU 2004/42/EC ceiling would still pass.
- Target properties + test methods were absent entirely.  A "Verified"
  recipe carried no promise about *what it should deliver in a lab*.
- Batch and experiment tracking did not exist; there was no path from a
  physically-produced sample to the recipe that generated it.

## Decision

Introduce a curated, first-class domain model for formulations:

1. **`ComponentFunction` enum + `FunctionEnvelope`** — 30 named
   functions, each with min/max dose window drawn from the
   `Flick / Wicks / Vincentz` literature. Free-text ingestion still
   works via `ComponentFunction.parse` synonyms.

2. **`PhysicalProperties` VO** — 22 optional fields. Everything is
   nullable so legacy imports do not break.

3. **`RawMaterial` aggregate root** — shared, versionable ingredient
   catalog with supplier references and deprecation semantics.

4. **`TargetSpecification` + property catalogue** (44 properties, six
   `PropertyCategory` buckets) — each with default `TestMethod`s
   (ISO / ГОСТ / ASTM / DIN) and 5 tolerance modes.

5. **`domain/services/technological_rules.py`** — 13 pure functions
   that walk a `Recipe` and emit `RuleFinding(rule_id, severity,
   message, reference)`.  The VOC rule looks up the ceiling from EU
   2004/42/EC by category/subcategory.

6. **`RecipeAssessmentService`** — aggregates verification + technological
   findings into a numeric score (0-100), a `Maturity` label, and a
   summary dict. Score is auditable — the penalty table is a small
   class-level constant.

7. **`ExperimentRun` aggregate** — closes the loop
   `predicted → measured`.  Verdict (`PASSED` /
   `PASSED_WITH_DEVIATION` / `FAILED` / `INCONCLUSIVE`) is auto-derived
   from the intersection of `MeasuredValue` and `TargetSpecification`.

8. **HTTP endpoint** `GET /recipes/{id}/assessment` exposes the score
   so external systems (LIMS, PLM, QA dashboards) can gate promotion
   without re-implementing the rules.

## Consequences

**Positive**

- Recipes now carry the physicochemical data the calculators need,
  eliminating the "guess density from the name" heuristic.
- Every verification decision (Draft → Verified) can be justified with
  a reference to a published rule.
- Regulatory promises (VOC ceilings, REACH) are enforced by the model
  instead of by a human reading a datasheet.
- The lab loop — batch, measured properties, verdict — is a first-class
  citizen instead of a spreadsheet next to the recipe.

**Negative**

- Downstream consumers must update their JSON writers to include
  `functional_role` for new components (existing free-text `function`
  is still parsed).
- The number of tests grew from 203 → 273 (+35 %) and the domain now
  spans 12 modules instead of 6 — the codebase is larger.

**Alternatives considered**

- **Keep the free-text function + heuristic calculators.** Rejected:
  every new material broke the calculators.
- **Import an existing ontology (e.g. ChEBI, PubChem).** Deferred to a
  later ADR — the immediate goal is dosing envelopes, not chemistry
  reasoning.
- **Push technological rules to an external rules engine (Drools /
  ClaraRules).** Rejected: pure Python functions keep the domain layer
  side-effect-free and testable.

## References

- `src/formulation_workbench/domain/value_objects/functions.py`
- `src/formulation_workbench/domain/value_objects/physical_properties.py`
- `src/formulation_workbench/domain/value_objects/target_properties.py`
- `src/formulation_workbench/domain/entities/raw_material.py`
- `src/formulation_workbench/domain/entities/experiment.py`
- `src/formulation_workbench/domain/services/technological_rules.py`
- `src/formulation_workbench/domain/services/recipe_assessment.py`
- `src/formulation_workbench/application/use_cases/assess_recipe.py`
- `tests/unit/domain/test_*.py`
