"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Search, Filter, Download, Plus } from "lucide-react";
import {
  api,
  type CatalogFacetsOut,
  type RecipeSummary,
  type SearchResponse,
} from "@/lib/api";
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
  const [subcategory, setSubcategory] = useState<string | null>(null);
  const [productClass, setProductClass] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Facets are fetched once and reused for every dropdown so the
  // filter widgets show every value in the catalogue, not just what
  // happened to land on the current page.
  const [facets, setFacets] = useState<CatalogFacetsOut | null>(null);

  // Sorted category list — server already returns them alphabetically
  // but a tuple<label, count> is friendlier for the dropdown.
  const categoryEntries = facets
    ? Object.entries(facets.by_category).sort(([a], [b]) => a.localeCompare(b))
    : [];
  // Subcategory dropdown is scoped to the chosen category — a shortcut
  // that avoids the "40+ subcategories, half of them irrelevant" trap.
  const subcategoryEntries =
    facets && category
      ? Object.entries(facets.by_subcategory[category] ?? {}).sort(([a], [b]) =>
          a.localeCompare(b)
        )
      : [];
  const productClassEntries = facets
    ? Object.entries(facets.by_product_class).sort(([a], [b]) => a.localeCompare(b))
    : [];

  const load = () => {
    setLoading(true);
    setError(null);
    api
      .listRecipes({
        q,
        category: category ? [category] : undefined,
        // The API supports multi-value ``category`` but a single-value
        // subcategory is expressed by narrowing the category first,
        // which is exactly what the dropdown chain enforces.
        subcategory: subcategory ? [subcategory] : undefined,
        product_class: productClass ? [productClass] : undefined,
        limit: 200,
      })
      .then((r: SearchResponse) => {
        setItems(r.items);
        setTotal(r.total_count);
      })
      .catch((e) => setError(e.message ?? String(e)))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    // Facets → in parallel with the first page load.  Server returns
    // both under 100 ms on a fresh SQLite, so we don't stagger them.
    api.catalogFacets().then(setFacets).catch(() => setFacets(null));
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Reset subcategory when category changes — otherwise a stale
  // subcategory from a different category silently filters the list
  // to zero results.
  useEffect(() => {
    setSubcategory(null);
  }, [category]);

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
          <a
            href={api.catalogPdfUrl({
              category: category ?? undefined,
              limit: 50,
            })}
            download
            className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
          >
            <Download className="h-4 w-4" /> {t("recipes.export.pdf")}
          </a>
        </div>
      </header>

      <Card>
        <CardContent className="p-4 space-y-3">
          <div className="flex flex-col md:flex-row gap-3 md:items-center">
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
            <Button onClick={load} disabled={loading}>
              {loading ? t("common.loading") : t("common.search")}
            </Button>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <Filter className="h-4 w-4 text-muted-foreground" />
            <select
              className="h-9 rounded-md border border-input px-3 text-sm bg-white min-w-[10rem]"
              value={category ?? ""}
              onChange={(e) => setCategory(e.target.value || null)}
            >
              <option value="">{t("recipes.category.all")}</option>
              {categoryEntries.map(([c, n]) => (
                <option key={c} value={c}>
                  {c} ({n})
                </option>
              ))}
            </select>
            <select
              className="h-9 rounded-md border border-input px-3 text-sm bg-white min-w-[10rem] disabled:opacity-50"
              value={subcategory ?? ""}
              onChange={(e) => setSubcategory(e.target.value || null)}
              disabled={!category || subcategoryEntries.length === 0}
              title={
                category
                  ? t("recipes.subcategory.all")
                  : t("recipes.subcategory.pick_category_first")
              }
            >
              <option value="">
                {category
                  ? t("recipes.subcategory.all")
                  : t("recipes.subcategory.pick_category_first")}
              </option>
              {subcategoryEntries.map(([s, n]) => (
                <option key={s} value={s}>
                  {s} ({n})
                </option>
              ))}
            </select>
            <select
              className="h-9 rounded-md border border-input px-3 text-sm bg-white min-w-[8rem]"
              value={productClass ?? ""}
              onChange={(e) => setProductClass(e.target.value || null)}
            >
              <option value="">{t("recipes.class.all")}</option>
              {productClassEntries.map(([c, n]) => (
                <option key={c} value={c}>
                  {c} ({n})
                </option>
              ))}
            </select>
            {(category || subcategory || productClass) && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setCategory(null);
                  setSubcategory(null);
                  setProductClass(null);
                }}
              >
                {t("recipes.filter.reset")}
              </Button>
            )}
            {facets && (
              <span className="ml-auto text-xs text-muted-foreground">
                {t("recipes.facets.hint", {
                  n: Object.keys(facets.by_category).length,
                  total: facets.total,
                })}
              </span>
            )}
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
