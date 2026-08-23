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
export type AlertConfig = {
  webhook_configured: boolean;
  webhook_url_hint: string;
  webhook_format: string;
  min_severity: string;
};
export type Info = {
  name: string;
  version: string;
  environment: string;
  python: string;
  platform: string;
  git_sha: string;
  build_date: string;
  alert?: AlertConfig | null;
};

export const api = {
  health: () => request<Health>("/health"),
  info: () => request<Info>("/info"),

  // recipes
  listRecipes: (params?: {
    q?: string;
    category?: string[];
    subcategory?: string[];
    product_class?: string[];
    limit?: number;
    offset?: number;
  }) => {
    const q = new URLSearchParams();
    if (params?.q) q.set("q", params.q);
    if (params?.category) params.category.forEach((c) => q.append("category", c));
    if (params?.subcategory)
      params.subcategory.forEach((c) => q.append("subcategory", c));
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
  /** Full facet snapshot for filter dropdowns — every category + count. */
  catalogFacets: () => request<CatalogFacetsOut>("/catalog/facets"),
  /** One-shot dashboard payload (v1.21) — replaces 5 independent GETs. */
  dashboardSummary: () => request<DashboardSummaryOut>("/dashboard/summary"),

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

  // sensitivity
  sensitivity: (id: string, body: SensitivityRequest) =>
    request<SensitivityResult>(`/recipes/${id}/sensitivity`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // Direct URL helpers for downloads — the browser triggers the actual
  // GET so we get the Content-Disposition attachment behaviour.
  recipeCsvUrl: (id: string) => `/api/recipes/${encodeURIComponent(id)}/export.csv`,
  recipePdfUrl: (id: string) => `/api/recipes/${encodeURIComponent(id)}/export.pdf`,
  catalogCsvUrl: () => `/api/catalog/export.csv`,
  catalogPdfUrl: (params?: { category?: string; limit?: number }) => {
    const q = new URLSearchParams();
    if (params?.category) q.set("category", params.category);
    if (params?.limit) q.set("limit", String(params.limit));
    const qs = q.toString();
    return `/api/catalog/export.pdf${qs ? "?" + qs : ""}`;
  },

  // heatmap
  sensitivityHeatmap: (id: string, body: HeatmapRequest) =>
    request<HeatmapResult>(`/recipes/${id}/sensitivity-heatmap`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // versions + diff
  recipeVersions: (id: string) =>
    request<RecipeVersionsOut>(`/recipes/${id}/versions`),
  recipeDiff: (id: string, left: number, right: number) =>
    request<RecipeDiffOut>(`/recipes/${id}/diff?left=${left}&right=${right}`),

  // write
  createRecipe: (body: CreateRecipeBody) =>
    request<RecipeSummary>(`/recipes`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  createNewVersion: (id: string, body: { actor?: string; change_summary?: string }) =>
    request<RecipeSummary>(`/recipes/${id}/new-version`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // users & roles
  me: () => request<MeOut>(`/me`),
  listUsers: () => request<UsersListOut>(`/users`),
  createUser: (body: UserCreateBody) =>
    request<User>(`/users`, { method: "POST", body: JSON.stringify(body) }),
  updateUser: (id: string, body: UserUpdateBody) =>
    request<User>(`/users/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteUser: (id: string) =>
    request<void>(`/users/${id}`, { method: "DELETE" }),

  // session auth (browser login-flow, v1.17)
  login: (body: LoginBody) =>
    request<LoginOut>(`/auth/login`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  logout: () => request<void>(`/auth/logout`, { method: "POST" }),

  // personal API keys (v1.18)
  listApiKeys: (userId: string) =>
    request<ApiKeysListOut>(`/users/${userId}/api-keys`),
  createApiKey: (userId: string, body: ApiKeyCreateBody) =>
    request<ApiKeyIssuedOut>(`/users/${userId}/api-keys`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  revokeApiKey: (userId: string, keyId: string) =>
    request<void>(`/users/${userId}/api-keys/${keyId}`, { method: "DELETE" }),

  // audit log (Admin only, v1.17)
  listAuditLog: (params?: {
    recipe_id?: string;
    actor?: string;
    action?: string;
    limit?: number;
    offset?: number;
  }) => {
    const q = new URLSearchParams();
    if (params?.recipe_id) q.set("recipe_id", params.recipe_id);
    if (params?.actor) q.set("actor", params.actor);
    if (params?.action) q.set("action", params.action);
    if (params?.limit) q.set("limit", String(params.limit));
    if (params?.offset !== undefined) q.set("offset", String(params.offset));
    const qs = q.toString();
    return request<AuditLogPageOut>(`/audit-log${qs ? "?" + qs : ""}`);
  },

  // clone recipe
  cloneRecipe: (id: string) =>
    request<RecipeSummary>(`/recipes/${id}/clone`, { method: "POST" }),

  // regulatory scan
  regulatoryScan: (params?: {
    category?: string;
    min_severity?: "warning" | "error";
    limit?: number;
  }) => {
    const q = new URLSearchParams();
    if (params?.category) q.set("category", params.category);
    if (params?.min_severity) q.set("min_severity", params.min_severity);
    if (params?.limit) q.set("limit", String(params.limit));
    const qs = q.toString();
    return request<RegulatoryScanResult>(
      `/catalog/regulatory-scan${qs ? "?" + qs : ""}`
    );
  },

  // workflow — draft → pending review → verified/rejected
  submitReview: (id: string, body: { actor: string; comment?: string }) =>
    request<RecipeSummary>(`/recipes/${id}/submit-review`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  verifyRecipe: (
    id: string,
    body: { verifier: string; source_citation_id?: string; comment?: string }
  ) =>
    request<RecipeSummary>(`/recipes/${id}/verify`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  rejectRecipe: (id: string, body: { actor: string; reason: string }) =>
    request<RecipeSummary>(`/recipes/${id}/reject`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // production feature vectors (drift telemetry)
  ingestProductionVectors: (items: ProductionVectorIngestItem[]) =>
    request<{ accepted: number; ids: string[]; skipped: Record<string, string> }>(
      `/ml/production-vectors`,
      { method: "POST", body: JSON.stringify({ items }) }
    ),
  listProductionVectors: (params?: { recipe_id?: string; source?: string; limit?: number }) => {
    const q = new URLSearchParams();
    if (params?.recipe_id) q.set("recipe_id", params.recipe_id);
    if (params?.source) q.set("source", params.source);
    if (params?.limit) q.set("limit", String(params.limit));
    const qs = q.toString();
    return request<{
      total: number;
      samples: Array<{
        id: string;
        recipe_id: string;
        recorded_at: string;
        source: string;
        features: number[];
        notes: string;
      }>;
    }>(`/ml/production-vectors${qs ? "?" + qs : ""}`);
  },
  driftFromCatalogSource: (
    code: string,
    params: { limit?: number; source: "catalog" | "production"; category?: string }
  ) => {
    const q = new URLSearchParams();
    q.set("source", params.source);
    if (params.limit) q.set("limit", String(params.limit));
    if (params.category) q.set("category", params.category);
    return request<DriftFullOut>(
      `/ml/models/${code}/drift-from-catalog?${q.toString()}`
    );
  },
  driftAlertTest: (
    code: string,
    body: {
      current_vectors: number[][];
      dispatch_min_level?: string;
      context?: Record<string, string>;
    }
  ) =>
    request<{ property_code: string; worst_level: string; alert_dispatched: boolean; dispatch_reason: string }>(
      `/ml/models/${code}/drift-full/alert`,
      { method: "POST", body: JSON.stringify(body) }
    ),

  // similar recipes
  similarRecipes: (
    id: string,
    params?: { top_k?: number; same_category_only?: boolean; min_similarity?: number }
  ) => {
    const q = new URLSearchParams();
    if (params?.top_k) q.set("top_k", String(params.top_k));
    if (params?.same_category_only !== undefined)
      q.set("same_category_only", String(params.same_category_only));
    if (params?.min_similarity !== undefined)
      q.set("min_similarity", String(params.min_similarity));
    const qs = q.toString();
    return request<SimilarRecipesOut>(
      `/recipes/${id}/similar${qs ? "?" + qs : ""}`
    );
  },

  // pareto + optimiser
  pareto: (recipeId: string, body: ParetoRequest) =>
    request<ParetoResult>(`/recipes/${recipeId}/pareto`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  optimise: (recipeId: string, body: OptimisationRequest) =>
    request<OptimisationResult>(`/recipes/${recipeId}/optimise`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // drift
  driftFromCatalog: (
    code: string,
    params?: { limit?: number; category?: string }
  ) => {
    const q = new URLSearchParams();
    if (params?.limit) q.set("limit", String(params.limit));
    if (params?.category) q.set("category", params.category);
    const qs = q.toString();
    return request<DriftFullOut>(
      `/ml/models/${code}/drift-from-catalog${qs ? "?" + qs : ""}`
    );
  },
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
  /** ``{category → n_recipes}`` — populated since v1.19. */
  by_category?: Record<string, number>;
  /** ``{product_class → n_recipes}`` — populated since v1.19. */
  by_product_class?: Record<string, number>;
}

/** Full facet snapshot for filter dropdowns (``GET /catalog/facets``). */
export interface CatalogFacetsOut {
  total: number;
  by_category: Record<string, number>;
  /** Nested map so the UI can render subcategory scoped to a category. */
  by_subcategory: Record<string, Record<string, number>>;
  by_product_class: Record<string, number>;
  by_status: Record<string, number>;
}

/** Compact recipe row in the dashboard's "recent activity" list. */
export interface RecentRecipeOut {
  id: string;
  category: string;
  subcategory: string;
  status: string;
  product_class: string;
  created_at: string;
}

/** Everything the dashboard renders in one round-trip
 * (``GET /dashboard/summary``, v1.21). */
export interface DashboardSummaryOut {
  version: string;
  environment: string;
  total_recipes: number;
  by_status: Record<string, number>;
  by_category: Record<string, number>;
  by_product_class: Record<string, number>;
  trained_models: number;
  recent_recipes: RecentRecipeOut[];
  recent_audit: AuditLogEntry[];
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

export interface SensitivityRequest {
  component_name: string;
  min_percent: number;
  max_percent: number;
  steps: number;
  property_codes?: string[];
}

export interface SensitivityPoint {
  target_percent: number;
  predictions: Record<string, number | null>;
  skipped: boolean;
  skip_reason: string;
}

export interface SensitivityResult {
  recipe_id: string;
  component_name: string;
  baseline_percent: number;
  min_percent: number;
  max_percent: number;
  steps: number;
  property_codes: string[];
  points: SensitivityPoint[];
}

// ---- 2D heatmap ------------------------------------------------------------
export interface HeatmapRequest {
  component_a: string;
  component_b: string;
  property_code: string;
  a_min: number;
  a_max: number;
  b_min: number;
  b_max: number;
  steps_a?: number;
  steps_b?: number;
}

export interface HeatmapResult {
  recipe_id: string;
  component_a: string;
  component_b: string;
  property_code: string;
  baseline_a: number;
  baseline_b: number;
  baseline_value: number | null;
  a_values: number[];
  b_values: number[];
  values: (number | null)[][];
  z_min: number | null;
  z_max: number | null;
}

export interface SimilarRecipe {
  recipe_id: string;
  category: string;
  subcategory: string;
  binder_type: string;
  product_class: string;
  similarity: number;
}

// ---- Users & roles ---------------------------------------------------------
export interface User {
  id: string;
  username: string;
  email: string | null;
  role: string;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface UsersListOut {
  users: User[];
}

export interface UserCreateBody {
  username: string;
  password: string;
  role: string;
  email?: string;
  is_active?: boolean;
}

export interface UserUpdateBody {
  email?: string | null;
  role?: string;
  is_active?: boolean;
  new_password?: string;
}

export interface MeOut {
  subject: string;
  mode: string;
  scopes: string[];
  role: string | null;
}

// ---- Session auth (browser login-flow) ------------------------------------
export interface LoginBody {
  username: string;
  password: string;
}

export interface LoginOut {
  subject: string;
  role: string;
  scopes: string[];
  expires_at: number;
  mode: string;
}

// ---- Audit log -------------------------------------------------------------
export interface AuditLogEntry {
  id: string;
  /** Nullable since v1.18 — auth events (Login/Logout/ApiKey…) have no recipe. */
  recipe_id: string | null;
  user_id: string | null;
  actor_label: string;
  action: string;
  changes: Record<string, unknown> | null;
  timestamp: string;
  ip_address: string | null;
}

// ---- Personal API keys -----------------------------------------------------
export interface ApiKey {
  id: string;
  user_id: string;
  label: string;
  token_prefix: string;
  created_at: string;
  last_used_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
  is_active: boolean;
}

export interface ApiKeysListOut {
  keys: ApiKey[];
}

export interface ApiKeyCreateBody {
  label: string;
  expires_at?: string | null;
}

/** The plaintext is returned exactly once — persist it or lose it. */
export interface ApiKeyIssuedOut extends ApiKey {
  plaintext: string;
}

export interface AuditLogPageOut {
  total: number;
  limit: number;
  offset: number;
  entries: AuditLogEntry[];
  actions: string[];
}

// ---- Regulatory scan -------------------------------------------------------
export interface RegulatoryScanFinding {
  recipe_id: string;
  category: string;
  subcategory: string;
  status: string;
  total_findings: number;
  errors: number;
  warnings: number;
  top_substances: string[];
}

export interface RegulatoryScanResult {
  n_scanned: number;
  n_offending: number;
  findings: RegulatoryScanFinding[];
}

// ---- Versions + diff -------------------------------------------------------
export interface RecipeVersion {
  id: string;
  version: number;
  status: string;
  verification_count: number;
  verification_required: number;
  created_at: string;
  created_by: string;
}

export interface RecipeVersionsOut {
  recipe_id: string;
  versions: RecipeVersion[];
}

export interface RecipeDiffMetadataChange {
  field: string;
  from_value: string | null;
  to_value: string | null;
}

export interface RecipeDiffComponentChange {
  stage_number: number;
  component_name: string;
  kind: "added" | "removed" | "mass_changed" | "function_changed" | string;
  from_value: string | number | null;
  to_value: string | number | null;
}

export interface RecipeDiffOut {
  recipe_id: string;
  left_version: number;
  right_version: number;
  metadata_changes: RecipeDiffMetadataChange[];
  component_changes: RecipeDiffComponentChange[];
  identical: boolean;
}

// ---- Recipe create/edit payloads (subset mirrored from schemas.py) ---------
export interface ComponentIn {
  name: string;
  cas_number: string;
  function: string;
  mass_percent: number;
  tolerance_percent?: number;
  manufacturer_reference?: string;
}

export interface StageIn {
  stage_number: number;
  name: string;
  description?: string;
  components: ComponentIn[];
  process?: {
    equipment: string;
    rotational_speed_rpm?: number | null;
    temperature_c?: number | null;
    duration_min?: number | null;
  } | null;
}

export interface CitationInBody {
  authors: string;
  title: string;
  year: number;
  publisher: string;
  isbn?: string | null;
  doi?: string | null;
  url?: string | null;
  page_or_formula?: string;
}

export interface ProductionVectorIngestItem {
  recipe_id: string;
  features?: number[];
  source?: string;
  notes?: string;
}

export interface CreateRecipeBody {
  id?: string | null;
  category: string;
  subcategory: string;
  binder_type: string;
  product_class: string;
  intended_use: string;
  finish?: string;
  color?: string;
  tags?: string[];
  stages: StageIn[];
  primary_source: CitationInBody;
  cross_references?: CitationInBody[];
}

export interface SimilarRecipesOut {
  reference_recipe_id: string;
  same_category_only: boolean;
  matches: SimilarRecipe[];
}

// ---- Pareto / optimiser ----------------------------------------------------
export interface PropertyTarget {
  property_code: string;
  target_value: number;
  tolerance?: number;
  direction?: "match" | "minimise" | "maximise";
  weight?: number;
}

export interface ComponentBounds {
  component_name: string;
  min_percent: number;
  max_percent: number;
}

export interface ParetoRequest {
  targets: PropertyTarget[];
  bounds?: ComponentBounds[];
  population_size?: number;
  generations?: number;
  mutation_std?: number;
  seed?: number | null;
}

export interface ParetoPoint {
  mass_percent: Record<string, number>;
  objectives: Record<string, number>;
  rank: number;
  crowding_distance: number;
}

export interface ParetoResult {
  base_recipe_id: string;
  front: ParetoPoint[];
  generations: number;
}

export interface OptimisationRequest {
  targets: PropertyTarget[];
  bounds?: ComponentBounds[];
  max_iterations?: number;
  population_size?: number;
  seed?: number | null;
}

export interface OptimisationResult {
  base_recipe_id: string;
  optimised_mass_percent: Record<string, number>;
  predicted_values: Record<string, number>;
  final_loss: number;
  converged: boolean;
  iterations_used: number;
  notes?: string[];
}
