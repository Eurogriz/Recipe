"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, Plus, Trash2 } from "lucide-react";
import {
  api,
  type ComponentIn,
  type CreateRecipeBody,
  type StageIn,
} from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useT } from "@/i18n/I18nProvider";
import { fmt } from "@/lib/utils";

/**
 * Minimal but functional recipe wizard.
 *
 * We deliberately keep this to one stage (the API supports multiple,
 * but 95 % of the seed corpus is a single consolidated stage, and
 * the extra UX of multi-stage editing would balloon this file).
 * The stage's components table is the interesting bit: the "Total"
 * indicator turns green when the sum reaches 100 ± 0.5 % and the
 * Submit button only enables under that condition (plus every
 * required text field non-empty).
 */
export default function NewRecipePage() {
  const t = useT();
  const router = useRouter();

  const [category, setCategory] = useState("Краски");
  const [subcategory, setSubcategory] = useState("");
  const [binderType, setBinderType] = useState("");
  const [productClass, setProductClass] = useState("Standard");
  const [intendedUse, setIntendedUse] = useState("");
  const [finish, setFinish] = useState("");
  const [color, setColor] = useState("");
  const [tags, setTags] = useState("");

  const [authors, setAuthors] = useState("");
  const [title, setTitle] = useState("");
  const [year, setYear] = useState<number>(new Date().getFullYear());
  const [publisher, setPublisher] = useState("Noyes Publications");
  const [isbn, setIsbn] = useState("");
  const [page, setPage] = useState("");

  const [stageName, setStageName] = useState("Full production");
  const [equipment, setEquipment] = useState("Disperser");
  const [components, setComponents] = useState<ComponentIn[]>([
    { name: "Water", cas_number: "7732-18-5", function: "vehicle", mass_percent: 50.0, tolerance_percent: 1.0 },
    { name: "Binder", cas_number: "mixture", function: "binder", mass_percent: 30.0, tolerance_percent: 1.0 },
    { name: "TiO2", cas_number: "13463-67-7", function: "pigment", mass_percent: 20.0, tolerance_percent: 1.0 },
  ]);

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successId, setSuccessId] = useState<string | null>(null);

  const totalMass = useMemo(
    () => components.reduce((s, c) => s + (Number(c.mass_percent) || 0), 0),
    [components]
  );
  const totalOk = Math.abs(totalMass - 100.0) < 0.5;

  const requiredFilled =
    category.trim() &&
    subcategory.trim() &&
    binderType.trim() &&
    intendedUse.trim() &&
    authors.trim() &&
    title.trim() &&
    publisher.trim() &&
    components.length >= 1 &&
    components.every((c) => c.name.trim() && c.cas_number.trim() && c.function.trim());

  const canSubmit = Boolean(requiredFilled) && totalOk && !submitting;

  const setComp = (i: number, patch: Partial<ComponentIn>) =>
    setComponents((cs) => cs.map((c, idx) => (idx === i ? { ...c, ...patch } : c)));

  const addComp = () =>
    setComponents((cs) => [
      ...cs,
      {
        name: "",
        cas_number: "mixture",
        function: "additive_other",
        mass_percent: 0.0,
        tolerance_percent: 0.5,
      },
    ]);

  const removeComp = (i: number) =>
    setComponents((cs) => cs.filter((_, idx) => idx !== i));

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const body: CreateRecipeBody = {
        category,
        subcategory,
        binder_type: binderType,
        product_class: productClass,
        intended_use: intendedUse,
        finish,
        color,
        tags: tags
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        stages: [
          {
            stage_number: 1,
            name: stageName || "Full production",
            description: "",
            components,
            process: { equipment: equipment || "Disperser" },
          } satisfies StageIn,
        ],
        primary_source: {
          authors,
          title,
          year: Number(year),
          publisher,
          isbn: isbn || null,
          page_or_formula: page,
        },
        cross_references: [],
      };
      const created = await api.createRecipe(body);
      setSuccessId(created.id);
      // Bounce to the new recipe page after a short delay so the toast
      // is legible before navigation.
      setTimeout(() => {
        router.push(`/recipes/${encodeURIComponent(created.id)}`);
      }, 900);
    } catch (e: any) {
      // Pull out FastAPI validation detail if present.
      const detail = e?.detail?.detail ?? e?.detail;
      const msg =
        typeof detail === "string"
          ? detail
          : detail
            ? JSON.stringify(detail)
            : e?.message ?? String(e);
      setError(t("wizard.failed", { msg }));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="p-8 space-y-6 max-w-5xl">
      <Link
        href="/recipes"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" /> {t("recipe.back")}
      </Link>

      <header>
        <h1 className="text-3xl font-semibold tracking-tight">{t("wizard.title")}</h1>
        <p className="text-muted-foreground mt-1">{t("wizard.subtitle")}</p>
      </header>

      {successId && (
        <div className="rounded-md border border-green-300 bg-green-50 text-green-900 px-4 py-3 text-sm">
          {t("wizard.created", { id: successId })}
        </div>
      )}
      {error && (
        <div className="rounded-md border border-destructive/30 bg-red-50 text-red-900 px-4 py-3 text-sm">
          {error}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>{t("wizard.section.meta")}</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <Labeled label={t("wizard.f.category") + " *"}>
            <Input value={category} onChange={(e) => setCategory(e.target.value)} />
          </Labeled>
          <Labeled label={t("wizard.f.subcategory") + " *"}>
            <Input value={subcategory} onChange={(e) => setSubcategory(e.target.value)} />
          </Labeled>
          <Labeled label={t("wizard.f.binder_type") + " *"}>
            <Input value={binderType} onChange={(e) => setBinderType(e.target.value)} />
          </Labeled>
          <Labeled label={t("wizard.f.product_class")}>
            <select
              className="w-full h-9 rounded-md border border-input px-3 text-sm bg-white"
              value={productClass}
              onChange={(e) => setProductClass(e.target.value)}
            >
              {["Economy", "Standard", "Premium"].map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </Labeled>
          <Labeled label={t("wizard.f.intended_use") + " *"} className="md:col-span-2">
            <Input value={intendedUse} onChange={(e) => setIntendedUse(e.target.value)} />
          </Labeled>
          <Labeled label={t("wizard.f.finish")}>
            <Input value={finish} onChange={(e) => setFinish(e.target.value)} />
          </Labeled>
          <Labeled label={t("wizard.f.color")}>
            <Input value={color} onChange={(e) => setColor(e.target.value)} />
          </Labeled>
          <Labeled label={t("wizard.f.tags")} className="md:col-span-2">
            <Input
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="interior, matte, low-voc"
            />
          </Labeled>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("wizard.section.source")}</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <Labeled label={t("wizard.f.authors") + " *"}>
            <Input value={authors} onChange={(e) => setAuthors(e.target.value)} />
          </Labeled>
          <Labeled label={t("wizard.f.title") + " *"}>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} />
          </Labeled>
          <Labeled label={t("wizard.f.year")}>
            <Input
              type="number"
              value={year}
              onChange={(e) => setYear(Number(e.target.value) || year)}
            />
          </Labeled>
          <Labeled label={t("wizard.f.publisher") + " *"}>
            <Input value={publisher} onChange={(e) => setPublisher(e.target.value)} />
          </Labeled>
          <Labeled label={t("wizard.f.isbn")}>
            <Input value={isbn} onChange={(e) => setIsbn(e.target.value)} />
          </Labeled>
          <Labeled label={t("wizard.f.page")}>
            <Input value={page} onChange={(e) => setPage(e.target.value)} />
          </Labeled>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("wizard.section.composition")}</CardTitle>
          <p className="text-xs text-muted-foreground">{t("wizard.func.help")}</p>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <Labeled label={t("wizard.stage.name")}>
              <Input value={stageName} onChange={(e) => setStageName(e.target.value)} />
            </Labeled>
            <Labeled label={t("wizard.stage.equipment")}>
              <Input value={equipment} onChange={(e) => setEquipment(e.target.value)} />
            </Labeled>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs uppercase text-muted-foreground border-b border-border">
                  <th className="text-left py-2 pr-2">{t("wizard.comp.name")}</th>
                  <th className="text-left py-2 pr-2">{t("wizard.comp.cas")}</th>
                  <th className="text-left py-2 pr-2">{t("wizard.comp.function")}</th>
                  <th className="text-right py-2 pr-2">{t("wizard.comp.mass")}</th>
                  <th className="text-right py-2 pr-2">{t("wizard.comp.tolerance")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {components.map((c, i) => (
                  <tr key={i} className="border-b border-border/50">
                    <td className="py-1 pr-2">
                      <Input
                        value={c.name}
                        onChange={(e) => setComp(i, { name: e.target.value })}
                      />
                    </td>
                    <td className="py-1 pr-2 w-40">
                      <Input
                        className="font-mono text-xs"
                        value={c.cas_number}
                        onChange={(e) => setComp(i, { cas_number: e.target.value })}
                      />
                    </td>
                    <td className="py-1 pr-2 w-44">
                      <Input
                        value={c.function}
                        onChange={(e) => setComp(i, { function: e.target.value })}
                      />
                    </td>
                    <td className="py-1 pr-2 w-24 text-right">
                      <Input
                        type="number"
                        step="0.01"
                        className="font-mono text-right"
                        value={c.mass_percent}
                        onChange={(e) =>
                          setComp(i, { mass_percent: Number(e.target.value) || 0 })
                        }
                      />
                    </td>
                    <td className="py-1 pr-2 w-24 text-right">
                      <Input
                        type="number"
                        step="0.01"
                        className="font-mono text-right"
                        value={c.tolerance_percent ?? 0}
                        onChange={(e) =>
                          setComp(i, { tolerance_percent: Number(e.target.value) || 0 })
                        }
                      />
                    </td>
                    <td className="py-1 pl-2 w-10 text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => removeComp(i)}
                        disabled={components.length <= 1}
                        title={t("wizard.comp.remove")}
                      >
                        <Trash2 className="h-4 w-4 text-red-500" />
                      </Button>
                    </td>
                  </tr>
                ))}
                <tr className="border-t border-border">
                  <td colSpan={3} className="pt-2 text-right font-medium">
                    {t("common.total")}:
                  </td>
                  <td className="pt-2 text-right font-mono font-semibold">
                    <Badge variant={totalOk ? "success" : "warning"}>
                      {fmt(totalMass, 3)} %
                    </Badge>
                  </td>
                  <td colSpan={2} className="pt-2 pl-2 text-xs text-muted-foreground">
                    {totalOk ? t("wizard.total.ok") : t("wizard.total.warn")}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <Button variant="outline" onClick={addComp}>
            <Plus className="h-4 w-4" /> {t("wizard.comp.add")}
          </Button>
        </CardContent>
      </Card>

      <div className="flex items-center gap-3">
        <Button onClick={submit} disabled={!canSubmit}>
          {submitting ? t("wizard.submitting") : t("wizard.submit")}
        </Button>
        <Link href="/recipes" className="text-sm text-muted-foreground hover:underline">
          {t("wizard.cancel")}
        </Link>
      </div>
    </div>
  );
}

function Labeled({
  label,
  children,
  className,
}: {
  label: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={className}>
      <label className="text-xs text-muted-foreground block mb-1">{label}</label>
      {children}
    </div>
  );
}
