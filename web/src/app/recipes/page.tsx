"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Search, Filter, Download, Plus } from "lucide-react";
import { api, type RecipeSummary, type SearchResponse } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useT } from "@/i18n/I18nProvider";

export default function RecipesPage() {
  const t = useT();
  const [items, setItems] = useState<RecipeSummary[] | null>(null);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState("");
  const [category, setCategory] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const categories = useMemo(() => {
    const s = new Set<string>();
    items?.forEach((r) => r.category && s.add(r.category));
    return Array.from(s).sort();
  }, [items]);

  const load = () => {
    setLoading(true);
    setError(null);
    api
      .listRecipes({ q, category: category ? [category] : undefined, limit: 200 })
      .then((r: SearchResponse) => {
        setItems(r.items);
        setTotal(r.total_count);
      })
      .catch((e) => setError(e.message ?? String(e)))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="p-8 space-y-6">
      <header className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">{t("recipes.title")}</h1>
          <p className="text-muted-foreground mt-1">
            {t("recipes.subtitle", { n: total })}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Link
            href="/recipes/new"
            className="inline-flex items-center gap-1 rounded-md bg-primary text-primary-foreground px-3 py-1.5 text-sm hover:bg-primary/90"
          >
            <Plus className="h-4 w-4" /> {t("recipes.new")}
          </Link>
          <a
            href={api.catalogCsvUrl()}
            download
            className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
          >
            <Download className="h-4 w-4" /> {t("recipes.export.csv")}
          </a>
        </div>
      </header>

      <Card>
        <CardContent className="p-4 flex flex-col md:flex-row gap-3 md:items-center">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && load()}
              placeholder={t("recipes.search_placeholder")}
              className="pl-9"
            />
          </div>
          <div className="flex items-center gap-2">
            <Filter className="h-4 w-4 text-muted-foreground" />
            <select
              className="h-9 rounded-md border border-input px-3 text-sm bg-white"
              value={category ?? ""}
              onChange={(e) => setCategory(e.target.value || null)}
            >
              <option value="">{t("recipes.category.all")}</option>
              {categories.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
            <Button onClick={load} disabled={loading}>
              {loading ? t("common.loading") : t("common.search")}
            </Button>
          </div>
        </CardContent>
      </Card>

      {error && (
        <div className="rounded-md border border-destructive/30 bg-red-50 text-red-900 px-4 py-3 text-sm">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {items?.map((r) => (
          <Link key={r.id} href={`/recipes/${encodeURIComponent(r.id)}`} className="block">
            <Card className="hover:border-primary/40 hover:shadow transition-all h-full">
              <CardContent className="p-5 space-y-3">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-xs text-muted-foreground">{r.category}</div>
                    <div className="font-semibold leading-tight">
                      {r.subcategory || r.id}
                    </div>
                  </div>
                  <StatusBadge status={r.status} />
                </div>
                <p className="text-sm text-muted-foreground line-clamp-2">
                  {r.intended_use || "—"}
                </p>
                <div className="flex flex-wrap gap-2 pt-1">
                  <Badge variant="outline">{r.product_class}</Badge>
                  {r.binder_type && <Badge variant="info">{r.binder_type}</Badge>}
                  <Badge variant="default">{t("recipe.version", { n: r.version })}</Badge>
                </div>
              </CardContent>
            </Card>
          </Link>
        ))}
        {items?.length === 0 && (
          <div className="col-span-full text-center text-muted-foreground py-12 border border-dashed border-border rounded-lg">
            {t("recipes.empty", { cmd: "python scripts/dev/seed_demo.py" })
              .split(/(python scripts\/dev\/seed_demo\.py)/)
              .map((chunk, i) =>
                chunk === "python scripts/dev/seed_demo.py" ? (
                  <code
                    key={i}
                    className="font-mono text-xs bg-muted px-1.5 py-0.5 rounded mx-1"
                  >
                    {chunk}
                  </code>
                ) : (
                  <span key={i}>{chunk}</span>
                )
              )}
          </div>
        )}
      </div>
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
