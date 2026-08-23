"use client";

import { useCallback, useEffect, useState } from "react";

/** localStorage key. Namespaced so different apps on the same
 *  origin don't collide. */
const STORAGE_KEY = "fw:compare-selection";

/** Compare endpoint accepts 2..4 recipes; keeping N here so the UI
 *  can disable the "add" button when full. */
export const COMPARE_MAX_SIZE = 4;

type Listener = (ids: string[]) => void;

/** In-memory mirror + cross-tab / cross-component pub-sub.
 *
 * We could use React Context but the selection is a genuinely
 * cross-page piece of state (recipes list, recipe detail, compare
 * page all read/write it) and Context would force us to lift the
 * provider up to the AppShell, which then re-renders on every
 * tick.  A tiny local store + one custom hook is simpler and
 * matches how the rest of the app handles cross-page state
 * (i18n also lives in a Provider but doesn't mutate on tick).
 */
class SelectionStore {
  private ids: string[] = [];
  private listeners = new Set<Listener>();
  private hydrated = false;

  private hydrate(): void {
    if (this.hydrated || typeof window === "undefined") return;
    this.hydrated = true;
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        this.ids = parsed.filter((x) => typeof x === "string").slice(0, COMPARE_MAX_SIZE);
      }
    } catch {
      // Corrupt storage — start clean, don't crash render.
      this.ids = [];
    }
    // Listen to changes in OTHER tabs so a user comparing across
    // windows sees a consistent selection.
    window.addEventListener("storage", (e) => {
      if (e.key !== STORAGE_KEY) return;
      try {
        const parsed = e.newValue ? JSON.parse(e.newValue) : [];
        this.ids = Array.isArray(parsed) ? parsed.slice(0, COMPARE_MAX_SIZE) : [];
        this.emit();
      } catch {
        /* ignore */
      }
    });
  }

  private persist(): void {
    if (typeof window === "undefined") return;
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(this.ids));
    } catch {
      // localStorage quota / disabled — selection lives in memory
      // for the current tab only.  Acceptable.
    }
  }

  private emit(): void {
    // Copy the array so listeners can compare-and-set safely.
    const snapshot = [...this.ids];
    for (const l of this.listeners) l(snapshot);
  }

  subscribe(l: Listener): () => void {
    this.hydrate();
    this.listeners.add(l);
    return () => {
      this.listeners.delete(l);
    };
  }

  getSnapshot(): string[] {
    this.hydrate();
    return this.ids;
  }

  add(id: string): boolean {
    if (!id || this.ids.includes(id)) return false;
    if (this.ids.length >= COMPARE_MAX_SIZE) return false;
    this.ids = [...this.ids, id];
    this.persist();
    this.emit();
    return true;
  }

  remove(id: string): void {
    if (!this.ids.includes(id)) return;
    this.ids = this.ids.filter((x) => x !== id);
    this.persist();
    this.emit();
  }

  toggle(id: string): boolean {
    if (this.ids.includes(id)) {
      this.remove(id);
      return false;
    }
    return this.add(id);
  }

  clear(): void {
    if (this.ids.length === 0) return;
    this.ids = [];
    this.persist();
    this.emit();
  }
}

const store = new SelectionStore();

/** React hook for reading + mutating the compare selection.
 *
 * Returns a stable object with:
 *   ``ids`` — current selection (up to COMPARE_MAX_SIZE);
 *   ``has(id)`` — quick membership check for card highlighting;
 *   ``toggle(id)`` — flip membership; returns the final state;
 *   ``remove(id)`` — drop one;
 *   ``clear()`` — drop all.
 *
 * Subscribes to cross-tab changes automatically via the ``storage``
 * event, so a click in tab A updates the tray in tab B.
 */
export function useCompareSelection() {
  // Initialise from store's current snapshot to avoid a
  // "no ids" flash on first render when localStorage already has data.
  const [ids, setIds] = useState<string[]>(() => store.getSnapshot());

  useEffect(() => {
    setIds(store.getSnapshot());
    return store.subscribe(setIds);
  }, []);

  const has = useCallback((id: string) => ids.includes(id), [ids]);
  const toggle = useCallback((id: string) => store.toggle(id), []);
  const remove = useCallback((id: string) => store.remove(id), []);
  const add = useCallback((id: string) => store.add(id), []);
  const clear = useCallback(() => store.clear(), []);

  return {
    ids,
    has,
    toggle,
    remove,
    add,
    clear,
    isFull: ids.length >= COMPARE_MAX_SIZE,
    canCompare: ids.length >= 2,
  };
}
