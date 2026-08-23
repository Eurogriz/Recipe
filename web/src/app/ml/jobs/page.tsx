"use client";

import { useEffect, useState } from "react";
import { RefreshCw, X } from "lucide-react";
import { api, type JobRecord } from "@/lib/api";
import { fmt, timeAgoParts } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Table, TBody, THead, TH, TR, TD } from "@/components/ui/table";
import { useT } from "@/i18n/I18nProvider";

const STATUSES = ["all", "queued", "running", "succeeded", "failed", "cancelled"] as const;
type Filter = (typeof STATUSES)[number];

export default function JobsPage() {
  const t = useT();
  const [jobs, setJobs] = useState<JobRecord[] | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [selected, setSelected] = useState<JobRecord | null>(null);

  const load = () => {
    api
      .listJobs({ status: filter === "all" ? undefined : filter, limit: 100 })
      .then((r) => setJobs(r.jobs))
      .catch(() => setJobs([]));
  };

  useEffect(load, [filter]);
  useEffect(() => {
    const timer = setInterval(load, 3000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  const cancel = async (id: string) => {
    try {
      await api.cancelJob(id);
    } catch {
      /* 409 for terminal is fine */
    }
    load();
  };

  return (
    <div className="p-8 space-y-6">
      <header className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">{t("jobs.title")}</h1>
          <p className="text-muted-foreground mt-1">
            <SubtitleWithCode raw={t("jobs.subtitle", { endpoint: "__CODE__" })} />
          </p>
        </div>
        <Button variant="outline" onClick={load}>
          <RefreshCw className="h-4 w-4" /> {t("common.refresh")}
        </Button>
      </header>

      <div className="flex flex-wrap items-center gap-2">
        {STATUSES.map((s) => (
          <button
            key={s}
            onClick={() => setFilter(s)}
            className={`px-3 py-1 rounded-full text-xs border transition-colors ${
              filter === s
                ? "bg-primary text-primary-foreground border-primary"
                : "border-border hover:bg-accent"
            }`}
          >
            {t(`jobs.filter.${s}` as any)}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card className="lg:col-span-2">
          <CardContent className="p-0">
            <Table>
              <THead>
                <TR>
                  <TH>{t("jobs.col.id")}</TH>
                  <TH>{t("jobs.col.kind")}</TH>
                  <TH>{t("jobs.col.status")}</TH>
                  <TH>{t("jobs.col.created")}</TH>
                  <TH className="text-right">{t("jobs.col.duration")}</TH>
                  <TH />
                </TR>
              </THead>
              <TBody>
                {!jobs ? (
                  <TR>
                    <TD colSpan={6} className="text-center text-muted-foreground py-6">
                      {t("common.loading")}
                    </TD>
                  </TR>
                ) : jobs.length === 0 ? (
                  <TR>
                    <TD colSpan={6} className="text-center text-muted-foreground py-6">
                      {t("jobs.empty")}
                    </TD>
                  </TR>
                ) : (
                  jobs.map((j) => (
                    <TR
                      key={j.id}
                      className={
                        selected?.id === j.id ? "bg-muted/60 cursor-pointer" : "cursor-pointer"
                      }
                      onClick={() => setSelected(j)}
                    >
                      <TD className="font-mono text-xs">{j.id.slice(0, 12)}…</TD>
                      <TD className="text-xs">{j.kind}</TD>
                      <TD>
                        <StatusBadge s={j.status} />
                      </TD>
                      <TD className="text-xs">
                        <TimeAgo iso={j.created_at} />
                      </TD>
                      <TD className="text-right font-mono text-xs">
                        {fmt(j.duration_seconds, 2)}
                      </TD>
                      <TD className="text-right">
                        {(j.status === "queued" || j.status === "running") && (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={(e) => {
                              e.stopPropagation();
                              cancel(j.id);
                            }}
                          >
                            <X className="h-3 w-3" /> {t("common.cancel")}
                          </Button>
                        )}
                      </TD>
                    </TR>
                  ))
                )}
              </TBody>
            </Table>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{t("common.details")}</CardTitle>
          </CardHeader>
          <CardContent className="text-sm space-y-2">
            {!selected ? (
              <p className="text-muted-foreground">{t("jobs.details.click")}</p>
            ) : (
              <>
                <Row k={t("jobs.field.id")} v={selected.id} mono />
                <Row k={t("jobs.field.kind")} v={selected.kind} />
                <Row k={t("jobs.field.status")} v={selected.status} />
                <Row k={t("jobs.field.created")} v={selected.created_at} />
                <Row k={t("jobs.field.started")} v={selected.started_at ?? "—"} />
                <Row k={t("jobs.field.finished")} v={selected.finished_at ?? "—"} />
                <Row
                  k={t("jobs.field.duration")}
                  v={
                    selected.duration_seconds != null
                      ? `${selected.duration_seconds.toFixed(3)} s`
                      : "—"
                  }
                />
                {selected.error && (
                  <div className="pt-2">
                    <div className="text-xs uppercase text-muted-foreground">
                      {t("jobs.details.error")}
                    </div>
                    <pre className="text-xs bg-red-50 border border-red-200 rounded p-2 overflow-auto">
                      {selected.error}
                    </pre>
                  </div>
                )}
                {selected.result != null && (
                  <div className="pt-2">
                    <div className="text-xs uppercase text-muted-foreground">
                      {t("jobs.details.result")}
                    </div>
                    <pre className="text-xs bg-muted rounded p-2 overflow-auto max-h-96">
                      {JSON.stringify(selected.result, null, 2)}
                    </pre>
                  </div>
                )}
                <div className="pt-2">
                  <div className="text-xs uppercase text-muted-foreground">
                    {t("jobs.details.metadata")}
                  </div>
                  <pre className="text-xs bg-muted rounded p-2 overflow-auto max-h-40">
                    {JSON.stringify(selected.metadata, null, 2)}
                  </pre>
                </div>
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function StatusBadge({ s }: { s: string }) {
  const v =
    s === "succeeded"
      ? "success"
      : s === "failed"
        ? "destructive"
        : s === "running"
          ? "info"
          : s === "cancelled"
            ? "outline"
            : "warning";
  return <Badge variant={v}>{s}</Badge>;
}

function Row({ k, v, mono }: { k: string; v: string; mono?: boolean }) {
  return (
    <div className="flex justify-between gap-4 border-b border-border/60 py-1.5 last:border-0">
      <span className="text-muted-foreground">{k}</span>
      <span className={mono ? "font-mono text-xs break-all text-right" : "text-right"}>
        {v}
      </span>
    </div>
  );
}

function SubtitleWithCode({ raw }: { raw: string }) {
  // Split on the placeholder that will be replaced with an inline <code>.
  const parts = raw.split("__CODE__");
  return (
    <>
      {parts[0]}
      <code className="font-mono text-xs bg-muted px-1.5 py-0.5 rounded">
        POST /ml/train/async
      </code>
      {parts[1] ?? ""}
    </>
  );
}

function TimeAgo({ iso }: { iso: string | null | undefined }) {
  const t = useT();
  const { key, n } = timeAgoParts(iso);
  if (!key) return <>—</>;
  return <>{t(key, { n })}</>;
}
