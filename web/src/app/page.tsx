"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Beaker,
  Boxes,
  CheckCircle2,
  Cpu,
  FlaskConical,
  Layers,
} from "lucide-react";
import {
  api,
  type CatalogStats,
  type Health,
  type Info,
  type ModelMetadata,
  type CalibrationMatrix,
} from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useT } from "@/i18n/I18nProvider";

export default function DashboardPage() {
  const t = useT();
  const [health, setHealth] = useState<Health | null>(null);
  const [info, setInfo] = useState<Info | null>(null);
  const [stats, setStats] = useState<CatalogStats | null>(null);
  const [models, setModels] = useState<ModelMetadata[] | null>(null);
  const [matrix, setMatrix] = useState<CalibrationMatrix | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      api.health(),
      api.info(),
      api.catalogStats(),
      api.listModels(),
      api.calibrationMatrix(),
    ])
      .then(([h, i, s, m, c]) => {
        setHealth(h);
        setInfo(i);
        setStats(s);
        setModels(m);
        setMatrix(c);
      })
      .catch((e) => setError(e.message ?? String(e)));
  }, []);

  return (
    <div className="p-8 space-y-8">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight">{t("dashboard.title")}</h1>
        <p className="text-muted-foreground mt-1">{t("dashboard.subtitle")}</p>
      </header>

      {error && (
        <div className="rounded-md border border-destructive/30 bg-red-50 text-red-900 px-4 py-3 text-sm">
          {t("common.error_prefix")}: {error}
        </div>
      )}

      <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          title={t("dashboard.stat.api")}
          icon={<CheckCircle2 className="h-5 w-5 text-green-600" />}
          value={health?.status ?? "…"}
          hint={health ? `v${health.version} — ${health.environment}` : ""}
        />
        <StatCard
          title={t("dashboard.stat.recipes")}
          icon={<Beaker className="h-5 w-5 text-primary" />}
          value={stats ? String(stats.total) : "…"}
          hint={
            stats
              ? Object.entries(stats.by_status)
                  .map(([k, v]) => `${k}: ${v}`)
                  .join("  ·  ")
              : ""
          }
        />
        <StatCard
          title={t("dashboard.stat.models")}
          icon={<Cpu className="h-5 w-5 text-indigo-600" />}
          value={models ? String(models.length) : "…"}
          hint={
            models && models.length > 0
              ? t("dashboard.stat.avg_r2", {
                  value: (
                    models.reduce((a, m) => a + m.cv_mean_r2, 0) / models.length
                  ).toFixed(3),
                })
              : t("dashboard.stat.no_models")
          }
        />
        <StatCard
          title={t("dashboard.stat.calibrated")}
          icon={<Layers className="h-5 w-5 text-amber-600" />}
          value={matrix ? `${matrix.n_calibrated}/${matrix.n_models}` : "…"}
          hint={matrix ? t("dashboard.stat.under_covered", { n: matrix.n_under_covered }) : ""}
        />
      </section>

      <section className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>{t("dashboard.sysinfo.title")}</CardTitle>
          </CardHeader>
          <CardContent className="text-sm space-y-2">
            {info ? (
              <>
                <Row k={t("dashboard.sysinfo.name")} v={info.name} />
                <Row k={t("dashboard.sysinfo.version")} v={info.version} />
                <Row k={t("dashboard.sysinfo.environment")} v={info.environment} />
                <Row k={t("dashboard.sysinfo.python")} v={info.python} />
                <Row k={t("dashboard.sysinfo.platform")} v={info.platform} />
                <Row k={t("dashboard.sysinfo.git")} v={info.git_sha} mono />
                <Row k={t("dashboard.sysinfo.build")} v={info.build_date} />
              </>
            ) : (
              <p className="text-muted-foreground">{t("common.loading")}</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{t("dashboard.quick.title")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <QuickLink
              href="/recipes"
              icon={<Beaker className="h-5 w-5 text-primary" />}
              label={t("dashboard.quick.recipes.label")}
              caption={t("dashboard.quick.recipes.caption")}
            />
            <QuickLink
              href="/ml"
              icon={<Cpu className="h-5 w-5 text-indigo-600" />}
              label={t("dashboard.quick.ml.label")}
              caption={t("dashboard.quick.ml.caption")}
            />
            <QuickLink
              href="/ml/jobs"
              icon={<FlaskConical className="h-5 w-5 text-amber-600" />}
              label={t("dashboard.quick.jobs.label")}
              caption={t("dashboard.quick.jobs.caption")}
            />
            <QuickLink
              href="/api/docs"
              external
              icon={<Boxes className="h-5 w-5 text-muted-foreground" />}
              label={t("dashboard.quick.openapi.label")}
              caption={t("dashboard.quick.openapi.caption")}
            />
          </CardContent>
        </Card>
      </section>
    </div>
  );
}

function StatCard({
  title,
  value,
  hint,
  icon,
}: {
  title: string;
  value: string;
  hint?: string;
  icon: React.ReactNode;
}) {
  return (
    <Card>
      <CardContent className="p-5">
        <div className="flex items-start justify-between">
          <div>
            <div className="text-xs uppercase tracking-wide text-muted-foreground">
              {title}
            </div>
            <div className="text-2xl font-semibold mt-1">{value}</div>
            {hint && <div className="text-xs text-muted-foreground mt-1">{hint}</div>}
          </div>
          <div>{icon}</div>
        </div>
      </CardContent>
    </Card>
  );
}

function Row({ k, v, mono }: { k: string; v: string; mono?: boolean }) {
  return (
    <div className="flex justify-between gap-4 border-b border-border/60 py-1.5 last:border-0">
      <span className="text-muted-foreground">{k}</span>
      <span className={mono ? "font-mono text-xs" : ""}>{v}</span>
    </div>
  );
}

function QuickLink({
  href,
  label,
  caption,
  icon,
  external,
}: {
  href: string;
  label: string;
  caption: string;
  icon: React.ReactNode;
  external?: boolean;
}) {
  const A = external ? "a" : Link;
  const extraProps = external ? { target: "_blank", rel: "noreferrer" } : {};
  return (
    <A
      href={href}
      className="flex items-start gap-3 rounded-md border border-border p-3 hover:bg-accent transition-colors"
      {...extraProps}
    >
      <div className="mt-0.5">{icon}</div>
      <div className="flex-1">
        <div className="font-medium text-sm flex items-center gap-2">
          {label}
          {external && <Badge variant="outline">↗</Badge>}
        </div>
        <div className="text-xs text-muted-foreground">{caption}</div>
      </div>
    </A>
  );
}
