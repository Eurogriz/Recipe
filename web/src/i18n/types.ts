export type Locale = "ru" | "en";

/**
 * We deliberately type the dictionary as a plain string→string map
 * (rather than a locked union of all keys) so that adding a new key
 * to one language file doesn't immediately break the build.  The
 * fallback logic in `useT` then covers any missing translations.
 */
export type Dict = Record<string, string>;
