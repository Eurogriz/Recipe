"use client";

import { Languages } from "lucide-react";
import { useI18n, SUPPORTED_LOCALES } from "@/i18n/I18nProvider";
import type { Locale } from "@/i18n/types";
import { cn } from "@/lib/utils";

const LABELS: Record<Locale, string> = { ru: "Русский", en: "English" };
const SHORT: Record<Locale, string> = { ru: "RU", en: "EN" };

export function LanguageSwitcher({ compact = false }: { compact?: boolean }) {
  const { locale, setLocale, t } = useI18n();

  if (compact) {
    return (
      <div className="inline-flex items-center gap-1 rounded-md border border-border bg-white p-0.5">
        {SUPPORTED_LOCALES.map((l) => (
          <button
            key={l}
            onClick={() => setLocale(l)}
            className={cn(
              "px-2 py-1 rounded text-xs font-medium transition-colors",
              l === locale
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:text-foreground"
            )}
            aria-pressed={l === locale}
            aria-label={LABELS[l]}
          >
            {SHORT[l]}
          </button>
        ))}
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <Languages className="h-4 w-4 text-muted-foreground" aria-hidden />
      <span className="text-xs text-muted-foreground">{t("app.language")}</span>
      <div className="inline-flex items-center gap-1 rounded-md border border-border bg-white p-0.5">
        {SUPPORTED_LOCALES.map((l) => (
          <button
            key={l}
            onClick={() => setLocale(l)}
            className={cn(
              "px-2 py-1 rounded text-xs font-medium transition-colors",
              l === locale
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:text-foreground"
            )}
            aria-pressed={l === locale}
          >
            {LABELS[l]}
          </button>
        ))}
      </div>
    </div>
  );
}
