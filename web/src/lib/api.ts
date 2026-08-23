/**
 * Thin wrapper around the FastAPI backend.
 *
 * Everything goes through `/api/*` which is proxied server-side by
 * next.config.mjs so the browser never talks to another origin.
 */

export type ApiError = { status: number; message: string; detail?: unknown };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail: unknown = undefined;
    try {
      detail = await res.json();
    } catch {
      /* ignore */
    }
    throw {
      status: res.status,
      message: `${res.status} ${res.statusText}`,
      detail,
    } satisfies ApiError;
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// --------------------------------------------------------------------------- health

export type Health = { status: string; version: string; environment: string };
export type Info = {
  name: string;
  version: string;
  environment: string;
  python: string;
  platform: string;
  git_sha: string;
  build_date: string;
};

export const api = {
  health: () => request<Health>("/health"),
  info: () => request<Info>("/info"),

  // recipes
  listRecipes: (params?: {
    q?: string;
    category?: string[];
    product_class?: string[];
    limit?: number;
    offset?: number;
  }) => {
    const q = new URLSearchParams();
    if (params?.q) q.set("q", params.q);
    if (params?.category) params.category.forEach((c) => q.append("category", c));
    if (params?.product_class)
      params.product_class.forEach((c) => q.append("product_class", c));
    if (params?.limit) q.set("limit", String(params.limit));
    if (params?.offset) q.set("offset", String(params.offset));
    const qs = q.toString();
    return request<SearchResponse>(`/recipes${qs ? "?" + qs : ""}`);
  },
  getRecipe: (id: string) => request<RecipeSummary>(`/recipes/${id}`),
  getRecipeFull: (id: string) => request<RecipeFull>(`/recipes/${id}/full`),
  assessRecipe: (id: string) => request<Assessment>(`/recipes/${id}/assessment`),
  costRecipe: (id: string, body: CostRequest) =>
    request<RecipeCost>(`/recipes/${id}/cost`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  predictRecipe: (id: string, explainTopK = 3) =>
    request<PredictionsOut>(`/recipes/${id}/predict?explain_top_k=${explainTopK}`),

  catalogStats: () => request<CatalogStats>("/catalog/stats"),

  // ml
  listModels: () => request<ModelMetadata[]>("/ml/models"),
  calibrationMatrix: () => request<CalibrationMatrix>("/ml/calibration-matrix"),
  trainSync: (body: { recipe_ids: string[]; property_codes?: string[] }) =>
    request<TrainResult>("/ml/train", { method: "POST", body: JSON.stringify(body) }),
  trainAsync: (body: { recipe_ids: string[]; property_codes?: string[] }) =>
    request<JobRecord>("/ml/train/async", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // jobs
  listJobs: (params?: { status?: string; kind?: string; limit?: number }) => {
    const q = new URLSearchParams();
    if (params?.status) q.set("status", params.status);
    if (params?.kind) q.set("kind", params.kind);
    if (params?.limit) q.set("limit", String(params.limit));
    const qs = q.toString();
    return request<{ jobs: JobRecord[] }>(`/ml/jobs${qs ? "?" + qs : ""}`);
  },
  getJob: (id: string) => request<JobRecord>(`/ml/jobs/${id}`),
  cancelJob: (id: string) => request<void>(`/ml/jobs/${id}`, { method: "DELETE" }),

  // drift
  driftFull: (code: string, currentVectors: number[][]) =>
    request<DriftFullOut>(`/ml/models/${code}/drift-full`, {
      method: "POST",
      body: JSON.stringify({ current_vectors: currentVectors }),
    }),
  driftAlert: (
    code: string,
    currentVectors: number[][],
    dispatch_min_level = "moderate_drift",
    context: Record<string, unknown> = {}
  ) =>
    request<DriftAlertOut>(`/ml/models/${code}/drift-full/alert`, {
      method: "POST",
      body: JSON.stringify({
        current_vectors: currentVectors,
        dispatch_min_level,
        context,
      }),
    }),
};

// --------------------------------------------------------------------------- types

export interface RecipeSummary {
  id: string;
  category: string;
  subcategory: string;
  binder_type: string;
  product_class: string;
  intended_use: string;
  status: string;
  verification_count: number;
  verification_required: number;
  version: number;
}

export interface SearchResponse {
  items: RecipeSummary[];
  total_count: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface Component {
  name: string;
  cas_number: string;
  function: string;
  mass_percent: number;
  tolerance_percent: number;
  inci_name?: string;
  manufacturer_reference?: string;
  notes?: string;
}

export interface ProcessParams {
  equipment: string;
  rotational_speed_rpm?: number | null;
  peripheral_speed_m_per_s?: number | null;
  temperature_c?: number | null;
  duration_min?: number | null;
}

export interface Stage {
  stage_number: number;
  name: string;
  description: string;
  components: Component[];
  process?: ProcessParams | null;
}

export interface Citation {
  authors: string;
  title: string;
  year: number;
  publisher: string;
  isbn?: string | null;
  doi?: string | null;
  url?: string;
  page_or_formula?: string;
}

export interface RecipeFull extends RecipeSummary {
  finish: string;
  color: string;
  tags: string[];
  stages: Stage[];
  primary_source: Citation;
  cross_references: Citation[];
}

export interface RuleFinding {
  rule_id: string;
  severity: string;
  message: string;
  reference?: string;
}

export interface RegulatoryFinding {
  rule_id: string;
  severity: string;
  substance: string;
  cas_number: string;
  message: string;
  reference?: string;
}

export interface Assessment {
  recipe_id: string;
  maturity: string;
  score: number;
  findings: RuleFinding[];
  verification_violations: { rule: string; message: string }[];
  regulatory_findings: RegulatoryFinding[];
  stoichiometry: {
    detected_system: string;
    reactive_equivalents_per_100g: number;
    co_reactive_equivalents_per_100g: number;
    ratio_reactive_to_co: number | null;
    recommended_ratio_low: number;
    recommended_ratio_high: number;
    is_balanced: boolean;
    findings: { rule_id: string; severity: string; message: string }[];
  } | null;
  summary: Record<string, string | number | boolean | null>;
}

export interface CostRequest {
  prices: Array<{
    component_name: string;
    amount: number;
    currency: string;
    unit: string;
  }>;
}

export interface RecipeCost {
  recipe_id: string;
  currency: string;
  cost_per_kg: number;
  cost_per_litre: number | null;
  priced_fraction: number;
  lines: Array<{
    component_name: string;
    mass_percent: number;
    unit_price_amount: number | null;
    unit_price_currency: string | null;
    unit_price_unit: string | null;
    cost_per_kg_recipe: number | null;
  }>;
  missing_prices: string[];
}

export interface FeatureImpact {
  feature_name: string;
  contribution: number;
  baseline_value: number;
  global_importance: number;
}

export interface Prediction {
  property_code: string;
  predicted_value: number;
  model_version: string;
  model_cv_r2: number;
  unit: string;
  lower_bound?: number | null;
  upper_bound?: number | null;
  interval_alpha?: number | null;
  top_features: FeatureImpact[];
}

export interface PredictionsOut {
  recipe_id: string;
  predictions: Prediction[];
}

export interface CatalogStats {
  total: number;
  by_status: Record<string, number>;
}

export interface ModelMetadata {
  property_code: string;
  version: string;
  n_samples: number;
  n_features: number;
  feature_names: string[];
  cv_mean_r2: number;
  cv_std_r2: number;
  training_recipe_ids: string[];
  algorithm: string;
  fingerprint: string;
  holdout_r2: number | null;
  holdout_mae: number | null;
  holdout_size: number | null;
}

export interface CalibrationMatrixRow {
  property_code: string;
  model_version: string;
  cv_mean_r2: number;
  n_samples: number;
  has_calibration: boolean;
  has_isotonic: boolean;
  has_interval: boolean;
  target_coverage: number | null;
  empirical_coverage: number | null;
  coverage_gap: number | null;
  factor: number | null;
  calibration_n: number | null;
}

export interface CalibrationMatrix {
  rows: CalibrationMatrixRow[];
  n_models: number;
  n_calibrated: number;
  n_under_covered: number;
}

export interface TrainResult {
  trained: ModelMetadata[];
  skipped: Record<string, string>;
}

export interface JobRecord {
  id: string;
  kind: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  metadata: Record<string, unknown>;
  result: unknown;
  error: string | null;
}

export interface DriftReport {
  feature_name: string;
  psi: number;
  ks_statistic: number;
  ks_p_value: number | null;
  level: string;
  n_reference: number;
  n_current: number;
}

export interface DriftFullOut {
  property_code: string;
  reports: DriftReport[];
  worst_level: string;
}

export interface DriftAlertOut extends DriftFullOut {
  alert_dispatched: boolean;
  dispatch_reason: string;
}
