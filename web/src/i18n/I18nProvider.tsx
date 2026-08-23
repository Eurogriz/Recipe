"use client";

import * as React from "react";
import { en } from "./dictionaries/en";
import { ru } from "./dictionaries/ru";
import type { Dict, Locale } from "./types";

interface I18nContextValue {
  locale: Locale;
  setLocale: (l: Locale) => void;
  t: (key: string, vars?: Record<string, string | number>) => string;
}

const DICTS: Record<Locale, Dict> = { en, ru };
const STORAGE_KEY = "fw.locale";
const SUPPORTED: Locale[] = ["ru", "en"];

function detectInitialLocale(): Locale {
  if (typeof window === "undefined") return "ru";
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === "ru" || stored === "en") return stored;
  } catch {
    /* ignore */
  }
  const nav = window.navigator.language?.slice(0, 2).toLowerCase();
  return nav === "en" ? "en" : "ru";
}

function interpolate(template: string, vars?: Record<string, string | number>): string {
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (_, key) =>
    key in vars ? String(vars[key]) : `{${key}}`
  );
}

const I18nContext = React.createContext<I18nContextValue | null>(null);

export function I18nProvider({ children }: { children: React.ReactNode }) {
  // Server render is always in the default locale to avoid a hydration
  // mismatch; we then swap to the user's preference on the client.
  const [locale, setLocaleState] = React.useState<Locale>("ru");
  const [hydrated, setHydrated] = React.useState(false);

  React.useEffect(() => {
    setLocaleState(detectInitialLocale());
    setHydrated(true);
  }, []);

  React.useEffect(() => {
    if (!hydrated) return;
    try {
      window.localStorage.setItem(STORAGE_KEY, locale);
    } catch {
      /* ignore */
    }
    // Reflect language change to assistive tech + browser translation UIs.
    if (typeof document !== "undefined") {
      document.documentElement.lang = locale;
    }
  }, [locale, hydrated]);

  const value = React.useMemo<I18nContextValue>(() => {
    const dict = DICTS[locale];
    const fallback = DICTS.en;
    return {
      locale,
      setLocale: setLocaleState,
      t: (key, vars) => interpolate(dict[key] ?? fallback[key] ?? key, vars),
    };
  }, [locale]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nContextValue {
  const ctx = React.useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be used within <I18nProvider>");
  return ctx;
}

export function useT() {
  return useI18n().t;
}

export const SUPPORTED_LOCALES = SUPPORTED;
