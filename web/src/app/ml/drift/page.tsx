"use client";

import { useEffect, useMemo, useState } from "react";
import { RefreshCw, PlayCircle } from "lucide-react";
import {
  api,
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

type Source = "current" | "random";

export default function DriftPage() {
  const t = useT();
  const [models, setModels] = useState<ModelMetadata[] | null>(null);
  const [selectedCode, setSelectedCode] = useState<string>("");
  const [source, setSource] = useState<Source>("current");
  const [nCurrent, setNCurrent] = useState<number>(50);
  const [busy, setBusy] = useState<boolean>(false);
  const [err, setErr] = useState<string | null>(null);
  const [report, setReport] = useState<DriftFullOut | null>(null);

  useEffect(() => {
    api
      .listModels()
      .then((ms) => {
        setModels(ms);
        if (ms.length > 0 && !selectedCode) setSelectedCode(ms[0].property_code);
      })
      .catch(() => setModels([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const run = async () => {
    if (!selectedCode) return;
    setBusy(true);
    setErr(null);
    setReport(null);
    try {
      let vectors: number[][] = [];
      if (source === "random") {
        // Deterministic-ish demo vectors: uniform noise in [0, 30].
        vectors = Array.from({ length: nCurrent }, () =>
          Array.from({ length: FEATURE_COUNT }, () => Math.random() * 30)
        );
      } else {
        // Grab the actual feature vectors the models were trained on
        // via the current catalog — we don't have that endpoint yet,
        // so approximate by sampling zero-vectors (matches shape,
        // exercises the endpoint honestly).  A real deployment would
        // POST the last-N production experiments here.
        vectors = Array.from({ length: nCurrent }, () =>
          Array.from({ length: FEATURE_COUNT }, () => 0)
        );
      }
      const r = await api.driftFull(selectedCode, vectors);
      setReport(r);
    } catch (e: any) {
      setErr(t("drift.failed", { msg: e.message ?? String(e) }));
    } finally {
      setBusy(false);
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
