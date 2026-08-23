import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function fmt(n: number | null | undefined, digits = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const abs = Math.abs(n);
  if (abs !== 0 && (abs < 0.01 || abs >= 100000)) return n.toExponential(digits);
  return n.toFixed(digits);
}

export function timeAgoParts(iso: string | null | undefined): {
  key: "time.s_ago" | "time.m_ago" | "time.h_ago" | "time.d_ago" | null;
  n: number;
} {
  if (!iso) return { key: null, n: 0 };
  const t = new Date(iso).getTime();
  const s = Math.floor((Date.now() - t) / 1000);
  if (s < 60) return { key: "time.s_ago", n: Math.max(0, s) };
  if (s < 3600) return { key: "time.m_ago", n: Math.floor(s / 60) };
  if (s < 86400) return { key: "time.h_ago", n: Math.floor(s / 3600) };
  return { key: "time.d_ago", n: Math.floor(s / 86400) };
}

/** Legacy helper — English only.  Prefer `timeAgoParts` + `useT()`. */
export function timeAgo(iso: string | null | undefined): string {
  const { key, n } = timeAgoParts(iso);
  if (!key) return "—";
  const suffix = { "time.s_ago": "s", "time.m_ago": "m", "time.h_ago": "h", "time.d_ago": "d" }[key];
  return `${n}${suffix} ago`;
}
