"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { PlayCircle, RefreshCw } from "lucide-react";
import {
  api,
  type CalibrationMatrix,
  type JobRecord,
  type ModelMetadata,
  type SearchResponse,
} from "@/lib/api";
import { fmt } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Table, TBody, THead, TH, TR, TD } from "@/components/ui/table";
import { useT } from "@/i18n/I18nProvider";

export default function MlPage() {
  const t = useT();
  const [models, setModels] = useState<ModelMetadata[] | null>(null);
  const [matrix, setMatrix] = useState<CalibrationMatrix | null>(null);
  const [training, setTraining] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [asyncJob, setAsyncJob] = useState<JobRecord | null>(null);

  const load = () => {
    api.listModels().then(setModels).catch(() => setModels([]));
    api.calibrationMatrix().then(setMatrix).catch(() => setMatrix(null));
  };
  useEffect(load, []);

  const listAllRecipeIds = async (): Promise<string[]> => {
    const r: SearchResponse = await api.listRecipes({ limit: 500 });
    return r.items.map((x) => x.id);
  };

  const doTrain = async () => {
    setTraining(true);
    setMsg(null);
    try {
      const ids = await listAllRecipeIds();
      const r = await api.trainSync({ recipe_ids: ids });
      setMsg(
        t("ml.train.result", {
          trained: r.trained.length,
          skipped: Object.keys(r.skipped).length,
        })
      );
      load();
    } catch (e: any) {
      setMsg(t("ml.train.failed", { msg: e.message ?? String(e) }));
    } finally {
      setTraining(false);
    }
  };

  const doTrainAsync = async () => {
    setMsg(null);
    try {
      const ids = await listAllRecipeIds();
      const j = await api.trainAsync({ recipe_ids: ids });
      setAsyncJob(j);
      setMsg(t("ml.train.submitted", { id: j.id.slice(0, 12) }));
      const poll = async () => {
        for (let i = 0; i < 40; i++) {
          const cur = await api.getJob(j.id);
          setAsyncJob(cur);
          if (["succeeded", "failed", "cancelled"].includes(cur.status)) {
            load();
            return;
          }
          await new Promise((r) => setTimeout(r, 500));
        }
      };
      poll();
    } catch (e: any) {
      setMsg(t("ml.train.submit_failed", { msg: e.message ?? String(e) }));
    }
  };

  return (
    <div className="p-8 space-y-8">
      <header className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">{t("ml.title")}</h1>
          <p className="text-muted-foreground mt-1">{t("ml.subtitle")}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" onClick={load}>
            <RefreshCw className="h-4 w-4" /> {t("common.refresh")}
          </Button>
          <Button onClick={doTrain} disabled={training}>
            <PlayCircle className="h-4 w-4" />{" "}
            {training ? t("ml.train.training") : t("ml.train.sync")}
          </Button>
          <Button variant="secondary" onClick={doTrainAsync}>
            {t("ml.train.async")}
          </Button>
        </div>
      </header>

      {msg && (
        <div className="rounded-md border border-border bg-muted/40 px-4 py-2 text-sm">
          {msg}
          {asyncJob && (
            <span className="ml-2 text-xs text-muted-foreground">
              {t("ml.async.status", { status: asyncJob.status })}
              {asyncJob.duration_seconds != null &&
                ` · ${t("ml.async.duration", { s: asyncJob.duration_seconds.toFixed(2) })}`}
            </span>
          )}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>{t("ml.models.title")}</CardTitle>
        </CardHeader>
        <CardContent>
          {!models ? (
            <p className="text-muted-foreground text-sm">{t("common.loading")}</p>
          ) : models.length === 0 ? (
            <p className="text-muted-foreground text-sm">
              {t("ml.models.empty", { btn: `«${t("ml.train.sync")}»` })}
            </p>
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>{t("ml.models.col.property")}</TH>
                  <TH className="text-right">{t("ml.models.col.samples")}</TH>
                  <TH className="text-right">{t("ml.models.col.cv_r2")}</TH>
                  <TH className="text-right">{t("ml.models.col.cv_std")}</TH>
                  <TH className="text-right">{t("ml.models.col.holdout_r2")}</TH>
                  <TH className="text-right">{t("ml.models.col.holdout_mae")}</TH>
                  <TH className="text-right">{t("ml.models.col.holdout_size")}</TH>
                  <TH>{t("ml.models.col.algorithm")}</TH>
                </TR>
              </THead>
              <TBody>
                {models.map((m) => (
                  <TR key={m.property_code}>
                    <TD className="font-medium">{m.property_code}</TD>
                    <TD className="text-right font-mono">{m.n_samples}</TD>
                    <TD className="text-right font-mono">
                      <R2Badge r2={m.cv_mean_r2} />
                    </TD>
                    <TD className="text-right font-mono text-muted-foreground">
                      ±{m.cv_std_r2.toFixed(3)}
                    </TD>
                    <TD className="text-right font-mono">
                      {m.holdout_r2 != null ? (
                        <R2Badge r2={m.holdout_r2} />
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TD>
                    <TD className="text-right font-mono">
                      {m.holdout_mae != null ? m.holdout_mae.toFixed(3) : "—"}
                    </TD>
                    <TD className="text-right font-mono text-muted-foreground">
                      {m.holdout_size ?? "—"}
                    </TD>
                    <TD className="text-xs text-muted-foreground">{m.algorithm}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>
            {t("ml.calibration.title")}
            {matrix && (
              <span className="ml-2 text-xs font-normal text-muted-foreground">
                {t("ml.calibration.subtitle", {
                  done: matrix.n_calibrated,
                  total: matrix.n_models,
                  under: matrix.n_under_covered,
                })}
              </span>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {!matrix ? (
            <p className="text-muted-foreground text-sm">{t("common.loading")}</p>
          ) : matrix.rows.length === 0 ? (
            <p className="text-muted-foreground text-sm">{t("ml.calibration.empty")}</p>
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>{t("ml.models.col.property")}</TH>
                  <TH className="text-right">{t("ml.models.col.cv_r2")}</TH>
                  <TH>{t("ml.calibration.col.calibrated")}</TH>
                  <TH className="text-right">{t("ml.calibration.col.target")}</TH>
                  <TH className="text-right">{t("ml.calibration.col.empirical")}</TH>
                  <TH className="text-right">{t("ml.calibration.col.gap")}</TH>
                  <TH className="text-right">{t("ml.calibration.col.factor")}</TH>
                </TR>
              </THead>
              <TBody>
                {matrix.rows.map((r) => (
                  <TR key={r.property_code}>
                    <TD className="font-medium">{r.property_code}</TD>
                    <TD className="text-right font-mono">
                      <R2Badge r2={r.cv_mean_r2} />
                    </TD>
                    <TD>
                      <Badge variant={r.has_calibration ? "success" : "outline"}>
                        {r.has_calibration ? t("common.yes") : t("common.no")}
                      </Badge>
                    </TD>
                    <TD className="text-right font-mono">{fmt(r.target_coverage, 2)}</TD>
                    <TD className="text-right font-mono">
                      {fmt(r.empirical_coverage, 3)}
                    </TD>
                    <TD className="text-right font-mono">
                      {r.coverage_gap != null && (
                        <Badge
                          variant={
                            r.coverage_gap >= -0.02
                              ? "success"
                              : r.coverage_gap >= -0.05
                                ? "warning"
                                : "destructive"
                          }
                        >
                          {r.coverage_gap >= 0 ? "+" : ""}
                          {fmt(r.coverage_gap, 3)}
                        </Badge>
                      )}
                      {r.coverage_gap == null && (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TD>
                    <TD className="text-right font-mono">{fmt(r.factor, 3)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("ml.jobs.link")}</CardTitle>
        </CardHeader>
        <CardContent>
          <Link href="/ml/jobs" className="text-sm text-primary underline">
            {t("ml.jobs.open")}
          </Link>
        </CardContent>
      </Card>
    </div>
  );
}

function R2Badge({ r2 }: { r2: number }) {
  const v = r2 >= 0.85 ? "success" : r2 >= 0.6 ? "warning" : "destructive";
  return <Badge variant={v}>{r2.toFixed(3)}</Badge>;
}
