"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PlayCircle, ShieldAlert } from "lucide-react";
import { api, type RegulatoryScanResult } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Table, TBody, THead, TH, TR, TD } from "@/components/ui/table";
import { useT } from "@/i18n/I18nProvider";

export default function RegulatoryPage() {
  const t = useT();
  const [result, setResult] = useState<RegulatoryScanResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [minSev, setMinSev] = useState<"warning" | "error">("warning");
  const [limit, setLimit] = useState<number>(500);
  const [categories, setCategories] = useState<string[]>([]);
  const [category, setCategory] = useState<string>("");

  useEffect(() => {
    // Populate the category dropdown from the current catalog.
    api
      .listRecipes({ limit: 500 })
      .then((r) => {
        const uniq = Array.from(
          new Set(r.items.map((x) => x.category).filter(Boolean))
        ).sort();
        setCategories(uniq);
      })
      .catch(() => setCategories([]));
  }, []);

  const run = async () => {
    setBusy(true);
    setErr(null);
    setResult(null);
    try {
      const r = await api.regulatoryScan({
        category: category || undefined,
        min_severity: minSev,
        limit,
      });
      setResult(r);
    } catch (e: any) {
      setErr(t("regulatory.failed", { msg: e.message ?? String(e) }));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="p-8 space-y-6">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight flex items-center gap-2">
          <ShieldAlert className="h-7 w-7 text-amber-600" />
          {t("regulatory.title")}
        </h1>
        <p className="text-muted-foreground mt-1">{t("regulatory.subtitle")}</p>
      </header>

      <Card>
        <CardContent className="p-4 grid grid-cols-1 md:grid-cols-4 gap-3 items-end">
          <div>
            <label className="text-xs text-muted-foreground block mb-1">
              {t("recipes.category.all")}
            </label>
            <select
              className="w-full h-9 rounded-md border border-input px-2 text-sm bg-white"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
            >
              <option value="">{t("recipes.category.all")}</option>
              {categories.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-muted-foreground block mb-1">
              {t("regulatory.min_severity")}
            </label>
            <select
              className="w-full h-9 rounded-md border border-input px-2 text-sm bg-white"
              value={minSev}
              onChange={(e) => setMinSev(e.target.value as "warning" | "error")}
            >
              <option value="warning">{t("regulatory.severity.warning")}</option>
              <option value="error">{t("regulatory.severity.error")}</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-muted-foreground block mb-1">
              {t("regulatory.limit")}
            </label>
            <input
              type="number"
              min={10}
              max={5000}
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value) || 500)}
              className="w-full h-9 rounded-md border border-input px-2 text-sm bg-white font-mono"
            />
          </div>
          <Button onClick={run} disabled={busy}>
            <PlayCircle className="h-4 w-4" />
            {busy ? t("regulatory.running") : t("regulatory.run")}
          </Button>
        </CardContent>
      </Card>

      {err && (
        <div className="rounded-md border border-red-300 bg-red-50 text-red-900 px-4 py-3 text-sm">
          {err}
        </div>
      )}

      {result && (
        <Card>
          <CardHeader>
            <CardTitle>
              {t("regulatory.summary", {
                scanned: result.n_scanned,
                offending: result.n_offending,
              })}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {result.n_scanned === 0 ? (
              <p className="text-sm text-amber-700">{t("regulatory.no_data")}</p>
            ) : result.findings.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                {t("regulatory.empty")}
              </p>
            ) : (
              <Table>
                <THead>
                  <TR>
                    <TH>{t("regulatory.col.recipe")}</TH>
                    <TH>{t("regulatory.col.category")}</TH>
                    <TH className="text-right">{t("regulatory.col.errors")}</TH>
                    <TH className="text-right">{t("regulatory.col.warnings")}</TH>
                    <TH>{t("regulatory.col.substances")}</TH>
                  </TR>
                </THead>
                <TBody>
                  {result.findings.map((f) => (
                    <TR key={f.recipe_id}>
                      <TD>
                        <Link
                          href={`/recipes/${encodeURIComponent(f.recipe_id)}`}
                          className="text-primary hover:underline"
                        >
                          {f.subcategory || f.recipe_id.slice(0, 12)}
                        </Link>
                      </TD>
                      <TD className="text-xs">{f.category}</TD>
                      <TD className="text-right">
                        <Badge variant={f.errors ? "destructive" : "outline"}>
                          {f.errors}
                        </Badge>
                      </TD>
                      <TD className="text-right">
                        <Badge variant={f.warnings ? "warning" : "outline"}>
                          {f.warnings}
                        </Badge>
                      </TD>
                      <TD className="text-xs">
                        {f.top_substances.length ? (
                          <div className="flex flex-wrap gap-1">
                            {f.top_substances.map((s, i) => (
                              <Badge key={i} variant="outline">
                                {s}
                              </Badge>
                            ))}
                          </div>
                        ) : (
                          "—"
                        )}
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
