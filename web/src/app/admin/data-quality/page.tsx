"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  CheckCircle2,
  Layers,
  Loader2,
  ShieldAlert,
} from "lucide-react";
import { api, type DataQualityReportOut } from "@/lib/api";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TBody,
  THead,
  TH,
  TR,
  TD,
} from "@/components/ui/table";
import { useT } from "@/i18n/I18nProvider";

/** Data-quality dashboard — visualises `/dashboard/data-quality`.
 *
 * Answers the operator's «which R-rules are hurting me most, and
 * where do I start fixing?» without a manual SQL walk.
 */
export default function DataQualityPage() {
  const t = useT();
  const [report, setReport] = useState<DataQualityReportOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .dashboardDataQuality({ sample_size: 5 })
      .then((r) => setReport(r))
      .catch((e) => setError(e?.message ?? String(e)))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="p-6 space-y-6 max-w-7xl">
      <header>
        <h1 className="text-2xl font-semibold flex items-center gap-2">
          <ShieldAlert className="h-6 w-6 text-primary" />
          {t("dq.title")}
        </h1>
        <p className="text-sm text-muted-foreground pt-1">{t("dq.subtitle")}</p>
      </header>

      {loading ? (
        <div className="flex items-center gap-2 text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t("dq.loading")}
        </div>
      ) : error ? (
        <div className="p-3 rounded-md bg-red-50 text-red-800 text-sm border border-red-200">
          {error}
        </div>
      ) : report ? (
        <>
          <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <StatCard
              icon={<Layers className="h-5 w-5 text-primary" />}
              label={t("dq.stat.total")}
              value={String(report.total_recipes)}
              hint={""}
            />
            <StatCard
              icon={<CheckCircle2 className="h-5 w-5 text-emerald-600" />}
              label={t("dq.stat.clean")}
              value={String(report.n_clean)}
              hint={t("dq.stat.clean.hint", {
                pct: pct(report.n_clean, report.total_recipes),
              })}
            />
            <StatCard
              icon={<AlertTriangle className="h-5 w-5 text-amber-600" />}
              label={t("dq.stat.violations")}
              value={String(report.n_with_violations)}
              hint={t("dq.stat.violations.hint", {
                pct: pct(report.n_with_violations, report.total_recipes),
              })}
            />
            <StatCard
              icon={<CheckCircle2 className="h-5 w-5 text-green-700" />}
              label={t("dq.stat.verified")}
              value={String(
                report.by_status["Verified"] ??
                  Math.round(report.verified_share * report.total_recipes)
              )}
              hint={`${(report.verified_share * 100).toFixed(1)}%`}
            />
          </section>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t("dq.rules.title")}</CardTitle>
              <p className="text-xs text-muted-foreground pt-1">
                {t("dq.rules.subtitle")}
              </p>
            </CardHeader>
            <CardContent className="p-0">
              {report.by_rule.length === 0 ? (
                <div className="p-6 text-sm text-muted-foreground text-center">
                  {t("dq.rules.empty")}
                </div>
              ) : (
                <Table>
                  <THead>
                    <TR>
                      <TH>{t("dq.rules.col.rule")}</TH>
                      <TH className="w-1/2">{t("dq.rules.col.title")}</TH>
                      <TH className="text-right">
                        {t("dq.rules.col.count")}
                      </TH>
                      <TH>{t("dq.rules.col.top_categories")}</TH>
                      <TH>{t("dq.rules.col.samples")}</TH>
                    </TR>
                  </THead>
                  <TBody>
                    {report.by_rule.map((r) => (
                      <TR key={r.rule}>
                        <TD>
                          <Badge variant="destructive">{r.rule}</Badge>
                        </TD>
                        <TD className="text-xs text-muted-foreground">
                          {r.title}
                        </TD>
                        <TD className="text-right font-mono font-semibold">
                          {r.n_recipes}
                        </TD>
                        <TD className="text-xs text-muted-foreground">
                          {Object.entries(r.by_category)
                            .sort(([, a], [, b]) => b - a)
                            .slice(0, 3)
                            .map(([cat, n]) => `${cat} (${n})`)
                            .join(", ")}
                        </TD>
                        <TD className="text-xs">
                          <div className="flex flex-wrap gap-1">
                            {r.sample_recipe_ids.slice(0, 5).map((id) => (
                              <Link
                                key={id}
                                href={`/recipes/${encodeURIComponent(id)}`}
                                className="font-mono text-primary hover:underline"
                              >
                                {id.slice(0, 8)}…
                              </Link>
                            ))}
                          </div>
                        </TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                {t("dq.categories.title")}
              </CardTitle>
              <p className="text-xs text-muted-foreground pt-1">
                {t("dq.categories.subtitle")}
              </p>
            </CardHeader>
            <CardContent className="p-0">
              <Table>
                <THead>
                  <TR>
                    <TH>{t("dq.categories.col.category")}</TH>
                    <TH className="text-right">
                      {t("dq.categories.col.total")}
                    </TH>
                    <TH className="text-right">
                      {t("dq.categories.col.clean")}
                    </TH>
                    <TH className="text-right">
                      {t("dq.categories.col.violations")}
                    </TH>
                    <TH className="text-right">
                      {t("dq.categories.col.verified")}
                    </TH>
                    <TH className="text-right">
                      {t("dq.categories.col.draft")}
                    </TH>
                    <TH>{t("dq.categories.col.top_rules")}</TH>
                    <TH>{t("dq.categories.col.health")}</TH>
                  </TR>
                </THead>
                <TBody>
                  {report.by_category.map((c) => {
                    const health = c.n_total
                      ? c.n_clean / c.n_total
                      : 0;
                    return (
                      <TR key={c.category}>
                        <TD className="font-medium">{c.category}</TD>
                        <TD className="text-right font-mono">{c.n_total}</TD>
                        <TD className="text-right font-mono text-emerald-700">
                          {c.n_clean}
                        </TD>
                        <TD className="text-right font-mono text-amber-800">
                          {c.n_with_violations}
                        </TD>
                        <TD className="text-right font-mono text-green-800">
                          {c.n_verified}
                        </TD>
                        <TD className="text-right font-mono text-muted-foreground">
                          {c.n_draft}
                        </TD>
                        <TD className="text-xs">
                          <div className="flex gap-1 flex-wrap">
                            {c.top_rules.length === 0 ? (
                              <span className="text-muted-foreground">—</span>
                            ) : (
                              c.top_rules.map((r) => (
                                <Badge key={r} variant="warning">
                                  {r}
                                </Badge>
                              ))
                            )}
                          </div>
                        </TD>
                        <TD>
                          <HealthBar value={health} />
                        </TD>
                      </TR>
                    );
                  })}
                </TBody>
              </Table>
            </CardContent>
          </Card>
        </>
      ) : null}
    </div>
  );
}

function StatCard({
  icon,
  label,
  value,
  hint,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <Card>
      <CardContent className="pt-6 pb-4 space-y-1">
        <div className="flex items-center gap-2 text-xs text-muted-foreground uppercase tracking-wide">
          {icon} {label}
        </div>
        <div className="text-3xl font-semibold">{value}</div>
        {hint ? (
          <div className="text-xs text-muted-foreground">{hint}</div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function HealthBar({ value }: { value: number }) {
  // Green when >75% clean, amber 40-75%, red <40%.
  const colour =
    value >= 0.75
      ? "bg-emerald-500"
      : value >= 0.4
        ? "bg-amber-500"
        : "bg-red-500";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 bg-slate-100 rounded overflow-hidden">
        <div
          className={`h-2 ${colour}`}
          style={{ width: `${Math.round(value * 100)}%` }}
        />
      </div>
      <span className="text-xs text-muted-foreground w-10 text-right">
        {Math.round(value * 100)}%
      </span>
    </div>
  );
}

function pct(numerator: number, denominator: number): string {
  if (!denominator) return "0%";
  return `${((numerator / denominator) * 100).toFixed(1)}%`;
}
