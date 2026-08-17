"use client";
import { useState, useEffect, useCallback } from "react";

export type RecentItem = {
  id: string;
  label: string;
  href?: string;
  icon?: string;
  visitedAt: number;
};

export function useRecentlyViewed(storageKey: string, maxItems = 5) {
  const [items, setItems] = useState<RecentItem[]>([]);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(storageKey);
      if (raw) setItems(JSON.parse(raw));
    } catch {}
  }, [storageKey]);

  const track = useCallback(
    (item: Omit<RecentItem, "visitedAt">) => {
      setItems((prev) => {
        const filtered = prev.filter((i) => i.id !== item.id);
        const next = [{ ...item, visitedAt: Date.now() }, ...filtered].slice(0, maxItems);
        try {
          localStorage.setItem(storageKey, JSON.stringify(next));
        } catch {}
        return next;
      });
    },
    [storageKey, maxItems]
  );

  const clear = useCallback(() => {
    setItems([]);
    try {
      localStorage.removeItem(storageKey);
    } catch {}
  }, [storageKey]);

  return { items, track, clear };
}
