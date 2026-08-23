"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  ChevronLeft,
  ChevronRight,
  Download,
  Filter,
  Loader2,
  Plus,
  Search,
} from "lucide-react";
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
import {
  COMPARE_MAX_SIZE,
  useCompareSelection,
} from "@/lib/compare-selection";
import { Check, GitCompareArrows } from "lucide-react";

// 60 fits neatly in a 3-col grid at any breakpoint and is small enough
// to render at ~5 ms per page.  200 (v1.19) was too coarse — the user
// couldn't reach recipes past the first page and paged searches were
// slow because of the composition-tree eager loads.
const PAGE_SIZE = 60;

export default function RecipesPage() {
  const t = useT();
  const [items, setItems] = useState<RecipeSummary[] | null>(null);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState("");
  const [category, setCategory] = useState<string | null>(null);
  const [subcategory, setSubcategory] = useState<string | null>(null);
  const [productClass, setProductClass] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Facets — fetched once and reused for every filter dropdown.  Was
  // previously inferred from the current search page, which meant
  // that if the first page happened to contain only 1-2 categories
  // (e.g. lexicographic sort) the user could never reach the rest.
  const [facets, setFacets] = useState<CatalogFacetsOut | null>(null);
  const [facetsError, setFacetsError] = useState<string | null>(null);

  // Sorted dropdown entries — we keep the count in the label so the
  // user immediately sees the size of each bucket ("Краски (320)").
  const categoryEntries = facets
    ? Object.entries(facets.by_category).sort(([a], [b]) => a.localeCompare(b))
    : [];
  const subcategoryEntries =
    facets && category
      ? Object.entries(facets.by_subcategory[category] ?? {}).sort(([a], [b]) =>
          a.localeCompare(b)
        )
      : [];
  const productClassEntries = facets
    ? Object.entries(facets.by_product_class).sort(([a], [b]) => a.localeCompare(b))
    : [];

  // Debounced text search so every keystroke doesn't hammer the API.
  // Filters change synchronously via handlers below and don't need a
  // debounce (a user clicking a dropdown expects an immediate update).
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const currentRequestId = useRef(0);

  // Explicit ``loadArgs`` so callers pass the exact filter set they
  // want — avoids the classic bug where React's stale closure over
  // the previous state value silently sends yesterday's query.
  const load = useCallback(
    (args: {
      q: string;
      category: string | null;
      subcategory: string | null;
      productClass: string | null;
      offset: number;
    }) => {
      const requestId = ++currentRequestId.current;
      setLoading(true);
      setError(null);
      api
        .listRecipes({
          q: args.q,
          category: args.category ? [args.category] : undefined,
          subcategory: args.subcategory ? [args.subcategory] : undefined,
          product_class: args.productClass ? [args.productClass] : undefined,
          limit: PAGE_SIZE,
          offset: args.offset,
        })
        .then((r: SearchResponse) => {
          // Ignore stale responses — a slow request finishing after a
          // fresh one would otherwise overwrite the newer results.
          if (requestId !== currentRequestId.current) return;
          setItems(r.items);
          setTotal(r.total_count);
        })
        .catch((e) => {
          if (requestId !== currentRequestId.current) return;
          setError(e.message ?? String(e));
        })
        .finally(() => {
          if (requestId !== currentRequestId.current) return;
          setLoading(false);
        });
    },
    []
  );

  // Initial load + facets fetch (in parallel).  Facet response is
  // typically <100 ms so we don't stagger them.
  useEffect(() => {
    api
      .catalogFacets()
      .then((f) => {
        setFacets(f);
        setFacetsError(null);
      })
      .catch((e) => {
        setFacets(null);
        setFacetsError(e?.message ?? String(e));
      });
    load({ q: "", category: null, subcategory: null, productClass: null, offset: 0 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Reload when filter or offset changes — no more manual "Search"
  // click for filter selection.  Any filter change resets offset to
  // 0 (see the effect below); offset changes on their own reload
  // just the page.
  useEffect(() => {
    load({ q, category, subcategory, productClass, offset });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [category, subcategory, productClass, offset]);

  // Any filter change resets to page 1 — a user on page 5 of Мастики
  // who switches to Краски expects to see page 1 of Краски, not
  // page 5 (which might not even exist).
  useEffect(() => {
    setOffset(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [category, subcategory, productClass, q]);

  // Reset subcategory when category changes — otherwise a stale
  // subcategory value from another category silently filters to 0.
  useEffect(() => {
    setSubcategory(null);
  }, [category]);

  // Debounced text search — 350 ms after the user stops typing.
  // Text change already reset offset to 0 via the effect above.
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      load({ q, category, subcategory, productClass, offset: 0 });
    }, 350);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

  const resetFilters = () => {
    setCategory(null);
    setSubcategory(null);
    setProductClass(null);
  };

  const hasActiveFilters = !!(category || subcategory || productClass || q);

  return (
    <div className="p-8 space-y-6">
      <header className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">
            {t("recipes.title")}
          </h1>
          <p className="text-muted-foreground mt-1">
            {hasActiveFilters
              ? t("recipes.subtitle.filtered", {
                  shown: total,
                  total: facets?.total ?? total,
                })
              : t("recipes.subtitle.total", { n: total })}
            {total > PAGE_SIZE && (
              <span className="ml-2">
                ·{" "}
                {t("recipes.subtitle.page", {
                  from: offset + 1,
                  to: Math.min(offset + PAGE_SIZE, total),
                })}
              </span>
            )}
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
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    if (debounceRef.current) clearTimeout(debounceRef.current);
                    load({ q, category, subcategory, productClass, offset: 0 });
                  }
                }}
                placeholder={t("recipes.search_placeholder")}
                className="pl-9"
              />
            </div>
            {loading && (
              <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                <Loader2 className="h-3 w-3 animate-spin" />
                {t("common.loading")}
              </span>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <Filter className="h-4 w-4 text-muted-foreground" />
            <select
              className="h-9 rounded-md border border-input px-3 text-sm bg-white min-w-[10rem]"
              value={category ?? ""}
              onChange={(e) => setCategory(e.target.value || null)}
              disabled={!facets}
            >
              <option value="">
                {facets
                  ? t("recipes.category.all")
                  : t("recipes.filter.loading")}
              </option>
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
              disabled={!facets}
            >
              <option value="">
                {facets
                  ? t("recipes.class.all")
                  : t("recipes.filter.loading")}
              </option>
              {productClassEntries.map(([c, n]) => (
                <option key={c} value={c}>
                  {c} ({n})
                </option>
              ))}
            </select>
            {hasActiveFilters && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setQ("");
                  resetFilters();
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
            {facetsError && (
              <span className="ml-auto text-xs text-red-700">
                {t("recipes.facets.failed", { msg: facetsError })}
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
          <RecipeCard key={r.id} recipe={r} />
        ))}
        {items?.length === 0 && !loading && (
          <div className="col-span-full text-center text-muted-foreground py-12 border border-dashed border-border rounded-lg">
            {hasActiveFilters
              ? t("recipes.empty.filtered")
              : t("recipes.empty", { cmd: "python scripts/dev/seed_demo.py" })
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

      {total > PAGE_SIZE && (
        <Pagination
          offset={offset}
          pageSize={PAGE_SIZE}
          total={total}
          loading={loading}
          onOffset={(next) => {
            setOffset(next);
            // Smooth scroll to top so the user sees the new page.
            // Instant would also work but jarring in a long list.
            window.scrollTo({ top: 0, behavior: "smooth" });
          }}
        />
      )}
    </div>
  );
}

function Pagination({
  offset,
  pageSize,
  total,
  loading,
  onOffset,
}: {
  offset: number;
  pageSize: number;
  total: number;
  loading: boolean;
  onOffset: (next: number) => void;
}) {
  const t = useT();
  // Convert to 1-based page numbers for display — humans count
  // pages from 1, not 0.
  const currentPage = Math.floor(offset / pageSize) + 1;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const canPrev = offset > 0 && !loading;
  const canNext = offset + pageSize < total && !loading;

  return (
    <div className="flex items-center justify-between gap-3 pt-2 border-t border-border">
      <span className="text-xs text-muted-foreground">
        {t("recipes.pagination.status", {
          from: offset + 1,
          to: Math.min(offset + pageSize, total),
          total,
        })}
      </span>
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={!canPrev}
          onClick={() => onOffset(Math.max(0, offset - pageSize))}
        >
          <ChevronLeft className="h-3 w-3 mr-1" />
          {t("recipes.pagination.prev")}
        </Button>
        <span className="text-xs text-muted-foreground px-2">
          {t("recipes.pagination.page_of", {
            page: currentPage,
            total: totalPages,
          })}
        </span>
        <Button
          variant="outline"
          size="sm"
          disabled={!canNext}
          onClick={() => onOffset(offset + pageSize)}
        >
          {t("recipes.pagination.next")}
          <ChevronRight className="h-3 w-3 ml-1" />
        </Button>
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

/** Card that both navigates on the main click AND allows toggling
 *  the compare-selection via a checkbox in the top-right corner.
 *
 *  The checkbox is a plain ``<button>`` (not an ``<input>``) because
 *  the whole card is wrapped in a ``<Link>`` and nested interactive
 *  elements need explicit ``stopPropagation`` — a real checkbox
 *  triggers browser default-click before React sees the event,
 *  which navigates the wrapping link.
 */
function RecipeCard({ recipe }: { recipe: RecipeSummary }) {
  const t = useT();
  const { has, toggle, isFull } = useCompareSelection();
  const selected = has(recipe.id);
  const disabled = !selected && isFull;

  return (
    <div className="relative">
      <Link
        href={`/recipes/${encodeURIComponent(recipe.id)}`}
        className="block"
      >
        <Card
          className={
            "hover:border-primary/40 hover:shadow transition-all h-full" +
            (selected ? " ring-2 ring-primary/70" : "")
          }
        >
          <CardContent className="p-5 space-y-3">
            <div className="flex items-start justify-between gap-3">
              <div className="pr-8 min-w-0">
                <div className="text-xs text-muted-foreground truncate">
                  {recipe.category}
                </div>
                <div className="font-semibold leading-tight truncate">
                  {recipe.subcategory || recipe.id}
                </div>
              </div>
              <StatusBadge status={recipe.status} />
            </div>
            <p className="text-sm text-muted-foreground line-clamp-2">
              {recipe.intended_use || "—"}
            </p>
            <div className="flex flex-wrap gap-2 pt-1">
              <Badge variant="outline">{recipe.product_class}</Badge>
              {recipe.binder_type && (
                <Badge variant="info">{recipe.binder_type}</Badge>
              )}
              <Badge variant="default">
                {t("recipe.version", { n: recipe.version })}
              </Badge>
            </div>
          </CardContent>
        </Card>
      </Link>
      {/* Compare-selection toggle — absolutely positioned so it
        * overlays the top-right corner of the card without breaking
        * the link's clickable area.  ``preventDefault`` is critical
        * — without it the wrapping ``<Link>`` navigates before the
        * onClick handler ever fires. */}
      <button
        type="button"
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          if (disabled) return;
          toggle(recipe.id);
        }}
        disabled={disabled}
        aria-label={
          selected
            ? t("recipes.card.deselect_aria")
            : t("recipes.card.select_aria")
        }
        title={
          disabled
            ? t("recipes.card.compare_full", { max: COMPARE_MAX_SIZE })
            : selected
              ? t("recipes.card.deselect_title")
              : t("recipes.card.select_title")
        }
        className={
          "absolute top-3 right-3 h-6 w-6 rounded-md border transition-colors flex items-center justify-center " +
          (selected
            ? "bg-primary text-primary-foreground border-primary"
            : disabled
              ? "bg-muted border-border text-muted-foreground opacity-50 cursor-not-allowed"
              : "bg-white border-border text-muted-foreground hover:border-primary/60 hover:text-primary")
        }
      >
        {selected ? (
          <Check className="h-3.5 w-3.5" />
        ) : (
          <GitCompareArrows className="h-3.5 w-3.5" />
        )}
      </button>
    </div>
  );
}
