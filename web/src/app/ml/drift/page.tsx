"use client";

import { useEffect, useMemo, useState } from "react";
import { RefreshCw, PlayCircle } from "lucide-react";
import {
  api,
  type AlertConfig,
  type DriftFullOut,
  type ModelMetadata,
} from "@/lib/api";
import { fmt } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Table, TBody, THead, TH, TR, TD } from "@/components/ui/table";
import { useT } from "@/i18n/I18nProvider";

const FEATURE_COUNT = 37; // matches formulation_workbench.infrastructure.ml.features.FEATURE_NAMES

type Source = "current" | "production" | "random";

export default function DriftPage() {
  const t = useT();
  const [models, setModels] = useState<ModelMetadata[] | null>(null);
  const [selectedCode, setSelectedCode] = useState<string>("");
  const [source, setSource] = useState<Source>("current");
  const [nCurrent, setNCurrent] = useState<number>(100);
  const [busy, setBusy] = useState<boolean>(false);
  const [err, setErr] = useState<string | null>(null);
  const [report, setReport] = useState<DriftFullOut | null>(null);
  const [productionCount, setProductionCount] = useState<number>(0);
  const [ingestMsg, setIngestMsg] = useState<string | null>(null);
  const [ingesting, setIngesting] = useState<boolean>(false);
  const [catalogSize, setCatalogSize] = useState<number>(0);
  const [alertCfg, setAlertCfg] = useState<AlertConfig | null>(null);
  const [alertTestMsg, setAlertTestMsg] = useState<string | null>(null);
  const [alertTesting, setAlertTesting] = useState<boolean>(false);

  useEffect(() => {
    api
      .listModels()
      .then((ms) => {
        setModels(ms);
        if (ms.length > 0 && !selectedCode) setSelectedCode(ms[0].property_code);
      })
      .catch(() => setModels([]));
    api
      .listProductionVectors({ limit: 1 })
      .then((p) => setProductionCount(p.total))
      .catch(() => setProductionCount(0));
    api
      .catalogStats()
      .then((s) => setCatalogSize(s.total))
      .catch(() => setCatalogSize(0));
    api
      .info()
      .then((i) => setAlertCfg(i.alert ?? null))
      .catch(() => setAlertCfg(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const sendTestAlert = async () => {
    if (!selectedCode) return;
    setAlertTesting(true);
    setAlertTestMsg(null);
    try {
      // Build 20 random vectors of the correct width. Random noise on a
      // model trained against a coherent catalog reliably shows severe
      // drift on every feature — perfect for exercising the pipeline.
      const vectors = Array.from({ length: 20 }, () =>
        Array.from({ length: FEATURE_COUNT }, () => Math.random() * 25)
      );
      const r = await api.driftAlertTest(selectedCode, {
        current_vectors: vectors,
        dispatch_min_level: "moderate_drift",
        context: { source: "ui-test" },
      });
      setAlertTestMsg(
        t("alert.test.result", {
          level: r.worst_level,
          dispatched: r.alert_dispatched ? "✓" : "✗",
          reason: r.dispatch_reason,
        })
      );
    } catch (e: any) {
      setAlertTestMsg(t("alert.test.failed", { msg: e.message ?? String(e) }));
    } finally {
      setAlertTesting(false);
    }
  };

  const run = async () => {
    if (!selectedCode) return;
    setBusy(true);
    setErr(null);
    setReport(null);
    try {
      let r: DriftFullOut;
      if (source === "current") {
        r = await api.driftFromCatalogSource(selectedCode, {
          source: "catalog",
          limit: nCurrent,
        });
      } else if (source === "production") {
        r = await api.driftFromCatalogSource(selectedCode, {
          source: "production",
          limit: nCurrent,
        });
      } else {
        // Deterministic-ish random vectors for a smoke test.
        const vectors = Array.from({ length: nCurrent }, () =>
          Array.from({ length: FEATURE_COUNT }, () => Math.random() * 30)
        );
        r = await api.driftFull(selectedCode, vectors);
      }
      setReport(r);
    } catch (e: any) {
      setErr(t("drift.failed", { msg: e.message ?? String(e) }));
    } finally {
      setBusy(false);
    }
  };

  const ingestFromCatalog = async () => {
    setIngesting(true);
    setIngestMsg(null);
    try {
      // Pull the first N recipes from the catalog and push them into
      // production_feature_vector as a demo ingestion.  In a real
      // deployment this would be replaced by an integration reading
      // live production lots.
      const listed = await api.listRecipes({ limit: Math.min(nCurrent, 200) });
      const items = listed.items.map((r) => ({
        recipe_id: r.id,
        source: "production",
        notes: "seeded from catalog",
      }));
      const out = await api.ingestProductionVectors(items);
      setIngestMsg(t("drift.production.ingest_ok", { n: out.accepted }));
      const fresh = await api.listProductionVectors({ limit: 1 });
      setProductionCount(fresh.total);
    } catch (e: any) {
      setIngestMsg(t("drift.production.ingest_failed", { msg: e.message ?? String(e) }));
    } finally {
      setIngesting(false);
    }
  };

  const worstLabel = useMemo(() => {
    if (!report) return null;
    const key = `drift.summary.${report.worst_level}` as const;
    return t(key);
  }, [report, t]);

  return (
    <div className="p-8 space-y-6">
      <header className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">{t("drift.title")}</h1>
          <p className="text-muted-foreground mt-1">{t("drift.subtitle")}</p>
        </div>
      </header>

      <Card>
        <CardHeader>
          <CardTitle>{t("drift.model")}</CardTitle>
        </CardHeader>
        <CardContent>
          {models === null ? (
            <p className="text-muted-foreground text-sm">{t("common.loading")}</p>
          ) : models.length === 0 ? (
            <p className="text-muted-foreground text-sm">{t("drift.no_model")}</p>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-4 gap-3 items-end">
              <div>
                <label className="text-xs text-muted-foreground">{t("drift.model")}</label>
                <select
                  className="w-full h-9 rounded-md border border-input px-2 text-sm bg-white"
                  value={selectedCode}
                  onChange={(e) => setSelectedCode(e.target.value)}
                >
                  {models.map((m) => (
                    <option key={m.property_code} value={m.property_code}>
                      {m.property_code} (n={m.n_samples})
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-xs text-muted-foreground">
                  {t("drift.sample_source")}
                </label>
                <select
                  className="w-full h-9 rounded-md border border-input px-2 text-sm bg-white"
                  value={source}
                  onChange={(e) => setSource(e.target.value as Source)}
                >
                  <option value="current">{t("drift.source.current_recipes")}</option>
                  <option value="production">
                    {t("drift.source.production")} ({productionCount})
                  </option>
                  <option value="random">{t("drift.source.random")}</option>
                </select>
              </div>
              <div>
                <label className="text-xs text-muted-foreground">{t("drift.n_current")}</label>
                <input
                  type="number"
                  min={5}
                  max={500}
                  value={nCurrent}
                  onChange={(e) => setNCurrent(Number(e.target.value))}
                  className="w-full h-9 rounded-md border border-input px-2 text-sm bg-white font-mono"
                />
              </div>
              <div className="flex gap-2">
                <Button onClick={run} disabled={busy}>
                  <PlayCircle className="h-4 w-4" />
                  {busy ? t("drift.running") : t("drift.run")}
                </Button>
                <Button variant="outline" onClick={() => setReport(null)}>
                  <RefreshCw className="h-4 w-4" /> {t("common.refresh")}
                </Button>
              </div>
            </div>
          )}
          {err && <div className="text-sm text-red-700 mt-3">{err}</div>}
          <p className="text-xs text-muted-foreground mt-3">{t("drift.hint")}</p>

          {source === "production" && (
            <div className="mt-3 rounded-md border border-border bg-muted/40 px-4 py-3 space-y-2">
              <div className="text-xs text-muted-foreground">
                {t("drift.production.count", { n: productionCount })}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={ingestFromCatalog}
                  disabled={ingesting || catalogSize === 0}
                >
                  {t("drift.production.ingest_from_current", { n: catalogSize })}
                </Button>
                {ingestMsg && (
                  <span className="text-xs text-muted-foreground">{ingestMsg}</span>
                )}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {report && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <StatCard
              label={t("drift.summary.worst")}
              value={worstLabel ?? report.worst_level}
              variant={
                report.worst_level === "severe_drift"
                  ? "destructive"
                  : report.worst_level === "moderate_drift"
                    ? "warning"
                    : "success"
              }
            />
            <StatCard
              label={t("drift.summary.reference_size")}
              value={String(report.reports[0]?.n_reference ?? 0)}
            />
            <StatCard
              label={t("drift.summary.current_size")}
              value={String(report.reports[0]?.n_current ?? 0)}
            />
          </div>

          <Card>
            <CardHeader>
              <CardTitle>{report.property_code}</CardTitle>
            </CardHeader>
            <CardContent>
              <Table>
                <THead>
                  <TR>
                    <TH>{t("drift.col.feature")}</TH>
                    <TH>{t("drift.col.level")}</TH>
                    <TH className="text-right">{t("drift.col.psi")}</TH>
                    <TH className="text-right">{t("drift.col.ks")}</TH>
                    <TH className="text-right">{t("drift.col.pvalue")}</TH>
                  </TR>
                </THead>
                <TBody>
                  {report.reports
                    .slice()
                    .sort((a, b) => b.psi - a.psi)
                    .map((r) => (
                      <TR key={r.feature_name}>
                        <TD className="font-mono text-xs">{r.feature_name}</TD>
                        <TD>
                          <LevelBadge level={r.level} />
                        </TD>
                        <TD className="text-right font-mono">{fmt(r.psi, 4)}</TD>
                        <TD className="text-right font-mono">{fmt(r.ks_statistic, 4)}</TD>
                        <TD className="text-right font-mono text-muted-foreground">
                          {r.ks_p_value != null ? fmt(r.ks_p_value, 4) : "—"}
                        </TD>
                      </TR>
                    ))}
                </TBody>
              </Table>
            </CardContent>
          </Card>
        </>
      )}

      <Card>
        <CardHeader>
          <CardTitle>{t("alert.section")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          {alertCfg === null ? (
            <p className="text-muted-foreground">{t("common.loading")}</p>
          ) : (
            <>
              <p>
                {alertCfg.webhook_configured
                  ? t("alert.status.configured", { hint: alertCfg.webhook_url_hint })
                  : t("alert.status.not_configured")}
              </p>
              <p className="text-xs text-muted-foreground">
                {t("alert.format", { format: alertCfg.webhook_format })} ·{" "}
                {t("alert.min_severity", { level: alertCfg.min_severity })}
              </p>
              <p className="text-xs text-muted-foreground">{t("alert.test.hint")}</p>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={sendTestAlert}
                  disabled={alertTesting || !selectedCode}
                >
                  {alertTesting ? t("alert.test.running") : t("alert.test.run")}
                </Button>
                {alertTestMsg && (
                  <span className="text-xs text-muted-foreground">{alertTestMsg}</span>
                )}
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function LevelBadge({ level }: { level: string }) {
  const t = useT();
  const label = t(`drift.summary.${level}` as any);
  const v =
    level === "severe_drift"
      ? "destructive"
      : level === "moderate_drift"
        ? "warning"
        : "success";
  return <Badge variant={v}>{label}</Badge>;
}

function StatCard({
  label,
  value,
  variant,
}: {
  label: string;
  value: string;
  variant?: "success" | "warning" | "destructive";
}) {
  const color =
    variant === "success"
      ? "text-green-700"
      : variant === "warning"
        ? "text-amber-700"
        : variant === "destructive"
          ? "text-red-700"
          : "text-foreground";
  return (
    <Card>
      <CardContent className="p-5">
        <div className="text-xs uppercase tracking-wide text-muted-foreground">{label}</div>
        <div className={`text-2xl font-semibold mt-1 ${color}`}>{value}</div>
      </CardContent>
    </Card>
  );
}
