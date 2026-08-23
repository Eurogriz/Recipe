"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  FlaskConical,
  Loader2,
  Search,
  X,
} from "lucide-react";
import {
  api,
  type CatalogFacetsOut,
  type ComponentMatchOut,
  type SearchByComponentResultOut,
} from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Table, TBody, THead, TH, TR, TD } from "@/components/ui/table";
import { useT } from "@/i18n/I18nProvider";

/** Well-known CAS'ы для быстрых кнопок — покрывают ~80% типичных запросов. */
const QUICK_CAS: Array<{ cas: string; label: string }> = [
  { cas: "13463-67-7", label: "TiO2 (rutile)" },
  { cas: "1317-65-3", label: "Limestone" },
  { cas: "9003-04-7", label: "Polyacrylate" },
  { cas: "7732-18-5", label: "Water" },
  { cas: "63148-62-9", label: "PDMS (silicone)" },
  { cas: "117-81-7", label: "DEHP (SVHC!)" },
  { cas: "71-43-2", label: "Benzene (SVHC!)" },
  { cas: "50-00-0", label: "Formaldehyde (SVHC!)" },
];

export default function ComponentSearchPage() {
  const t = useT();
  const [cas, setCas] = useState("");
  const [minPct, setMinPct] = useState<string>("");
  const [maxPct, setMaxPct] = useState<string>("");
  const [category, setCategory] = useState<string>("");
  const [facets, setFacets] = useState<CatalogFacetsOut | null>(null);
  const [result, setResult] = useState<SearchByComponentResultOut | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Facets used only for the category dropdown; failure is
    // non-fatal — the CAS search still works without it.
    api
      .catalogFacets()
      .then(setFacets)
      .catch(() => setFacets(null));
  }, []);

  const runSearch = async () => {
    if (!cas.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const r = await api.recipesByComponent({
        cas: cas.trim(),
        min_mass_percent: minPct ? Number(minPct) : undefined,
        max_mass_percent: maxPct ? Number(maxPct) : undefined,
        category: category || undefined,
        limit: 200,
      });
      setResult(r);
    } catch (e: any) {
      setError(e?.message ?? String(e));
    } finally {
      setLoading(false);
    }
  };

  const resetAll = () => {
    setCas("");
    setMinPct("");
    setMaxPct("");
    setCategory("");
    setResult(null);
    setError(null);
  };

  const categories = facets
    ? Object.entries(facets.by_category).sort(([a], [b]) => a.localeCompare(b))
    : [];

  return (
    <div className="p-6 space-y-6 max-w-7xl">
      <header>
        <h1 className="text-2xl font-semibold flex items-center gap-2">
          <FlaskConical className="h-6 w-6 text-primary" />
          {t("search.title")}
        </h1>
        <p className="text-sm text-muted-foreground pt-1">{t("search.subtitle")}</p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <Search className="h-4 w-4" />
            {t("search.query.title")}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-6 gap-3">
            <div className="md:col-span-2">
              <label className="block text-xs font-medium mb-1 text-muted-foreground uppercase">
                {t("search.f.cas")}
              </label>
              <Input
                value={cas}
                onChange={(e) => setCas(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") runSearch();
                }}
                placeholder="13463-67-7"
                className="font-mono"
                autoFocus
              />
            </div>
            <div>
              <label className="block text-xs font-medium mb-1 text-muted-foreground uppercase">
                {t("search.f.min")}
              </label>
              <Input
                type="number"
                min={0}
                max={100}
                step={0.1}
                value={minPct}
                onChange={(e) => setMinPct(e.target.value)}
                placeholder="0"
              />
            </div>
            <div>
              <label className="block text-xs font-medium mb-1 text-muted-foreground uppercase">
                {t("search.f.max")}
              </label>
              <Input
                type="number"
                min={0}
                max={100}
                step={0.1}
                value={maxPct}
                onChange={(e) => setMaxPct(e.target.value)}
                placeholder="100"
              />
            </div>
            <div className="md:col-span-2">
              <label className="block text-xs font-medium mb-1 text-muted-foreground uppercase">
                {t("search.f.category")}
              </label>
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                className="w-full h-9 rounded-md border border-input px-3 text-sm bg-white"
                disabled={!facets}
              >
                <option value="">
                  {facets ? t("search.f.category.any") : t("recipes.filter.loading")}
                </option>
                {categories.map(([c, n]) => (
                  <option key={c} value={c}>
                    {c} ({n})
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-muted-foreground uppercase">
              {t("search.quick")}
            </span>
            {QUICK_CAS.map((q) => (
              <Button
                key={q.cas}
                variant="outline"
                size="sm"
                onClick={() => {
                  setCas(q.cas);
                }}
              >
                {q.label}
              </Button>
            ))}
          </div>

          <div className="flex gap-2">
            <Button onClick={runSearch} disabled={loading || !cas.trim()}>
              {loading ? (
                <>
                  <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                  {t("common.loading")}
                </>
              ) : (
                <>
                  <Search className="h-4 w-4 mr-1" />
                  {t("search.run")}
                </>
              )}
            </Button>
            <Button variant="outline" onClick={resetAll}>
              <X className="h-4 w-4 mr-1" />
              {t("search.reset")}
            </Button>
          </div>
        </CardContent>
      </Card>

      {error && (
        <div className="p-3 rounded-md bg-red-50 text-red-800 text-sm border border-red-200">
          {error}
        </div>
      )}

      {result && !loading && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              {result.n_recipes === 0
                ? t("search.results.empty")
                : t("search.results.title", {
                    n: result.n_recipes,
                    cas: result.cas_number,
                  })}
            </CardTitle>
          </CardHeader>
          {result.n_recipes > 0 && (
            <CardContent className="p-0">
              <Table>
                <THead>
                  <TR>
                    <TH>{t("search.col.category")}</TH>
                    <TH>{t("search.col.subcategory")}</TH>
                    <TH>{t("search.col.status")}</TH>
                    <TH className="text-right">{t("search.col.total")}</TH>
                    <TH className="text-right">{t("search.col.stages")}</TH>
                    <TH>{t("search.col.names")}</TH>
                  </TR>
                </THead>
                <TBody>
                  {result.matches.map((m) => (
                    <TR key={m.recipe_id}>
                      <TD className="text-xs">{m.recipe_category}</TD>
                      <TD className="text-sm">
                        <Link
                          href={`/recipes/${encodeURIComponent(m.recipe_id)}`}
                          className="text-primary hover:underline"
                        >
                          {m.recipe_subcategory || m.recipe_id.slice(0, 8) + "…"}
                        </Link>
                      </TD>
                      <TD>
                        <StatusBadge status={m.recipe_status} />
                      </TD>
                      <TD className="text-right font-mono font-semibold">
                        <MassPercent value={m.total_mass_percent} />
                      </TD>
                      <TD className="text-right text-xs text-muted-foreground">
                        {m.n_stages}
                      </TD>
                      <TD className="text-xs text-muted-foreground">
                        {m.stage_names.slice(0, 3).join(" · ")}
                        {m.stage_names.length > 3 && " …"}
                      </TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            </CardContent>
          )}
        </Card>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const v =
    status === "Verified"
      ? "success"
      : status === "PendingReview"
        ? "warning"
        : status === "Rejected"
          ? "destructive"
          : "outline";
  return <Badge variant={v}>{status}</Badge>;
}

/** Colour-code the mass percentage so the eye picks up dominant vs
 * trace uses at a glance. */
function MassPercent({ value }: { value: number }) {
  const colour =
    value >= 30
      ? "text-red-700"
      : value >= 10
        ? "text-amber-700"
        : "text-emerald-700";
  return <span className={colour}>{value.toFixed(2)}%</span>;
}
