"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Diff, Loader2 } from "lucide-react";
import {
  api,
  type CompareResultOut,
  type CompareComponentRowOut,
  type ComparePropertyRowOut,
  type CompareRecipeHeaderOut,
} from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { useT } from "@/i18n/I18nProvider";

/** Wrapper around ``useSearchParams`` — Next 14 requires a
 * ``<Suspense>`` boundary for the hook to work under `output=static`. */
export default function ComparePageWithSuspense() {
  return (
    <Suspense
      fallback={
        <div className="p-6 text-muted-foreground">Loading…</div>
      }
    >
      <ComparePage />
    </Suspense>
  );
}

function ComparePage() {
  const t = useT();
  const params = useSearchParams();
  const rawIds = params.get("ids") ?? "";
  const initialIds = rawIds
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  const [ids, setIds] = useState<string[]>(initialIds);
  const [diffThreshold, setDiffThreshold] = useState<string>("0.1");
  const [result, setResult] = useState<CompareResultOut | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showOnlyDiff, setShowOnlyDiff] = useState(false);

  const run = async (idsToCompare: string[]) => {
    setError(null);
    if (idsToCompare.length < 2 || idsToCompare.length > 4) {
      setResult(null);
      return;
    }
    setLoading(true);
    try {
      const r = await api.recipesCompare({
        ids: idsToCompare,
        diff_threshold: Number(diffThreshold) || 0.1,
      });
      setResult(r);
    } catch (e: any) {
      setResult(null);
      setError(e?.message ?? String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (ids.length >= 2 && ids.length <= 4) {
      run(ids);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const filteredComponents = showOnlyDiff
    ? result?.components.filter((r) => r.is_diff) ?? []
    : result?.components ?? [];
  const filteredProperties = showOnlyDiff
    ? result?.properties.filter((r) => r.is_diff) ?? []
    : result?.properties ?? [];

  return (
    <div className="p-6 space-y-6 max-w-7xl">
      <header>
        <h1 className="text-2xl font-semibold flex items-center gap-2">
          <Diff className="h-6 w-6 text-primary" />
          {t("compare.title")}
        </h1>
        <p className="text-sm text-muted-foreground pt-1">
          {t("compare.subtitle")}
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("compare.query.title")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="text-xs text-muted-foreground">
            {t("compare.query.hint")}
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2">
            {[0, 1, 2, 3].map((i) => (
              <Input
                key={i}
                value={ids[i] ?? ""}
                onChange={(e) => {
                  const next = [...ids];
                  next[i] = e.target.value.trim();
                  setIds(next.filter((_x, idx) => idx <= i || next[idx]));
                }}
                placeholder={
                  i < 2
                    ? t("compare.f.id_required", { n: i + 1 })
                    : t("compare.f.id_optional", { n: i + 1 })
                }
                className="font-mono text-xs"
              />
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <label className="text-xs text-muted-foreground">
              {t("compare.f.threshold")}:
              <Input
                type="number"
                min={0}
                max={100}
                step={0.1}
                value={diffThreshold}
                onChange={(e) => setDiffThreshold(e.target.value)}
                className="inline-block w-24 ml-2"
              />
            </label>
            <label className="text-xs text-muted-foreground flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={showOnlyDiff}
                onChange={(e) => setShowOnlyDiff(e.target.checked)}
              />
              {t("compare.f.show_only_diff")}
            </label>
            <Button
              onClick={() => run(ids.filter(Boolean))}
              disabled={loading || ids.filter(Boolean).length < 2}
            >
              {loading ? (
                <>
                  <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                  {t("common.loading")}
                </>
              ) : (
                t("compare.run")
              )}
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
        <>
          <ComparisonHeader recipes={result.recipes} />
          <ComponentGrid rows={filteredComponents} recipes={result.recipes} />
          <PropertyGrid rows={filteredProperties} recipes={result.recipes} />
        </>
      )}
    </div>
  );
}

function ComparisonHeader({
  recipes,
}: {
  recipes: CompareRecipeHeaderOut[];
}) {
  const t = useT();
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t("compare.header.title")}</CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {recipes.map((r) => (
          <Link
            key={r.id}
            href={`/recipes/${encodeURIComponent(r.id)}`}
            className="block rounded-md border border-border p-3 hover:border-primary/40 hover:bg-accent transition-colors"
          >
            <div className="text-xs text-muted-foreground">{r.category}</div>
            <div className="font-semibold text-sm truncate">{r.subcategory}</div>
            <div className="text-xs text-muted-foreground mt-1">
              {r.binder_type}
            </div>
            <div className="flex gap-1 mt-2">
              <StatusBadge status={r.status} />
              <Badge variant="outline">v{r.version}</Badge>
              <Badge variant="default">{r.product_class}</Badge>
            </div>
          </Link>
        ))}
      </CardContent>
    </Card>
  );
}

function ComponentGrid({
  rows,
  recipes,
}: {
  rows: CompareComponentRowOut[];
  recipes: CompareRecipeHeaderOut[];
}) {
  const t = useT();
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          {t("compare.components.title", { n: rows.length })}
        </CardTitle>
      </CardHeader>
      <CardContent className="p-0 overflow-x-auto">
        {rows.length === 0 ? (
          <div className="p-6 text-center text-muted-foreground text-sm">
            {t("compare.components.empty")}
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="border-b border-border">
              <tr className="text-xs text-muted-foreground uppercase">
                <th className="text-left px-3 py-2 w-40">CAS</th>
                <th className="text-left px-3 py-2">
                  {t("compare.components.col.name")}
                </th>
                {recipes.map((r, i) => (
                  <th
                    key={r.id}
                    className="text-right px-3 py-2 whitespace-nowrap"
                  >
                    {t("compare.components.col.recipe_n", { n: i + 1 })}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.cas_number}
                  className={row.is_diff ? "bg-amber-50/40" : ""}
                >
                  <td className="font-mono text-xs px-3 py-2 whitespace-nowrap">
                    {row.cas_number}
                    {row.is_diff && (
                      <Badge variant="warning" className="ml-2">
                        Δ
                      </Badge>
                    )}
                  </td>
                  <td className="px-3 py-2 text-xs text-muted-foreground truncate max-w-xs">
                    {row.canonical_name}
                  </td>
                  {row.cells.map((cell, i) => (
                    <td
                      key={i}
                      className="text-right font-mono px-3 py-2 whitespace-nowrap"
                    >
                      <MassCell value={cell.mass_percent} />
                      {cell.stage_number !== null && (
                        <div className="text-xs text-muted-foreground">
                          {t("compare.components.stage", {
                            n: cell.stage_number,
                          })}
                        </div>
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </CardContent>
    </Card>
  );
}

function PropertyGrid({
  rows,
  recipes,
}: {
  rows: ComparePropertyRowOut[];
  recipes: CompareRecipeHeaderOut[];
}) {
  const t = useT();
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          {t("compare.properties.title", { n: rows.length })}
        </CardTitle>
      </CardHeader>
      <CardContent className="p-0 overflow-x-auto">
        {rows.length === 0 ? (
          <div className="p-6 text-center text-muted-foreground text-sm">
            {t("compare.properties.empty")}
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="border-b border-border">
              <tr className="text-xs text-muted-foreground uppercase">
                <th className="text-left px-3 py-2 w-56">
                  {t("compare.properties.col.property")}
                </th>
                {recipes.map((r, i) => (
                  <th
                    key={r.id}
                    className="text-right px-3 py-2 whitespace-nowrap"
                  >
                    {t("compare.components.col.recipe_n", { n: i + 1 })}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.property_code}
                  className={row.is_diff ? "bg-amber-50/40" : ""}
                >
                  <td className="font-mono text-xs px-3 py-2">
                    {row.property_code}
                    {row.is_diff && (
                      <Badge variant="warning" className="ml-2">
                        Δ
                      </Badge>
                    )}
                  </td>
                  {row.cells.map((cell, i) => (
                    <td
                      key={i}
                      className="text-right font-mono px-3 py-2 whitespace-nowrap"
                    >
                      {cell.predicted_value !== null ? (
                        <>
                          {cell.predicted_value.toFixed(2)}
                          {cell.unit && (
                            <span className="text-xs text-muted-foreground ml-1">
                              {cell.unit}
                            </span>
                          )}
                        </>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </CardContent>
    </Card>
  );
}

function MassCell({ value }: { value: number | null }) {
  if (value === null) return <span className="text-muted-foreground">—</span>;
  const colour =
    value >= 30
      ? "text-red-700 font-semibold"
      : value >= 10
        ? "text-amber-700"
        : value >= 1
          ? ""
          : "text-muted-foreground";
  return <span className={colour}>{value.toFixed(2)}%</span>;
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
