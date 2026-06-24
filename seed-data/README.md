{
  "_manifest": "Formulation Workbench — Seed Dataset v1.0.0",
  "_description": "Starter dataset of verified formulations. Each recipe has a primary source citation with ISBN/DOI and at least one cross-reference. The dataset is intended as a foundation — extend to 500+ recipes with additional sources from Flick, Wicks/Jones/Pappas, Goldschmidt/Streitberger, Petrie, Ebnesajjad, and technical bulletins from raw material manufacturers.",
  "_version": "1.0.0",
  "_date": "2026-06-24",
  "_disclaimer": "All recipes are provided for reference purposes. Industrial use requires laboratory validation and adaptation to specific raw materials. See individual recipe source_reference for verification status.",
  "_categories": {
    "laki": {"name": "Лаки", "recipes": 5},
    "kraski": {"name": "Краски", "recipes": 6},
    "kolery": {"name": "Колеры и пигментные пасты", "recipes": 4},
    "klei": {"name": "Клеи", "recipes": 5},
    "germetiki": {"name": "Герметики", "recipes": 4},
    "mastiki": {"name": "Мастики", "recipes": 3},
    "gruntovki": {"name": "Грунтовки, шпатлёвки, штукатурки, наливные полы", "recipes": 4},
    "special": {"name": "Антикоррозия, огнезащита, гидроизоляция", "recipes": 3}
  },
  "_verification_workflow": {
    "status": "All recipes in this dataset have status='Draft' by default",
    "next_step": "Each must undergo triple-verification (3 independent reviewers) before becoming 'Verified'",
    "required_verifications": 3
  },
  "_recipes_index": {
    "laki": "seed-data/laki.json",
    "kraski": "seed-data/kraski.json",
    "kolery": "seed-data/kolery.json",
    "klei": "seed-data/klei.json",
    "germetiki": "seed-data/germetiki.json",
    "mastiki": "seed-data/mastiki.json",
    "gruntovki": "seed-data/gruntovki.json",
    "special": "seed-data/special.json"
  }
}
