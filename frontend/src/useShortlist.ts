import { useEffect, useState } from "react";

export interface ShortlistItem {
  gsis_id: string;
  name: string;
  position: string | null;
  ppr_pg: number | null;
}

// A per-league watchlist of players, saved in the browser (localStorage) so it
// survives reloads. No backend needed — it's personal to this device.
export function useShortlist(leagueId: string) {
  const key = `waiver-shortlist-${leagueId}`;
  const [items, setItems] = useState<ShortlistItem[]>([]);

  // Load whenever the league changes.
  useEffect(() => {
    try {
      setItems(JSON.parse(localStorage.getItem(key) || "[]"));
    } catch {
      setItems([]);
    }
  }, [key]);

  function persist(next: ShortlistItem[]) {
    setItems(next);
    try {
      localStorage.setItem(key, JSON.stringify(next));
    } catch {
      /* storage may be unavailable (private mode, quota) — ignore */
    }
  }

  const has = (id: string) => items.some((i) => i.gsis_id === id);

  const toggle = (item: ShortlistItem) =>
    persist(
      has(item.gsis_id)
        ? items.filter((i) => i.gsis_id !== item.gsis_id)
        : [...items, item]
    );

  return { items, has, toggle };
}
