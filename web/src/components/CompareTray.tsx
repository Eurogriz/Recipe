"use client";

import Link from "next/link";
import { Diff, X } from "lucide-react";
import { useT } from "@/i18n/I18nProvider";
import {
  COMPARE_MAX_SIZE,
  useCompareSelection,
} from "@/lib/compare-selection";
import { Button } from "@/components/ui/button";

/** Sticky bottom bar that appears whenever the user has picked ≥1
 * recipe for compare.  Rendered globally by the AppShell so a
 * selection made on ``/recipes`` survives navigation to
 * ``/recipes/{id}`` or ``/search``.
 *
 * Hidden until the selection is non-empty — it must not steal
 * layout height on pages the user isn't comparing on.
 */
export function CompareTray() {
  const t = useT();
  const { ids, remove, clear, canCompare } = useCompareSelection();

  if (ids.length === 0) return null;

  return (
    <div
      className="fixed bottom-0 inset-x-0 z-40 border-t border-border bg-white/95 backdrop-blur"
      role="region"
      aria-label={t("compare.tray.aria")}
    >
      <div className="mx-auto max-w-7xl px-4 py-3 flex flex-wrap items-center gap-3">
        <div className="text-xs text-muted-foreground uppercase font-medium">
          {t("compare.tray.selected", {
            n: ids.length,
            max: COMPARE_MAX_SIZE,
          })}
        </div>

        <div className="flex flex-wrap gap-1.5 flex-1 min-w-0">
          {ids.map((id) => (
            <span
              key={id}
              className="inline-flex items-center gap-1 rounded-md border border-border bg-white text-xs font-mono px-2 py-1"
            >
              <span title={id}>{id.slice(0, 8)}…</span>
              <button
                type="button"
                onClick={() => remove(id)}
                className="text-muted-foreground hover:text-destructive transition-colors"
                aria-label={t("compare.tray.remove_aria", { id: id.slice(0, 8) })}
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>

        <div className="flex items-center gap-2 ml-auto">
          <Button variant="outline" size="sm" onClick={clear}>
            {t("compare.tray.clear")}
          </Button>
          {canCompare ? (
            <Link
              href={`/compare?ids=${encodeURIComponent(ids.join(","))}`}
              className="inline-flex items-center gap-1 rounded-md bg-primary text-primary-foreground text-sm px-3 py-1.5 hover:bg-primary/90"
            >
              <Diff className="h-4 w-4" />
              {t("compare.tray.go", { n: ids.length })}
            </Link>
          ) : (
            <span className="text-xs text-muted-foreground italic">
              {t("compare.tray.need_two")}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
