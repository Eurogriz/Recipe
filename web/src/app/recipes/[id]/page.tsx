"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  Beaker,
  ClipboardCheck,
  DollarSign,
  Download,
  LineChart,
  Network,
  Plus,
  Sliders,
  Target,
  Trash2,
} from "lucide-react";
import {
  api,
  type Assessment,
  type ModelMetadata,
  type OptimisationResult,
  type ParetoResult,
  type PredictionsOut,
  type PropertyTarget,
  type RecipeCost,
  type RecipeFull,
  type SensitivityResult,
  type SimilarRecipesOut,
} from "@/lib/api";
import { fmt } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TBody, THead, TH, TR, TD } from "@/components/ui/table";
import { useT } from "@/i18n/I18nProvider";

type Tab =
  | "composition"
  | "assessment"
  | "predict"
  | "cost"
  | "optimise"
  | "similar"
  | "sensitivity";

export default function RecipeDetailPage() {
  const t = useT();
  const params = useParams<{ id: string }>();
  const id = decodeURIComponent(params.id);
  const [recipe, setRecipe] = useState<RecipeFull | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("composition");

  useEffect(() => {
    api.getRecipeFull(id).then(setRecipe).catch((e) => setError(e.message ?? String(e)));
  }, [id]);

  if (error) {
    return (
      <div className="p-8">
        <div className="rounded-md border border-destructive/30 bg-red-50 text-red-900 px-4 py-3 text-sm">
          {error}
        </div>
      </div>
    );
  }
  if (!recipe) return <div className="p-8 text-muted-foreground">{t("common.loading")}</div>;

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <Link
          href="/recipes"
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" /> {t("recipe.back")}
        </Link>
        <a
          href={api.recipeCsvUrl(id)}
          className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
          download
        >
          <Download className="h-4 w-4" /> {t("recipe.export.csv")}
        </a>
      </div>

      <header className="space-y-2">
        <div className="flex items-center gap-2 flex-wrap">
          <h1 className="text-2xl font-semibold tracking-tight">
            {recipe.subcategory || recipe.id}
          </h1>
          <Badge variant="outline">{recipe.category}</Badge>
          <Badge variant="info">{recipe.product_class}</Badge>
          <Badge variant={recipe.status === "Verified" ? "success" : "warning"}>
            {recipe.status}{" "}
            ({t("recipe.status.of", {
              done: recipe.verification_count,
              required: recipe.verification_required,
            })})
          </Badge>
        </div>
        <p className="text-muted-foreground">{recipe.intended_use || "—"}</p>
        <div className="text-xs text-muted-foreground">
          <span className="font-mono">{recipe.id}</span> · {t("recipe.version", { n: recipe.version })} ·{" "}
          {t("recipe.binder")}: {recipe.binder_type || "—"} · {t("recipe.finish")}:{" "}
          {recipe.finish || "—"} · {t("recipe.color")}: {recipe.color || "—"}
        </div>
        {recipe.tags?.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {recipe.tags.map((tag) => (
              <Badge key={tag} variant="outline">
                {tag}
              </Badge>
            ))}
          </div>
        )}
      </header>

      <div className="flex gap-2 border-b border-border overflow-x-auto">
        <TabButton
          current={tab}
          v="composition"
          onClick={setTab}
          icon={<Beaker className="h-4 w-4" />}
        >
          {t("recipe.tab.composition")}
        </TabButton>
        <TabButton
          current={tab}
          v="assessment"
          onClick={setTab}
          icon={<ClipboardCheck className="h-4 w-4" />}
        >
          {t("recipe.tab.assessment")}
        </TabButton>
        <TabButton
          current={tab}
          v="predict"
          onClick={setTab}
          icon={<LineChart className="h-4 w-4" />}
        >
          {t("recipe.tab.predict")}
        </TabButton>
        <TabButton
          current={tab}
          v="cost"
          onClick={setTab}
          icon={<DollarSign className="h-4 w-4" />}
        >
          {t("recipe.tab.cost")}
        </TabButton>
        <TabButton
          current={tab}
          v="optimise"
          onClick={setTab}
          icon={<Target className="h-4 w-4" />}
        >
          {t("recipe.tab.optimise")}
        </TabButton>
        <TabButton
          current={tab}
          v="similar"
          onClick={setTab}
          icon={<Network className="h-4 w-4" />}
        >
          {t("recipe.tab.similar")}
        </TabButton>
        <TabButton
          current={tab}
          v="sensitivity"
          onClick={setTab}
          icon={<Sliders className="h-4 w-4" />}
        >
          {t("recipe.tab.sensitivity")}
        </TabButton>
      </div>

      {tab === "composition" && <CompositionTab recipe={recipe} />}
      {tab === "assessment" && <AssessmentTab id={id} />}
      {tab === "predict" && <PredictTab id={id} />}
      {tab === "cost" && <CostTab recipe={recipe} />}
      {tab === "optimise" && <OptimiseTab id={id} />}
      {tab === "similar" && <SimilarTab id={id} />}
      {tab === "sensitivity" && <SensitivityTab recipe={recipe} />}
    </div>
  );
}

function TabButton({
  v,
  current,
  onClick,
  children,
  icon,
}: {
  v: Tab;
  current: Tab;
  onClick: (t: Tab) => void;
  children: React.ReactNode;
  icon: React.ReactNode;
}) {
  const active = v === current;
  return (
    <button
      onClick={() => onClick(v)}
      className={`inline-flex items-center gap-2 px-3 py-2 text-sm border-b-2 -mb-px transition-colors whitespace-nowrap ${
        active
          ? "border-primary text-primary font-medium"
          : "border-transparent text-muted-foreground hover:text-foreground"
      }`}
    >
      {icon}
      {children}
    </button>
  );
}

/* ------------------------------------------------------------- Composition */
function CompositionTab({ recipe }: { recipe: RecipeFull }) {
  const t = useT();
  return (
    <div className="space-y-6">
      {recipe.stages.map((s) => {
        const total = s.components.reduce((a, c) => a + c.mass_percent, 0);
        return (
          <Card key={s.stage_number}>
            <CardHeader>
              <CardTitle>
                {t("recipe.comp.stage", { n: s.stage_number, name: s.name })}
              </CardTitle>
              {s.description && (
                <p className="text-sm text-muted-foreground">{s.description}</p>
              )}
              {s.process && (
                <p className="text-xs text-muted-foreground pt-1">
                  {t("recipe.comp.equipment")}: {s.process.equipment}
                  {s.process.rotational_speed_rpm
                    ? ` · ${s.process.rotational_speed_rpm} rpm`
                    : ""}
                  {s.process.temperature_c != null ? ` · ${s.process.temperature_c}°C` : ""}
                  {s.process.duration_min != null ? ` · ${s.process.duration_min} min` : ""}
                </p>
              )}
            </CardHeader>
            <CardContent>
              <Table>
                <THead>
                  <TR>
                    <TH>{t("recipe.comp.col.name")}</TH>
                    <TH>{t("recipe.comp.col.cas")}</TH>
                    <TH>{t("recipe.comp.col.function")}</TH>
                    <TH className="text-right">{t("recipe.comp.col.mass")}</TH>
                    <TH className="text-right">{t("recipe.comp.col.tol")}</TH>
                  </TR>
                </THead>
                <TBody>
                  {s.components.map((c) => (
                    <TR key={c.name + c.cas_number}>
                      <TD className="font-medium">{c.name}</TD>
                      <TD className="font-mono text-xs">{c.cas_number}</TD>
                      <TD>
                        <Badge variant="outline">{c.function}</Badge>
                      </TD>
                      <TD className="text-right font-mono">{fmt(c.mass_percent, 3)}</TD>
                      <TD className="text-right font-mono text-muted-foreground">
                        {fmt(c.tolerance_percent, 2)}
                      </TD>
                    </TR>
                  ))}
                  <TR>
                    <TD colSpan={3} className="text-right font-medium">
                      {t("recipe.comp.total")}
                    </TD>
                    <TD className="text-right font-mono font-semibold">
                      {fmt(total, 3)} %
                    </TD>
                    <TD />
                  </TR>
                </TBody>
              </Table>
            </CardContent>
          </Card>
        );
      })}

      <Card>
        <CardHeader>
          <CardTitle>{t("recipe.comp.primary_source")}</CardTitle>
        </CardHeader>
        <CardContent className="text-sm space-y-1">
          <div>{recipe.primary_source.authors}</div>
          <div className="italic">{recipe.primary_source.title}</div>
          <div className="text-muted-foreground">
            {recipe.primary_source.publisher}, {recipe.primary_source.year}
            {recipe.primary_source.isbn ? ` · ISBN ${recipe.primary_source.isbn}` : ""}
          </div>
          {recipe.primary_source.page_or_formula && (
            <div className="text-xs text-muted-foreground pt-1">
              {recipe.primary_source.page_or_formula}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

/* ------------------------------------------------------------- Assessment */
function AssessmentTab({ id }: { id: string }) {
  const t = useT();
  const [data, setData] = useState<Assessment | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.assessRecipe(id).then(setData).catch((e) => setErr(e.message ?? String(e)));
  }, [id]);

  if (err) return <div className="text-sm text-red-700">{err}</div>;
  if (!data)
    return <div className="text-sm text-muted-foreground">{t("assessment.assessing")}</div>;

  const errors = data.findings.filter((f) => f.severity === "error").length;
  const warnings = data.findings.filter((f) => f.severity === "warning").length;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card>
          <CardContent className="p-5">
            <div className="text-xs uppercase tracking-wide text-muted-foreground">
              {t("assessment.card.score")}
            </div>
            <div className="text-3xl font-semibold mt-1">{data.score.toFixed(1)}</div>
            <div className="text-xs text-muted-foreground mt-1">
              {t("assessment.card.score_hint")}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-5">
            <div className="text-xs uppercase tracking-wide text-muted-foreground">
              {t("assessment.card.maturity")}
            </div>
            <div className="text-2xl font-semibold mt-1">{data.maturity}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-5">
            <div className="text-xs uppercase tracking-wide text-muted-foreground">
              {t("assessment.card.findings")}
            </div>
            <div className="text-2xl font-semibold mt-1">
              {data.findings.length + data.regulatory_findings.length}
            </div>
            <div className="text-xs text-muted-foreground mt-1">
              {t("assessment.card.findings_hint", { errors, warnings })}
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{t("assessment.technological.title")}</CardTitle>
        </CardHeader>
        <CardContent>
          {data.findings.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {t("assessment.technological.clean")}
            </p>
          ) : (
            <ul className="space-y-2">
              {data.findings.map((f, i) => (
                <li
                  key={i}
                  className="flex items-start gap-3 border border-border rounded-md p-3"
                >
                  <SeverityBadge severity={f.severity} />
                  <div className="flex-1">
                    <div className="text-sm">{f.message}</div>
                    <div className="text-xs text-muted-foreground font-mono mt-1">
                      {f.rule_id}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      {data.regulatory_findings.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>{t("assessment.regulatory.title")}</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2">
              {data.regulatory_findings.map((f, i) => (
                <li
                  key={i}
                  className="flex items-start gap-3 border border-border rounded-md p-3"
                >
                  <SeverityBadge severity={f.severity} />
                  <div className="flex-1">
                    <div className="text-sm">
                      <b>{f.substance}</b> ({f.cas_number}): {f.message}
                    </div>
                    <div className="text-xs text-muted-foreground font-mono mt-1">
                      {f.rule_id}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      {data.stoichiometry && (
        <Card>
          <CardHeader>
            <CardTitle>
              {t("assessment.stoichiometry.title", {
                system: data.stoichiometry.detected_system,
              })}
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm grid grid-cols-1 md:grid-cols-2 gap-2">
            <div>
              {t("assessment.stoichiometry.reactive")}:{" "}
              <b>{fmt(data.stoichiometry.reactive_equivalents_per_100g, 4)}</b>
            </div>
            <div>
              {t("assessment.stoichiometry.co_reactive")}:{" "}
              <b>{fmt(data.stoichiometry.co_reactive_equivalents_per_100g, 4)}</b>
            </div>
            <div>
              {t("assessment.stoichiometry.ratio")}:{" "}
              <b>{fmt(data.stoichiometry.ratio_reactive_to_co, 3)}</b>
              &nbsp;(
              {t("assessment.stoichiometry.target", {
                low: data.stoichiometry.recommended_ratio_low,
                high: data.stoichiometry.recommended_ratio_high,
              })}
              )
            </div>
            <div>
              {t("assessment.stoichiometry.balanced")}:{" "}
              <Badge variant={data.stoichiometry.is_balanced ? "success" : "warning"}>
                {data.stoichiometry.is_balanced ? t("common.yes") : t("common.no")}
              </Badge>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function SeverityBadge({ severity }: { severity: string }) {
  const v =
    severity === "error"
      ? "destructive"
      : severity === "warning"
        ? "warning"
        : severity === "info"
          ? "info"
          : "outline";
  return <Badge variant={v}>{severity}</Badge>;
}

/**
 * Renders `predict.no_models` splitting on the {link} placeholder so we
 * can substitute an actual <Link> without HTML-encoded interpolation.
 */
function NoModelsMessage() {
  const t = useT();
  const raw = t("predict.no_models", { link: "__LINK__" });
  const parts = raw.split("__LINK__");
  return (
    <>
      {parts[0]}
      <Link href="/ml" className="underline">
        {t("predict.link.ml_page")}
      </Link>
      {parts[1] ?? ""}
    </>
  );
}

/* ------------------------------------------------------------- Predict */
function PredictTab({ id }: { id: string }) {
  const t = useT();
  const [data, setData] = useState<PredictionsOut | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api
      .predictRecipe(id, 3)
      .then(setData)
      .catch((e) => setErr(e.message ?? String(e)))
      .finally(() => setLoading(false));
  }, [id]);

  if (loading)
    return <div className="text-sm text-muted-foreground">{t("predict.running")}</div>;
  if (err) {
    return (
      <div className="rounded-md border border-amber-300 bg-amber-50 text-amber-900 px-4 py-3 text-sm space-y-2">
        <div>{t("predict.failed", { msg: err })}</div>
        <div className="text-xs">
          <NoModelsMessage />
        </div>
      </div>
    );
  }
  if (!data || data.predictions.length === 0) {
    return (
      <div className="text-sm text-muted-foreground">
        <NoModelsMessage />
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {data.predictions.map((p) => (
        <Card key={p.property_code}>
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              <span>{p.property_code}</span>
              <Badge variant="outline">R² {p.model_cv_r2.toFixed(3)}</Badge>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-baseline gap-2">
              <span className="text-3xl font-semibold">{fmt(p.predicted_value, 2)}</span>
              <span className="text-sm text-muted-foreground">{p.unit || ""}</span>
            </div>
            {p.lower_bound != null && p.upper_bound != null && (
              <div className="text-xs text-muted-foreground mt-1">
                {t("predict.interval", {
                  low: fmt(p.lower_bound, 2),
                  high: fmt(p.upper_bound, 2),
                })}
              </div>
            )}
            <div className="text-xs text-muted-foreground mt-1">
              {t("predict.model_version", { version: p.model_version })}
            </div>
            {p.top_features.length > 0 && (
              <div className="mt-4">
                <div className="text-xs uppercase tracking-wide text-muted-foreground mb-2">
                  {t("predict.top_features")}
                </div>
                <ul className="space-y-1">
                  {p.top_features.map((fi) => {
                    const positive = fi.contribution >= 0;
                    return (
                      <li
                        key={fi.feature_name}
                        className="flex items-center gap-2 text-xs"
                      >
                        <div className="w-32 truncate font-mono">{fi.feature_name}</div>
                        <div className="flex-1 h-2 bg-muted rounded overflow-hidden">
                          <div
                            className={
                              positive ? "h-full bg-emerald-500" : "h-full bg-red-500"
                            }
                            style={{
                              width: `${Math.min(100, Math.abs(fi.contribution) * 100)}%`,
                            }}
                          />
                        </div>
                        <div className="w-14 text-right font-mono">
                          {fi.contribution >= 0 ? "+" : ""}
                          {fmt(fi.contribution, 3)}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </div>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------- Cost */
function CostTab({ recipe }: { recipe: RecipeFull }) {
  const t = useT();
  const [prices, setPrices] = useState<Record<string, string>>({});
  const [data, setData] = useState<RecipeCost | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const defaults: Record<string, string> = {};
    recipe.stages.forEach((s) =>
      s.components.forEach((c) => {
        defaults[c.name] = defaultPrice(c.function);
      })
    );
    setPrices(defaults);
  }, [recipe]);

  const compute = () => {
    setLoading(true);
    setErr(null);
    const body = {
      prices: Object.entries(prices)
        .filter(([, v]) => v && !Number.isNaN(Number(v)))
        .map(([component_name, v]) => ({
          component_name,
          amount: Number(v),
          currency: "EUR",
          unit: "kg" as const,
        })),
    };
    api
      .costRecipe(recipe.id, body)
      .then(setData)
      .catch((e) => setErr(e.message ?? String(e)))
      .finally(() => setLoading(false));
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <Card className="lg:col-span-2">
        <CardHeader>
          <CardTitle>{t("cost.prices.title")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {recipe.stages.flatMap((s) =>
            s.components.map((c) => (
              <div key={c.name} className="flex items-center gap-3">
                <div className="w-56 truncate text-sm">{c.name}</div>
                <div className="w-24 text-xs text-muted-foreground text-right font-mono">
                  {fmt(c.mass_percent, 2)}%
                </div>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  value={prices[c.name] ?? ""}
                  onChange={(e) =>
                    setPrices((p) => ({ ...p, [c.name]: e.target.value }))
                  }
                  className="h-8 w-28 rounded-md border border-input bg-white px-2 text-sm font-mono"
                />
              </div>
            ))
          )}
          <div className="pt-2">
            <Button onClick={compute} disabled={loading}>
              {loading ? t("cost.computing") : t("cost.compute")}
            </Button>
          </div>
          {err && <div className="text-sm text-red-700">{err}</div>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("cost.result.title")}</CardTitle>
        </CardHeader>
        <CardContent>
          {!data ? (
            <p className="text-sm text-muted-foreground">{t("cost.result.hint")}</p>
          ) : (
            <div className="space-y-2 text-sm">
              <div className="text-xs uppercase text-muted-foreground">
                {t("cost.result.per_kg")}
              </div>
              <div className="text-3xl font-semibold">
                {fmt(data.cost_per_kg, 3)} {data.currency}
              </div>
              {data.cost_per_litre != null && (
                <div className="text-xs text-muted-foreground">
                  {t("cost.result.per_litre", {
                    v: fmt(data.cost_per_litre, 3),
                    c: data.currency,
                  })}
                </div>
              )}
              <div className="text-xs text-muted-foreground pt-2">
                {t("cost.result.priced_fraction", {
                  p: (data.priced_fraction * 100).toFixed(1),
                })}
              </div>
              {data.missing_prices.length > 0 && (
                <div className="text-xs text-amber-700 pt-2">
                  {t("cost.result.missing_prices", { n: data.missing_prices.length })}
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

/* ------------------------------------------------------------- Optimise */
interface EditableTarget extends PropertyTarget {
  _key: string;
}

function OptimiseTab({ id }: { id: string }) {
  const t = useT();
  const [models, setModels] = useState<ModelMetadata[] | null>(null);
  const [targets, setTargets] = useState<EditableTarget[]>([]);
  const [singleResult, setSingleResult] = useState<OptimisationResult | null>(null);
  const [paretoResult, setParetoResult] = useState<ParetoResult | null>(null);
  const [busy, setBusy] = useState<null | "single" | "pareto">(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api
      .listModels()
      .then((ms) => {
        setModels(ms);
        // Seed 2 default targets if models are trained.
        if (ms.length >= 2 && targets.length === 0) {
          const g = ms.find((m) => m.property_code === "gloss_60") ?? ms[0];
          const v = ms.find((m) => m.property_code === "voc_content") ?? ms[1];
          setTargets([
            {
              _key: crypto.randomUUID(),
              property_code: g.property_code,
              target_value: 60,
              direction: "maximise",
              weight: 1,
              tolerance: 5,
            },
            {
              _key: crypto.randomUUID(),
              property_code: v.property_code,
              target_value: 0,
              direction: "minimise",
              weight: 1,
              tolerance: 5,
            },
          ]);
        }
      })
      .catch(() => setModels([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const addTarget = () => {
    if (!models || models.length === 0) return;
    setTargets((ts) => [
      ...ts,
      {
        _key: crypto.randomUUID(),
        property_code: models[0].property_code,
        target_value: 50,
        direction: "match",
        weight: 1,
        tolerance: 5,
      },
    ]);
  };
  const removeTarget = (key: string) =>
    setTargets((ts) => ts.filter((x) => x._key !== key));
  const updateTarget = (key: string, patch: Partial<PropertyTarget>) =>
    setTargets((ts) => ts.map((x) => (x._key === key ? { ...x, ...patch } : x)));

  const runSingle = async () => {
    if (targets.length === 0) {
      setErr(t("optimise.no_targets"));
      return;
    }
    setBusy("single");
    setErr(null);
    setSingleResult(null);
    setParetoResult(null);
    try {
      const r = await api.optimise(id, {
        targets: targets.map(({ _key, ...rest }) => rest),
        max_iterations: 15,
        population_size: 10,
        seed: 42,
      });
      setSingleResult(r);
    } catch (e: any) {
      setErr(t("optimise.failed", { msg: e.message ?? String(e) }));
    } finally {
      setBusy(null);
    }
  };

  const runPareto = async () => {
    if (targets.length < 2) {
      setErr(t("optimise.no_targets"));
      return;
    }
    setBusy("pareto");
    setErr(null);
    setSingleResult(null);
    setParetoResult(null);
    try {
      const r = await api.pareto(id, {
        targets: targets.map(({ _key, ...rest }) => rest),
        population_size: 20,
        generations: 15,
        seed: 42,
      });
      setParetoResult(r);
    } catch (e: any) {
      setErr(t("optimise.failed", { msg: e.message ?? String(e) }));
    } finally {
      setBusy(null);
    }
  };

  if (!models) return <div className="text-sm text-muted-foreground">{t("common.loading")}</div>;
  if (models.length === 0) {
    return (
      <div className="text-sm text-muted-foreground">
        <NoModelsMessage />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>{t("optimise.title")}</CardTitle>
          <p className="text-sm text-muted-foreground">{t("optimise.subtitle")}</p>
        </CardHeader>
        <CardContent className="space-y-3">
          {targets.map((tgt) => (
            <div
              key={tgt._key}
              className="grid grid-cols-1 md:grid-cols-6 gap-2 items-center border border-border rounded-md p-3"
            >
              <div className="md:col-span-2">
                <label className="text-xs text-muted-foreground">{t("optimise.property")}</label>
                <select
                  className="w-full h-9 rounded-md border border-input px-2 text-sm bg-white"
                  value={tgt.property_code}
                  onChange={(e) => updateTarget(tgt._key, { property_code: e.target.value })}
                >
                  {models.map((m) => (
                    <option key={m.property_code} value={m.property_code}>
                      {m.property_code}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-xs text-muted-foreground">{t("optimise.target_value")}</label>
                <input
                  type="number"
                  className="w-full h-9 rounded-md border border-input px-2 text-sm bg-white font-mono"
                  value={tgt.target_value}
                  onChange={(e) =>
                    updateTarget(tgt._key, { target_value: Number(e.target.value) })
                  }
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground">{t("optimise.tolerance")}</label>
                <input
                  type="number"
                  className="w-full h-9 rounded-md border border-input px-2 text-sm bg-white font-mono"
                  value={tgt.tolerance ?? 0}
                  onChange={(e) => updateTarget(tgt._key, { tolerance: Number(e.target.value) })}
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground">{t("optimise.direction")}</label>
                <select
                  className="w-full h-9 rounded-md border border-input px-2 text-sm bg-white"
                  value={tgt.direction ?? "match"}
                  onChange={(e) =>
                    updateTarget(tgt._key, {
                      direction: e.target.value as PropertyTarget["direction"],
                    })
                  }
                >
                  <option value="match">{t("optimise.direction.match")}</option>
                  <option value="minimise">{t("optimise.direction.minimise")}</option>
                  <option value="maximise">{t("optimise.direction.maximise")}</option>
                </select>
              </div>
              <div className="flex items-end justify-end">
                <Button variant="ghost" size="sm" onClick={() => removeTarget(tgt._key)}>
                  <Trash2 className="h-4 w-4" /> {t("optimise.remove")}
                </Button>
              </div>
            </div>
          ))}
          <div className="flex flex-wrap gap-2 pt-2">
            <Button variant="outline" onClick={addTarget}>
              <Plus className="h-4 w-4" /> {t("optimise.add_target")}
            </Button>
            <Button onClick={runSingle} disabled={busy !== null || targets.length === 0}>
              {busy === "single" ? t("optimise.running") : t("optimise.run_single")}
            </Button>
            <Button
              variant="secondary"
              onClick={runPareto}
              disabled={busy !== null || targets.length < 2}
            >
              {busy === "pareto" ? t("optimise.running") : t("optimise.run_pareto")}
            </Button>
          </div>
          {err && <div className="text-sm text-red-700">{err}</div>}
        </CardContent>
      </Card>

      {singleResult && <OptimisationResultCard result={singleResult} />}
      {paretoResult && <ParetoResultCard result={paretoResult} />}
    </div>
  );
}

function OptimisationResultCard({ result }: { result: OptimisationResult }) {
  const t = useT();
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("optimise.result.title")}</CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div>
          <div className="grid grid-cols-3 gap-3 mb-4">
            <MiniStat label={t("optimise.result.loss")} value={fmt(result.final_loss, 4)} />
            <MiniStat label={t("optimise.result.iterations")} value={String(result.iterations_used)} />
            <MiniStat
              label={t("optimise.result.converged")}
              value={result.converged ? t("common.yes") : t("common.no")}
              variant={result.converged ? "success" : "warning"}
            />
          </div>
          <div className="text-xs uppercase text-muted-foreground mb-2">
            {t("optimise.result.predicted")}
          </div>
          <ul className="space-y-1 text-sm">
            {Object.entries(result.predicted_values).map(([k, v]) => (
              <li key={k} className="flex justify-between border-b border-border/60 py-1">
                <span className="font-mono text-xs">{k}</span>
                <span className="font-mono">{fmt(v, 2)}</span>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <div className="text-xs uppercase text-muted-foreground mb-2">
            {t("optimise.result.composition")}
          </div>
          <ul className="space-y-1 text-sm max-h-96 overflow-auto">
            {Object.entries(result.optimised_mass_percent)
              .sort((a, b) => b[1] - a[1])
              .map(([k, v]) => (
                <li key={k} className="flex justify-between border-b border-border/60 py-1">
                  <span className="truncate pr-2">{k}</span>
                  <span className="font-mono">{fmt(v, 3)} %</span>
                </li>
              ))}
          </ul>
        </div>
      </CardContent>
    </Card>
  );
}

function ParetoResultCard({ result }: { result: ParetoResult }) {
  const t = useT();
  if (result.front.length === 0) {
    return (
      <Card>
        <CardContent className="p-6 text-sm text-muted-foreground">
          {t("optimise.pareto.no_front")}
        </CardContent>
      </Card>
    );
  }
  const objKeys = Object.keys(result.front[0].objectives);
  // We plot a 2D scatter of the first two objectives.
  const xKey = objKeys[0];
  const yKey = objKeys[1] ?? objKeys[0];
  const xs = result.front.map((p) => p.objectives[xKey]);
  const ys = result.front.map((p) => p.objectives[yKey]);
  const xMin = Math.min(...xs);
  const xMax = Math.max(...xs);
  const yMin = Math.min(...ys);
  const yMax = Math.max(...ys);
  const W = 560;
  const H = 320;
  const M = 40;
  const nx = (x: number) => M + ((x - xMin) / Math.max(1e-9, xMax - xMin)) * (W - 2 * M);
  const ny = (y: number) => H - M - ((y - yMin) / Math.max(1e-9, yMax - yMin)) * (H - 2 * M);

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("optimise.pareto.title")}</CardTitle>
        <p className="text-sm text-muted-foreground">
          {t("optimise.pareto.subtitle", {
            n: result.front.length,
            gen: result.generations,
          })}
        </p>
      </CardHeader>
      <CardContent>
        <svg width={W} height={H} className="mx-auto block max-w-full">
          {/* axes */}
          <line x1={M} y1={H - M} x2={W - M} y2={H - M} stroke="hsl(215 16% 65%)" />
          <line x1={M} y1={M} x2={M} y2={H - M} stroke="hsl(215 16% 65%)" />
          <text x={W / 2} y={H - 8} textAnchor="middle" className="text-xs" fill="hsl(215 16% 47%)">
            {xKey}
          </text>
          <text
            x={12}
            y={H / 2}
            transform={`rotate(-90, 12, ${H / 2})`}
            textAnchor="middle"
            className="text-xs"
            fill="hsl(215 16% 47%)"
          >
            {yKey}
          </text>
          {/* min / max labels */}
          <text x={M} y={H - M + 16} className="text-[10px]" fill="hsl(215 16% 47%)">
            {fmt(xMin, 2)}
          </text>
          <text
            x={W - M}
            y={H - M + 16}
            textAnchor="end"
            className="text-[10px]"
            fill="hsl(215 16% 47%)"
          >
            {fmt(xMax, 2)}
          </text>
          <text x={M - 6} y={H - M} textAnchor="end" className="text-[10px]" fill="hsl(215 16% 47%)">
            {fmt(yMin, 2)}
          </text>
          <text x={M - 6} y={M + 4} textAnchor="end" className="text-[10px]" fill="hsl(215 16% 47%)">
            {fmt(yMax, 2)}
          </text>
          {/* points */}
          {result.front.map((p, i) => (
            <circle
              key={i}
              cx={nx(p.objectives[xKey])}
              cy={ny(p.objectives[yKey])}
              r={5}
              fill="hsl(221 83% 53%)"
              fillOpacity={0.7}
              stroke="hsl(221 83% 33%)"
            >
              <title>
                {`${xKey}=${fmt(p.objectives[xKey], 3)}, ${yKey}=${fmt(
                  p.objectives[yKey],
                  3
                )}`}
              </title>
            </circle>
          ))}
        </svg>
      </CardContent>
    </Card>
  );
}

function MiniStat({
  label,
  value,
  variant,
}: {
  label: string;
  value: string;
  variant?: "success" | "warning";
}) {
  const color =
    variant === "success"
      ? "text-green-700"
      : variant === "warning"
        ? "text-amber-700"
        : "text-foreground";
  return (
    <div className="border border-border rounded-md p-2">
      <div className="text-[10px] uppercase text-muted-foreground">{label}</div>
      <div className={`text-lg font-semibold ${color}`}>{value}</div>
    </div>
  );
}

/* ------------------------------------------------------------- Similar */
function SimilarTab({ id }: { id: string }) {
  const t = useT();
  const [data, setData] = useState<SimilarRecipesOut | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [topK, setTopK] = useState(10);
  const [sameCategory, setSameCategory] = useState(true);
  const [minSim, setMinSim] = useState(0);

  const load = () => {
    setLoading(true);
    setErr(null);
    api
      .similarRecipes(id, {
        top_k: topK,
        same_category_only: sameCategory,
        min_similarity: minSim,
      })
      .then(setData)
      .catch((e) => setErr(e.message ?? String(e)))
      .finally(() => setLoading(false));
  };

  useEffect(load, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>{t("similar.title")}</CardTitle>
          <p className="text-sm text-muted-foreground">{t("similar.subtitle")}</p>
        </CardHeader>
        <CardContent className="grid grid-cols-1 md:grid-cols-4 gap-3 items-end">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={sameCategory}
              onChange={(e) => setSameCategory(e.target.checked)}
            />
            {t("similar.same_category")}
          </label>
          <div>
            <label className="text-xs text-muted-foreground">{t("similar.top_k")}</label>
            <input
              type="number"
              min={1}
              max={50}
              value={topK}
              onChange={(e) => setTopK(Number(e.target.value) || 5)}
              className="w-full h-9 rounded-md border border-input px-2 text-sm font-mono bg-white"
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">{t("similar.min_sim")}</label>
            <input
              type="number"
              step="0.01"
              min={-1}
              max={1}
              value={minSim}
              onChange={(e) => setMinSim(Number(e.target.value))}
              className="w-full h-9 rounded-md border border-input px-2 text-sm font-mono bg-white"
            />
          </div>
          <Button onClick={load} disabled={loading}>
            {loading ? t("similar.loading") : t("common.search")}
          </Button>
        </CardContent>
      </Card>

      {err && (
        <div className="rounded-md border border-destructive/30 bg-red-50 text-red-900 px-4 py-3 text-sm">
          {t("similar.failed", { msg: err })}
        </div>
      )}

      {data && (
        <Card>
          <CardContent className="p-0">
            {data.matches.length === 0 ? (
              <div className="text-sm text-muted-foreground text-center py-6">
                {t("similar.empty")}
              </div>
            ) : (
              <Table>
                <THead>
                  <TR>
                    <TH>{t("similar.col.subcategory")}</TH>
                    <TH>{t("similar.col.binder")}</TH>
                    <TH>{t("similar.col.class")}</TH>
                    <TH className="text-right">{t("similar.col.similarity")}</TH>
                  </TR>
                </THead>
                <TBody>
                  {data.matches.map((m) => (
                    <TR key={m.recipe_id} className="cursor-pointer">
                      <TD>
                        <Link
                          href={`/recipes/${encodeURIComponent(m.recipe_id)}`}
                          className="text-primary hover:underline"
                        >
                          {m.subcategory || m.recipe_id}
                        </Link>
                      </TD>
                      <TD className="text-xs">{m.binder_type || "—"}</TD>
                      <TD>
                        <Badge variant="outline">{m.product_class}</Badge>
                      </TD>
                      <TD className="text-right">
                        <SimilarityBar value={m.similarity} />
                      </TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function SimilarityBar({ value }: { value: number }) {
  // Range 0..1 → 0..100% width.  Negative similarity clamps to 0.
  const pct = Math.max(0, Math.min(1, value)) * 100;
  const color =
    value >= 0.95
      ? "bg-emerald-500"
      : value >= 0.8
        ? "bg-blue-500"
        : value >= 0.5
          ? "bg-amber-500"
          : "bg-red-400";
  return (
    <div className="flex items-center justify-end gap-2 min-w-[140px]">
      <div className="w-24 h-2 bg-muted rounded overflow-hidden">
        <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="font-mono text-xs w-14 text-right">{value.toFixed(3)}</span>
    </div>
  );
}

/* ------------------------------------------------------------- Sensitivity */
function SensitivityTab({ recipe }: { recipe: RecipeFull }) {
  const t = useT();
  const components = useMemo(
    () => recipe.stages.flatMap((s) => s.components),
    [recipe]
  );
  const [component, setComponent] = useState<string>("");
  const [minPct, setMinPct] = useState<number>(0);
  const [maxPct, setMaxPct] = useState<number>(0);
  const [steps, setSteps] = useState<number>(11);
  const [busy, setBusy] = useState<boolean>(false);
  const [err, setErr] = useState<string | null>(null);
  const [models, setModels] = useState<ModelMetadata[] | null>(null);
  const [result, setResult] = useState<SensitivityResult | null>(null);

  useEffect(() => {
    api.listModels().then(setModels).catch(() => setModels([]));
  }, []);

  useEffect(() => {
    // Default to the largest component, and a ±50 % sweep around its
    // baseline (clamped to 0..min(90, 3× baseline)).
    if (components.length === 0) return;
    const biggest = components.reduce((a, b) =>
      a.mass_percent >= b.mass_percent ? a : b
    );
    setComponent(biggest.name);
    const base = biggest.mass_percent;
    setMinPct(Math.max(0, Math.round((base * 0.5) * 100) / 100));
    setMaxPct(Math.min(90, Math.round((base * 1.5) * 100) / 100));
  }, [components]);

  const run = async () => {
    if (!component) return;
    setBusy(true);
    setErr(null);
    setResult(null);
    try {
      const r = await api.sensitivity(recipe.id, {
        component_name: component,
        min_percent: minPct,
        max_percent: maxPct,
        steps,
      });
      setResult(r);
    } catch (e: any) {
      setErr(t("sensitivity.failed", { msg: e.message ?? String(e) }));
    } finally {
      setBusy(false);
    }
  };

  const noModels = models !== null && models.length === 0;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>{t("sensitivity.title")}</CardTitle>
          <p className="text-sm text-muted-foreground">
            {t("sensitivity.subtitle")}
          </p>
        </CardHeader>
        <CardContent className="grid grid-cols-1 md:grid-cols-5 gap-3 items-end">
          <div className="md:col-span-2">
            <label className="text-xs text-muted-foreground">
              {t("sensitivity.component")}
            </label>
            <select
              className="w-full h-9 rounded-md border border-input px-2 text-sm bg-white"
              value={component}
              onChange={(e) => setComponent(e.target.value)}
            >
              {components.map((c) => (
                <option key={c.name} value={c.name}>
                  {c.name} ({fmt(c.mass_percent, 2)}%)
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-muted-foreground">{t("sensitivity.min")}</label>
            <input
              type="number"
              step="0.1"
              min={0}
              max={100}
              value={minPct}
              onChange={(e) => setMinPct(Number(e.target.value))}
              className="w-full h-9 rounded-md border border-input px-2 text-sm font-mono bg-white"
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">{t("sensitivity.max")}</label>
            <input
              type="number"
              step="0.1"
              min={0}
              max={100}
              value={maxPct}
              onChange={(e) => setMaxPct(Number(e.target.value))}
              className="w-full h-9 rounded-md border border-input px-2 text-sm font-mono bg-white"
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">{t("sensitivity.steps")}</label>
            <input
              type="number"
              min={3}
              max={41}
              value={steps}
              onChange={(e) => setSteps(Number(e.target.value) || 11)}
              className="w-full h-9 rounded-md border border-input px-2 text-sm font-mono bg-white"
            />
          </div>
          <div className="md:col-span-5">
            <Button onClick={run} disabled={busy || noModels || !component}>
              {busy ? t("sensitivity.running") : t("sensitivity.run")}
            </Button>
            {noModels && (
              <span className="ml-3 text-sm text-amber-700">
                {t("sensitivity.no_models")}
              </span>
            )}
          </div>
          {err && (
            <div className="md:col-span-5 text-sm text-red-700">{err}</div>
          )}
        </CardContent>
      </Card>

      {result && <SensitivityChart result={result} />}
    </div>
  );
}

function SensitivityChart({ result }: { result: SensitivityResult }) {
  const t = useT();

  // Build a series per property_code, dropping skipped points.
  const series: {
    code: string;
    points: { x: number; y: number }[];
    yMin: number;
    yMax: number;
  }[] = [];
  for (const code of result.property_codes) {
    const pts: { x: number; y: number }[] = [];
    for (const p of result.points) {
      if (p.skipped) continue;
      const y = p.predictions[code];
      if (y === null || y === undefined || Number.isNaN(y)) continue;
      pts.push({ x: p.target_percent, y });
    }
    if (pts.length < 2) continue;
    const ys = pts.map((p) => p.y);
    series.push({ code, points: pts, yMin: Math.min(...ys), yMax: Math.max(...ys) });
  }

  if (series.length === 0) {
    return (
      <Card>
        <CardContent className="p-6 text-sm text-muted-foreground">
          {t("sensitivity.hint")}
        </CardContent>
      </Card>
    );
  }

  // Palette matches the ML model list ordering; wrap if we ever have
  // more than 6 properties.
  const palette = [
    "hsl(221 83% 53%)",
    "hsl(0 84% 60%)",
    "hsl(142 71% 45%)",
    "hsl(38 92% 50%)",
    "hsl(280 70% 55%)",
    "hsl(190 80% 45%)",
  ];

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {series.map((s, i) => (
        <Card key={s.code}>
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              <span>{s.code}</span>
              <Badge variant="outline">n = {s.points.length}</Badge>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <Curve
              points={s.points}
              yMin={s.yMin}
              yMax={s.yMax}
              baseline={result.baseline_percent}
              color={palette[i % palette.length]}
              xLabel={t("sensitivity.chart.axis_x")}
              baselineLabel={t("sensitivity.chart.baseline")}
            />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function Curve({
  points,
  yMin,
  yMax,
  baseline,
  color,
  xLabel,
  baselineLabel,
}: {
  points: { x: number; y: number }[];
  yMin: number;
  yMax: number;
  baseline: number;
  color: string;
  xLabel: string;
  baselineLabel: string;
}) {
  const W = 480;
  const H = 220;
  const M = 34;
  const xMin = points[0].x;
  const xMax = points[points.length - 1].x;
  // Add a little vertical padding so the curve doesn't hug the top/bottom.
  const yPad = (yMax - yMin) * 0.08 || 1.0;
  const yLo = yMin - yPad;
  const yHi = yMax + yPad;
  const nx = (x: number) =>
    M + ((x - xMin) / Math.max(1e-9, xMax - xMin)) * (W - 2 * M);
  const ny = (y: number) =>
    H - M - ((y - yLo) / Math.max(1e-9, yHi - yLo)) * (H - 2 * M);
  const d = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${nx(p.x).toFixed(1)},${ny(p.y).toFixed(1)}`)
    .join(" ");
  const showBaseline = baseline >= xMin && baseline <= xMax;
  return (
    <svg width={W} height={H} className="mx-auto block max-w-full">
      {/* axes */}
      <line x1={M} y1={H - M} x2={W - M} y2={H - M} stroke="hsl(215 16% 65%)" />
      <line x1={M} y1={M} x2={M} y2={H - M} stroke="hsl(215 16% 65%)" />
      {/* baseline marker */}
      {showBaseline && (
        <>
          <line
            x1={nx(baseline)}
            y1={M}
            x2={nx(baseline)}
            y2={H - M}
            stroke="hsl(38 92% 50%)"
            strokeDasharray="4 3"
          />
          <text
            x={nx(baseline)}
            y={M - 4}
            textAnchor="middle"
            fill="hsl(38 92% 40%)"
            className="text-[10px]"
          >
            {baselineLabel} {baseline.toFixed(2)}
          </text>
        </>
      )}
      {/* axis labels */}
      <text
        x={W / 2}
        y={H - 8}
        textAnchor="middle"
        className="text-xs"
        fill="hsl(215 16% 47%)"
      >
        {xLabel}
      </text>
      <text
        x={M}
        y={H - M + 14}
        className="text-[10px]"
        fill="hsl(215 16% 47%)"
      >
        {xMin.toFixed(1)}
      </text>
      <text
        x={W - M}
        y={H - M + 14}
        textAnchor="end"
        className="text-[10px]"
        fill="hsl(215 16% 47%)"
      >
        {xMax.toFixed(1)}
      </text>
      <text
        x={M - 4}
        y={H - M}
        textAnchor="end"
        className="text-[10px]"
        fill="hsl(215 16% 47%)"
      >
        {yLo.toFixed(2)}
      </text>
      <text
        x={M - 4}
        y={M + 4}
        textAnchor="end"
        className="text-[10px]"
        fill="hsl(215 16% 47%)"
      >
        {yHi.toFixed(2)}
      </text>
      {/* curve */}
      <path d={d} fill="none" stroke={color} strokeWidth={2} />
      {points.map((p, i) => (
        <circle key={i} cx={nx(p.x)} cy={ny(p.y)} r={3} fill={color}>
          <title>
            {`x = ${p.x.toFixed(2)}%, y = ${p.y.toFixed(4)}`}
          </title>
        </circle>
      ))}
    </svg>
  );
}

function defaultPrice(fn: string): string {
  const table: Record<string, string> = {
    vehicle: "0.10",
    solvent: "1.20",
    pigment: "3.80",
    extender: "0.18",
    binder: "2.30",
    dispersant: "4.50",
    defoamer: "6.00",
    biocide_in_can: "18.00",
    rheology_modifier: "9.50",
    coalescent: "2.60",
    epoxy_resin: "4.20",
    curing_agent: "5.90",
    drier: "12.00",
    wetting_agent: "8.00",
    anti_skinning_agent: "10.00",
    silane_promoter: "18.00",
    adhesion_promoter: "18.00",
    additive: "6.00",
    wax: "5.00",
  };
  return table[fn] ?? "2.00";
}
