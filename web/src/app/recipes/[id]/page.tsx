"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, Beaker, ClipboardCheck, DollarSign, LineChart } from "lucide-react";
import {
  api,
  type Assessment,
  type PredictionsOut,
  type RecipeCost,
  type RecipeFull,
} from "@/lib/api";
import { fmt } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TBody, THead, TH, TR, TD } from "@/components/ui/table";
import { useT } from "@/i18n/I18nProvider";

type Tab = "composition" | "assessment" | "predict" | "cost";

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
      <Link
        href="/recipes"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" /> {t("recipe.back")}
      </Link>

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
      </div>

      {tab === "composition" && <CompositionTab recipe={recipe} />}
      {tab === "assessment" && <AssessmentTab id={id} />}
      {tab === "predict" && <PredictTab id={id} />}
      {tab === "cost" && <CostTab recipe={recipe} />}
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
