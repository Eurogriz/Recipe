"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { RefreshCw, Search, XCircle } from "lucide-react";
import { api, type AuditLogEntry, type AuditLogPageOut, type MeOut } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Table, TBody, THead, TH, TR, TD } from "@/components/ui/table";
import { useT } from "@/i18n/I18nProvider";

const PAGE_SIZE = 25;

type Filters = {
  recipe_id: string;
  actor: string;
  action: string;
};

const EMPTY_FILTERS: Filters = { recipe_id: "", actor: "", action: "" };

/** Compact action → colour map so the eye can scan the timeline. */
function actionBadgeVariant(
  action: string
): "success" | "warning" | "destructive" | "info" | "default" {
  const a = action.toLowerCase();
  if (a === "created" || a === "cloned" || a === "verified" || a === "login")
    return "success";
  if (
    a === "rejected" ||
    a === "deleted" ||
    a === "loginfailed" ||
    a === "apikeyrevoked"
  )
    return "destructive";
  if (
    a === "submitted" ||
    a === "updated" ||
    a === "propertymeasured" ||
    a === "apikeyissued"
  )
    return "warning";
  if (a === "logout") return "info";
  return "default";
}

export default function AuditLogPage() {
  const t = useT();
  const [me, setMe] = useState<MeOut | null>(null);
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [applied, setApplied] = useState<Filters>(EMPTY_FILTERS);
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<AuditLogPageOut | null>(null);
  const [availableActions, setAvailableActions] = useState<string[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<AuditLogEntry | null>(null);

  useEffect(() => {
    api.me().then(setMe).catch(() => setMe(null));
  }, []);

  const load = async (nextOffset: number, f: Filters) => {
    setLoading(true);
    setErr(null);
    try {
      const data = await api.listAuditLog({
        recipe_id: f.recipe_id || undefined,
        actor: f.actor || undefined,
        action: f.action || undefined,
        limit: PAGE_SIZE,
        offset: nextOffset,
      });
      setPage(data);
      // ``actions`` is populated only on the first page, so hold on to
      // it across paginations rather than losing the dropdown options
      // as soon as the user hits Next.
      if (data.actions && data.actions.length > 0) {
        setAvailableActions(data.actions);
      }
    } catch (e: any) {
      setErr(t("audit.failed").replace("{msg}", e?.message ?? String(e)));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (me?.role === "Admin") {
      load(0, EMPTY_FILTERS);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me?.role]);

  if (me && me.role !== "Admin") {
    return (
      <div className="p-6">
        <Card>
          <CardContent className="py-8 text-center text-muted-foreground">
            {t("admin.forbidden").replace("{role}", me.role || "-")}
          </CardContent>
        </Card>
      </div>
    );
  }

  const onApply = () => {
    setApplied(filters);
    setOffset(0);
    load(0, filters);
  };
  const onReset = () => {
    setFilters(EMPTY_FILTERS);
    setApplied(EMPTY_FILTERS);
    setOffset(0);
    load(0, EMPTY_FILTERS);
  };
  const onPage = (delta: number) => {
    const next = Math.max(0, offset + delta * PAGE_SIZE);
    setOffset(next);
    load(next, applied);
  };

  const rows = page?.entries ?? [];
  const total = page?.total ?? 0;
  const shown = rows.length;

  return (
    <div className="p-6 space-y-6 max-w-7xl">
      <div>
        <h1 className="text-2xl font-semibold">{t("audit.title")}</h1>
        <p className="text-sm text-muted-foreground pt-1">{t("audit.subtitle")}</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Search className="h-4 w-4" />
            {t("audit.filter.apply")}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-3 items-end">
            <div>
              <label className="block text-xs font-medium mb-1 text-muted-foreground">
                {t("audit.filter.recipe_id")}
              </label>
              <Input
                value={filters.recipe_id}
                onChange={(e) =>
                  setFilters({ ...filters, recipe_id: e.target.value })
                }
                placeholder="uuid"
              />
            </div>
            <div>
              <label className="block text-xs font-medium mb-1 text-muted-foreground">
                {t("audit.filter.actor")}
              </label>
              <Input
                value={filters.actor}
                onChange={(e) => setFilters({ ...filters, actor: e.target.value })}
                placeholder="user:root"
              />
            </div>
            <div>
              <label className="block text-xs font-medium mb-1 text-muted-foreground">
                {t("audit.filter.action")}
              </label>
              <select
                className="w-full h-9 border border-input rounded-md bg-white px-3 text-sm"
                value={filters.action}
                onChange={(e) =>
                  setFilters({ ...filters, action: e.target.value })
                }
              >
                <option value="">{t("audit.filter.any")}</option>
                {availableActions.map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex gap-2">
              <Button onClick={onApply}>{t("audit.filter.apply")}</Button>
              <Button variant="outline" onClick={onReset}>
                <XCircle className="h-4 w-4 mr-1" />
                {t("audit.filter.reset")}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="p-8 text-center text-muted-foreground text-sm flex items-center justify-center gap-2">
              <RefreshCw className="h-4 w-4 animate-spin" />
              {t("audit.loading")}
            </div>
          ) : err ? (
            <div className="p-4 text-sm text-red-800 bg-red-50 border-b border-red-200">
              {err}
            </div>
          ) : rows.length === 0 ? (
            <div className="p-8 text-center text-muted-foreground text-sm">
              {t("audit.empty")}
            </div>
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>{t("audit.col.time")}</TH>
                  <TH>{t("audit.col.actor")}</TH>
                  <TH>{t("audit.col.action")}</TH>
                  <TH>{t("audit.col.recipe")}</TH>
                  <TH>{t("audit.col.changes")}</TH>
                </TR>
              </THead>
              <TBody>
                {rows.map((e) => (
                  <TR
                    key={e.id}
                    className="cursor-pointer hover:bg-slate-50"
                    onClick={() => setSelected(e)}
                  >
                    <TD className="whitespace-nowrap text-xs text-muted-foreground">
                      {new Date(e.timestamp).toLocaleString()}
                    </TD>
                    <TD className="text-sm font-mono">{e.actor_label}</TD>
                    <TD>
                      <Badge variant={actionBadgeVariant(e.action)}>
                        {e.action}
                      </Badge>
                    </TD>
                    <TD className="font-mono text-xs">
                      {e.recipe_id ? (
                        <Link
                          href={`/recipes/${e.recipe_id}`}
                          className="text-primary hover:underline"
                          onClick={(ev) => ev.stopPropagation()}
                        >
                          {e.recipe_id.slice(0, 8)}…
                        </Link>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TD>
                    <TD className="text-xs text-muted-foreground max-w-md truncate">
                      {e.changes
                        ? Object.keys(e.changes).join(", ")
                        : t("audit.changes.none")}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <div className="flex items-center justify-between text-sm text-muted-foreground">
        <span>
          {t("audit.summary")
            .replace("{total}", String(total))
            .replace("{shown}", String(shown))}
        </span>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={offset === 0 || loading}
            onClick={() => onPage(-1)}
          >
            {t("audit.page.prev")}
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={loading || offset + PAGE_SIZE >= total}
            onClick={() => onPage(1)}
          >
            {t("audit.page.next")}
          </Button>
        </div>
      </div>

      {selected ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">
              {selected.action} · {selected.actor_label} ·{" "}
              {new Date(selected.timestamp).toLocaleString()}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="text-xs bg-slate-50 p-3 rounded-md overflow-auto">
              {JSON.stringify(selected.changes ?? {}, null, 2)}
            </pre>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
