"use client";

/**
 * Lightweight beacon for SLO #2 (login → dashboard p95).
 *
 * Posts a single FMP timing per page-load to /metrics/ui-latency.  Cookie-
 * authed via apiFetch.  Best-effort — silently swallows failures so the
 * user never sees a beacon-related error.
 */

import { apiFetch } from "@/utils/apiFetch";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || (typeof window !== "undefined" ? (window.location.hostname.includes("ngrok-free.dev") ? `${window.location.protocol}//${window.location.host}` : `${window.location.protocol}//127.0.0.1:6060`) : "http://127.0.0.1:6060");

let _reported = false;

export function reportUiLatency(route: string, event: "ttfb" | "fmp" | "tti" = "fmp"): void {
  if (typeof window === "undefined") return;
  if (_reported) return;
  _reported = true;

  // Use Navigation Timing if available; falls back to performance.now() since
  // page start.  Either way: a coarse-grained "how long until the user sees
  // useful pixels" number.
  let durationMs: number;
  try {
    const navEntry = performance.getEntriesByType("navigation")[0] as
      | PerformanceNavigationTiming
      | undefined;
    if (navEntry) {
      // domContentLoadedEventEnd ≈ FMP for a CSR app.
      const fmp = navEntry.domContentLoadedEventEnd || navEntry.loadEventEnd || 0;
      durationMs = Math.round(fmp);
    } else {
      durationMs = Math.round(performance.now());
    }
  } catch {
    durationMs = Math.round(performance.now());
  }

  // Fire-and-forget. apiFetch handles cookie + CSRF + Content-Type.
  apiFetch(`${API_BASE}/metrics/ui-latency`, {
    method: "POST",
    body: JSON.stringify({ route, event, duration_ms: Math.max(0, durationMs) }),
  }).catch(() => {
    /* swallow — beacons are best-effort */
  });
}
