"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle,
  Clock,
  Loader2,
  Pause,
  Play,
  RefreshCw,
  XCircle } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

import { apiFetch } from "@/utils/apiFetch";
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || (typeof window !== "undefined" ? (window.location.hostname.includes("ngrok-free.dev") ? `${window.location.protocol}//${window.location.host}` : `${window.location.protocol}//127.0.0.1:6060`) : "http://127.0.0.1:6060");

// Types

type CompanyCycleResult = {
  company_id: number;
  status: string;
  dialer_results?: Record<string, unknown> | null;
  campaign_results?: Record<string, unknown> | null;
  ism_results?: unknown;
  error?: string | null;
  duration_seconds?: number | null;
};

type AutomationStatus = {
  last_cycle_at?: string | null;
  last_cycle_status?: string | null;
  last_cycle_duration_seconds?: number | null;
  last_cycle_company_count?: number | null;
  last_cycle_results?: CompanyCycleResult[];
  total_cycles?: number;
  total_failed_cycles?: number;
  paused?: boolean;
};

// Helpers

function relativeTime(isoString?: string | null): string {
  if (!isoString) return "Never";
  const diff = Math.floor((Date.now() - new Date(isoString).getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function formatDialerResults(results?: Record<string, unknown> | null): string {
  if (!results) return "—";
  const attempted = results["attempted"];
  const skipped = results["skipped"];
  if (attempted !== undefined || skipped !== undefined) {
    return `${attempted ?? 0} attempted, ${skipped ?? 0} skipped`;
  }
  return JSON.stringify(results).slice(0, 80);
}

function formatIsmResults(results?: unknown): string {
  if (results == null) return "—";
  if (Array.isArray(results)) {
    const dispatched = results.filter(
      (r: unknown) =>
        typeof r === "object" && r !== null && (r as Record<string, unknown>)["status"] === "dispatched"
    ).length;
    const skipped = results.length - dispatched;
    return `${dispatched} dispatched, ${skipped} skipped`;
  }
  if (typeof results === "object") {
    const r = results as Record<string, unknown>;
    if (r["dispatched"] !== undefined || r["skipped"] !== undefined) {
      return `${r["dispatched"] ?? 0} dispatched, ${r["skipped"] ?? 0} skipped`;
    }
    return JSON.stringify(r).slice(0, 80);
  }
  return String(results);
}

// Sub-components

function StatCard({
  label, value, accent }: {
  label: string;
  value: React.ReactNode;
  accent?: "red" | "amber" | "emerald";
}) {
  const colors: Record<string, string> = {
    red: "text-red-500",
    amber: "text-amber-500",
    emerald: "text-emerald-500" };
  return (
    <div className="rounded-2xl glass border border-white/40 dark:border-white/10 p-6 flex flex-col gap-1">
      <span className="text-xs font-medium uppercase tracking-wider text-slate-500 dark:text-slate-400">
        {label}
      </span>
      <span
        className={`text-2xl font-bold tabular-nums ${accent ? colors[accent] : "text-slate-800 dark:text-white"}`}
      >
        {value}
      </span>
    </div>
  );
}

function StatusPill({ paused }: { paused?: boolean }) {
  if (paused) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-700 dark:bg-amber-500/10 dark:text-amber-300">
        <Pause className="h-3 w-3" />
        PAUSED
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300">
      <span className="relative flex h-2 w-2">
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
        <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
      </span>
      RUNNING
    </span>
  );
}

function RowStatusBadge({ status }: { status: string }) {
  const s = status.toLowerCase();
  if (s === "success" || s === "ok") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300">
        <CheckCircle className="h-3 w-3" />
        {status}
      </span>
    );
  }
  if (s === "failed" || s === "error") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-700 dark:bg-red-500/10 dark:text-red-300">
        <XCircle className="h-3 w-3" />
        {status}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-600 dark:bg-slate-700 dark:text-slate-300">
      <AlertTriangle className="h-3 w-3" />
      {status}
    </span>
  );
}

function IsmExpandedRows({ results }: { results: unknown[] }) {
  return (
    <div className="mt-2 space-y-1 pl-2 border-l-2 border-violet-300 dark:border-violet-600">
      {results.map((item, i) => {
        const r = item as Record<string, unknown>;
        return (
          <div key={i} className="text-xs text-slate-600 dark:text-slate-400 flex gap-3">
            <span className="font-medium text-slate-800 dark:text-slate-200">
              Lead {String(r["lead_id"] ?? r["id"] ?? i + 1)}
            </span>
            <span>{String(r["status"] ?? "—")}</span>
            {Boolean(r["channel"]) && <span className="italic">{String(r["channel"])}</span>}
            {Boolean(r["error"]) && (
              <span className="text-red-500 truncate max-w-xs">{String(r["error"])}</span>
            )}
          </div>
        );
      })}
    </div>
  );
}

// Main Page

export default function AutomationPage() {
  const { user, sessionTimeout } = useAuth();

  const [status, setStatus] = useState<AutomationStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [dialLimit, setDialLimit] = useState(20);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [runSuccess, setRunSuccess] = useState(false);

  const [actionLoading, setActionLoading] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const [autoRefresh, setAutoRefresh] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const [expandedRows, setExpandedRows] = useState<Set<number>>(new Set());

  // Fetch status

  const fetchStatus = useCallback(async () => {
    if (!user) return;
    try {
      const res = await apiFetch(`${API_BASE}/automation/status`, {
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      const data: AutomationStatus = await res.json();
      setStatus(data);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch status");
    } finally {
      setLoading(false);
    }
  }, [user, sessionTimeout]);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  // Auto-refresh

  useEffect(() => {
    if (autoRefresh) {
      intervalRef.current = setInterval(() => {
        fetchStatus();
      }, 30_000);
    } else {
      if (intervalRef.current) clearInterval(intervalRef.current);
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [autoRefresh, fetchStatus]);

  // Run cycle

  async function handleRunCycle() {
    if (!user) return;
    setRunning(true);
    setRunError(null);
    setRunSuccess(false);
    try {
      const res = await apiFetch(`${API_BASE}/automation/run-cycle?dial_limit=${dialLimit}`, {
        method: "POST"
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error((body as { detail?: string }).detail ?? `Server ${res.status}`);
      }
      setRunSuccess(true);
      await fetchStatus();
      setTimeout(() => setRunSuccess(false), 4000);
    } catch (e) {
      setRunError(e instanceof Error ? e.message : "Cycle failed");
    } finally {
      setRunning(false);
    }
  }

  // Pause / Resume

  async function handlePauseResume() {
    if (!user || !status) return;
    setActionLoading(true);
    setActionError(null);
    const endpoint = status.paused ? "resume" : "pause";
    try {
      const res = await apiFetch(`${API_BASE}/automation/${endpoint}`, {
        method: "POST"
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) throw new Error(`Server ${res.status}`);
      await fetchStatus();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Action failed");
    } finally {
      setActionLoading(false);
    }
  }

  // Row expand

  function toggleRow(companyId: number) {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(companyId)) next.delete(companyId);
      else next.add(companyId);
      return next;
    });
  }

  // Render

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-white to-slate-100 dark:from-slate-950 dark:via-slate-900 dark:to-slate-950 p-6 lg:p-8">
      <div className="mx-auto max-w-7xl space-y-8">

        {/* Header */}
        <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-bold text-slate-800 dark:text-white">
              <Activity className="h-6 w-6 text-violet-500" />
              Automation Worker
            </h1>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              Monitor and control the automation cycle that runs dialing, campaigns, and more.
            </p>
          </div>
          {status && (
            <div className="mt-3 sm:mt-0">
              <StatusPill paused={status.paused} />
            </div>
          )}
        </div>

        {/* Global error */}
        {error && (
          <div className="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-400">
            <XCircle className="h-4 w-4 shrink-0" />
            {error}
          </div>
        )}

        {/* Stats grid */}
        {loading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="h-8 w-8 animate-spin text-violet-500" />
          </div>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
              <StatCard
                label="Total Cycles"
                value={status?.total_cycles ?? 0}
              />
              <StatCard
                label="Failed Cycles"
                value={status?.total_failed_cycles ?? 0}
                accent={(status?.total_failed_cycles ?? 0) > 0 ? "red" : undefined}
              />
              <StatCard
                label="Last Run"
                value={
                  <span className="flex items-center gap-1.5">
                    <Clock className="h-4 w-4 text-slate-400" />
                    {relativeTime(status?.last_cycle_at)}
                  </span>
                }
              />
              <StatCard
                label="Last Duration"
                value={
                  status?.last_cycle_duration_seconds != null
                    ? `${status.last_cycle_duration_seconds.toFixed(1)}s`
                    : "—"
                }
              />
            </div>

            {/* Control bar */}
            <div className="rounded-2xl glass border border-white/40 dark:border-white/10 p-6">
              <div className="flex flex-wrap items-center gap-4">

                {/* Run cycle */}
                <div className="flex items-center gap-2">
                  <label className="text-sm font-medium text-slate-600 dark:text-slate-300">
                    Dial limit
                  </label>
                  <input
                    type="number"
                    min={1}
                    max={500}
                    value={dialLimit}
                    onChange={(e) => setDialLimit(Number(e.target.value))}
                    className="w-20 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40 dark:text-white"
                  />
                  <button
                    onClick={handleRunCycle}
                    disabled={running}
                    className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-violet-500/20 disabled:opacity-60 disabled:cursor-not-allowed"
                  >
                    {running ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Play className="h-4 w-4" />
                    )}
                    Run Cycle Now
                  </button>
                </div>

                {/* Divider */}
                <div className="hidden h-8 w-px bg-slate-200 dark:bg-white/10 sm:block" />

                {/* Pause / Resume */}
                <button
                  onClick={handlePauseResume}
                  disabled={actionLoading || !status}
                  className={`inline-flex items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold shadow disabled:opacity-60 disabled:cursor-not-allowed transition-colors ${
                    status?.paused
                      ? "bg-gradient-to-r from-emerald-500 to-teal-500 text-white shadow-emerald-500/20"
                      : "bg-gradient-to-r from-amber-400 to-orange-400 text-white shadow-amber-500/20"
                  }`}
                >
                  {actionLoading ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : status?.paused ? (
                    <Play className="h-4 w-4" />
                  ) : (
                    <Pause className="h-4 w-4" />
                  )}
                  {status?.paused ? "Resume Worker" : "Pause Worker"}
                </button>

                {/* Divider */}
                <div className="hidden h-8 w-px bg-slate-200 dark:bg-white/10 sm:block" />

                {/* Auto-refresh */}
                <label className="flex cursor-pointer items-center gap-2 text-sm font-medium text-slate-600 dark:text-slate-300">
                  <input
                    type="checkbox"
                    checked={autoRefresh}
                    onChange={(e) => setAutoRefresh(e.target.checked)}
                    className="h-4 w-4 rounded accent-violet-600"
                  />
                  Auto-refresh every 30s
                </label>

                {/* Manual refresh */}
                <button
                  onClick={fetchStatus}
                  className="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-600 dark:border-white/10 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-white/5 inline-flex items-center gap-2"
                >
                  <RefreshCw className="h-4 w-4" />
                  Refresh
                </button>
              </div>

              {/* Inline feedback */}
              {runError && (
                <p className="mt-3 text-sm text-red-600 dark:text-red-400 flex items-center gap-1.5">
                  <XCircle className="h-4 w-4" /> {runError}
                </p>
              )}
              {runSuccess && (
                <p className="mt-3 text-sm text-emerald-600 dark:text-emerald-400 flex items-center gap-1.5">
                  <CheckCircle className="h-4 w-4" /> Cycle completed successfully.
                </p>
              )}
              {actionError && (
                <p className="mt-3 text-sm text-red-600 dark:text-red-400 flex items-center gap-1.5">
                  <XCircle className="h-4 w-4" /> {actionError}
                </p>
              )}
            </div>

            {/* Last cycle results table */}
            <div className="rounded-2xl glass border border-white/40 dark:border-white/10 overflow-hidden">
              <div className="px-6 py-4 border-b border-slate-100 dark:border-white/5">
                <h2 className="text-base font-semibold text-slate-800 dark:text-white flex items-center gap-2">
                  <Activity className="h-4 w-4 text-violet-500" />
                  Last Cycle Results
                  {status?.last_cycle_company_count != null && (
                    <span className="ml-1 rounded-full bg-violet-100 px-2.5 py-0.5 text-xs font-semibold text-violet-700 dark:bg-violet-500/10 dark:text-violet-300">
                      {status.last_cycle_company_count} companies
                    </span>
                  )}
                  {status?.last_cycle_status && (
                    <RowStatusBadge status={status.last_cycle_status} />
                  )}
                </h2>
              </div>

              {!status?.last_cycle_results?.length ? (
                <div className="flex flex-col items-center justify-center py-16 text-slate-400 dark:text-slate-600">
                  <Activity className="h-10 w-10 mb-3 opacity-30" />
                  <p className="text-sm">No cycle results yet. Run a cycle to see results here.</p>
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-slate-50/80 dark:bg-slate-800/50">
                      <tr>
                        {[
                          "Company ID",
                          "Status",
                          "Dialer Results",
                          "Campaign Results",
                          "ISM Results",
                          "Duration",
                          "Error",
                          "",
                        ].map((col) => (
                          <th
                            key={col}
                            className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400"
                          >
                            {col}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100 dark:divide-white/5">
                      {status.last_cycle_results.map((row) => {
                        const isExpanded = expandedRows.has(row.company_id);
                        const ismIsArray = Array.isArray(row.ism_results) && row.ism_results.length > 0;
                        return (
                          <React.Fragment key={row.company_id}>
                            <tr
                              className="group hover:bg-slate-50/60 dark:hover:bg-white/3 transition-colors"
                            >
                              <td className="px-4 py-3 font-mono text-xs font-semibold text-violet-600 dark:text-violet-400">
                                #{row.company_id}
                              </td>
                              <td className="px-4 py-3">
                                <RowStatusBadge status={row.status} />
                              </td>
                              <td className="px-4 py-3 text-slate-600 dark:text-slate-300">
                                {formatDialerResults(row.dialer_results)}
                              </td>
                              <td className="px-4 py-3 text-slate-600 dark:text-slate-300">
                                {row.campaign_results != null
                                  ? JSON.stringify(row.campaign_results).slice(0, 60)
                                  : "—"}
                              </td>
                              <td className="px-4 py-3 text-slate-600 dark:text-slate-300">
                                {formatIsmResults(row.ism_results)}
                              </td>
                              <td className="px-4 py-3 tabular-nums text-slate-500 dark:text-slate-400">
                                {row.duration_seconds != null
                                  ? `${row.duration_seconds.toFixed(1)}s`
                                  : "—"}
                              </td>
                              <td className="px-4 py-3 max-w-[200px]">
                                {row.error ? (
                                  <span
                                    className="text-red-600 dark:text-red-400 text-xs truncate block"
                                    title={row.error}
                                  >
                                    {row.error.length > 60
                                      ? row.error.slice(0, 60) + "…"
                                      : row.error}
                                  </span>
                                ) : (
                                  <span className="text-slate-300 dark:text-slate-600">—</span>
                                )}
                              </td>
                              <td className="px-4 py-3">
                                {ismIsArray && (
                                  <button
                                    onClick={() => toggleRow(row.company_id)}
                                    className="rounded-lg px-2 py-1 text-xs font-medium text-violet-600 dark:text-violet-400 hover:bg-violet-50 dark:hover:bg-violet-500/10 transition-colors"
                                  >
                                    {isExpanded ? "Collapse" : "Expand ISM"}
                                  </button>
                                )}
                              </td>
                            </tr>
                            {isExpanded && ismIsArray && (
                              <tr
                                className="bg-violet-50/40 dark:bg-violet-500/5"
                              >
                                <td colSpan={8} className="px-6 py-3">
                                  <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-violet-500 dark:text-violet-400">
                                    ISM Per-Lead Results
                                  </p>
                                  <IsmExpandedRows
                                    results={row.ism_results as unknown[]}
                                  />
                                </td>
                              </tr>
                            )}
                          </React.Fragment>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
