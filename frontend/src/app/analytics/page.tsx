"use client";

import { useCallback, useEffect, useState } from "react";
import { Download, Loader2, Plus, Trash2, Bell, Activity, Clock, BarChart2 } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:6060";

// ── Types ──────────────────────────────────────────────────────────────────────

type EngagementSummary = {
  event_counts: Record<string, number>;
  channel_counts: Record<string, number>;
  event_timeline: { day: string; event_type: string; count: number }[];
  quote_status_counts: Record<string, number>;
  call_task_status_counts: Record<string, number>;
  campaign_conversion_trends: {
    campaign_id: number;
    name: string;
    responded: number;
    sent: number;
    conversion_rate: number;
  }[];
  campaign_funnel: { status: string; count: number; percent: number }[];
  meta: Record<string, unknown>;
};

type EngineRow = {
  engine: string;
  rows: number;
  stt_avg: number;
  llm_avg: number;
  tts_avg: number;
  total_avg: number;
  total_min: number;
  total_max: number;
};

type LatencyData = {
  engines: EngineRow[];
  trend: { day: string; engine: string; avg_ms: number; turns: number }[];
  meta: { days: number; total_turns: number; total_calls: number };
};

type Alert = {
  id: number;
  metric: string;
  threshold: number;
  direction: string;
  channel: string;
  enabled: boolean;
  last_triggered_at: string | null;
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtMs(v: number | null | undefined) {
  if (v == null) return "—";
  return `${Math.round(v)} ms`;
}

function fmtDate(v: string | null | undefined) {
  if (!v) return "—";
  return new Date(v).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

function conversionColor(rate: number) {
  if (rate >= 30) return "text-emerald-600 dark:text-emerald-400";
  if (rate >= 10) return "text-amber-600 dark:text-amber-400";
  return "text-red-500 dark:text-red-400";
}

const CALL_STATUS_COLORS: Record<string, string> = {
  completed: "bg-emerald-500",
  failed: "bg-red-500",
  queued: "bg-blue-500",
  pending: "bg-slate-400",
};

const DAYS_OPTIONS = [7, 14, 30, 90];
const TABS = ["Overview", "Latency", "Alerts"] as const;
type Tab = (typeof TABS)[number];

// ── Component ─────────────────────────────────────────────────────────────────

export default function AnalyticsPage() {
  const { token, sessionTimeout } = useAuth();

  const [activeTab, setActiveTab] = useState<Tab>("Overview");
  const [days, setDays] = useState(30);
  const [latencyDays, setLatencyDays] = useState(7);

  // Data
  const [summary, setSummary] = useState<EngagementSummary | null>(null);
  const [latency, setLatency] = useState<LatencyData | null>(null);
  const [alerts, setAlerts] = useState<Alert[]>([]);

  // Loading states
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [latencyLoading, setLatencyLoading] = useState(false);
  const [alertsLoading, setAlertsLoading] = useState(false);
  const [exportLoading, setExportLoading] = useState(false);
  const [quoteExportLoading, setQuoteExportLoading] = useState(false);

  // Alert form
  const [newAlertMetric, setNewAlertMetric] = useState("");
  const [newAlertThreshold, setNewAlertThreshold] = useState<number>(0);
  const [newAlertDirection, setNewAlertDirection] = useState("gte");
  const [newAlertChannel, setNewAlertChannel] = useState("email");
  const [alertSaving, setAlertSaving] = useState(false);

  // Toast
  const [toast, setToast] = useState<string | null>(null);
  const [toastError, setToastError] = useState(false);

  function showToast(msg: string, error = false) {
    setToast(msg);
    setToastError(error);
    setTimeout(() => setToast(null), 3500);
  }

  const authHeaders = { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };

  // ── Fetch functions ──────────────────────────────────────────────────────────

  const fetchSummary = useCallback(async (d: number) => {
    if (!token) return;
    setSummaryLoading(true);
    try {
      const res = await fetch(`${API_BASE}/analytics/engagement-summary?days=${d}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) throw new Error("Failed to load engagement summary");
      setSummary(await res.json());
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Failed to load summary", true);
    } finally {
      setSummaryLoading(false);
    }
  }, [token, sessionTimeout]);

  const fetchLatency = useCallback(async (d: number) => {
    if (!token) return;
    setLatencyLoading(true);
    try {
      const res = await fetch(`${API_BASE}/analytics/latency?days=${d}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) throw new Error("Failed to load latency data");
      setLatency(await res.json());
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Failed to load latency", true);
    } finally {
      setLatencyLoading(false);
    }
  }, [token, sessionTimeout]);

  const fetchAlerts = useCallback(async () => {
    if (!token) return;
    setAlertsLoading(true);
    try {
      const res = await fetch(`${API_BASE}/analytics/alerts`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) throw new Error("Failed to load alerts");
      setAlerts(await res.json());
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Failed to load alerts", true);
    } finally {
      setAlertsLoading(false);
    }
  }, [token, sessionTimeout]);

  useEffect(() => { fetchSummary(days); }, [fetchSummary, days]);
  useEffect(() => { fetchLatency(latencyDays); }, [fetchLatency, latencyDays]);
  useEffect(() => { fetchAlerts(); }, [fetchAlerts]);

  // ── Export Analytics CSV ─────────────────────────────────────────────────────

  function handleExportAnalyticsCSV() {
    const hasEvents = summary && Object.values(summary.event_counts).some((v) => v > 0);
    const hasLatency = latency && latency.engines.length > 0;
    if (!hasEvents && !hasLatency) { showToast("No analytics data available to export", true); return; }
    setExportLoading(true);
    try {
      const rows: string[][] = [];
      const date = new Date().toLocaleDateString("en-IN");

      rows.push([`Analytics Export — ${date}`, "", "", ""]);
      rows.push([]);

      if (summary) {
        rows.push(["=== EVENT COUNTS ==="]);
        rows.push(["Event Type", "Count"]);
        for (const [k, v] of Object.entries(summary.event_counts)) rows.push([k, String(v)]);
        rows.push([]);

        rows.push(["=== CHANNEL BREAKDOWN ==="]);
        rows.push(["Channel", "Count"]);
        for (const [k, v] of Object.entries(summary.channel_counts)) rows.push([k, String(v)]);
        rows.push([]);

        rows.push(["=== CALL TASK STATUS ==="]);
        rows.push(["Status", "Count"]);
        for (const [k, v] of Object.entries(summary.call_task_status_counts)) rows.push([k, String(v)]);
        rows.push([]);

        rows.push(["=== QUOTE STATUS ==="]);
        rows.push(["Status", "Count"]);
        for (const [k, v] of Object.entries(summary.quote_status_counts)) rows.push([k, String(v)]);
        rows.push([]);

        rows.push(["=== CAMPAIGN CONVERSION ==="]);
        rows.push(["Campaign", "Sent", "Responded", "Conversion Rate %"]);
        for (const c of summary.campaign_conversion_trends)
          rows.push([c.name, String(c.sent), String(c.responded), c.conversion_rate.toFixed(1)]);
        rows.push([]);

        rows.push(["=== CAMPAIGN FUNNEL ==="]);
        rows.push(["Stage", "Count", "Percent %"]);
        for (const f of summary.campaign_funnel)
          rows.push([f.status, String(f.count), f.percent.toFixed(1)]);
        rows.push([]);

        rows.push(["=== EVENT TIMELINE ==="]);
        rows.push(["Day", "Event Type", "Count"]);
        for (const t of summary.event_timeline) rows.push([t.day, t.event_type, String(t.count)]);
        rows.push([]);
      }

      if (latency) {
        rows.push(["=== LATENCY BY ENGINE ==="]);
        rows.push(["Engine", "Turns", "Avg STT (ms)", "Avg LLM (ms)", "Avg TTS (ms)", "Avg Total (ms)", "Min (ms)", "Max (ms)"]);
        for (const e of latency.engines)
          rows.push([e.engine, String(e.rows), String(Math.round(e.stt_avg)), String(Math.round(e.llm_avg)), String(Math.round(e.tts_avg)), String(Math.round(e.total_avg)), String(Math.round(e.total_min)), String(Math.round(e.total_max))]);
        rows.push([]);

        rows.push(["=== LATENCY TREND ==="]);
        rows.push(["Day", "Engine", "Avg (ms)", "Turns"]);
        for (const t of latency.trend) rows.push([t.day, t.engine, String(Math.round(t.avg_ms)), String(t.turns)]);
      }

      const csv = rows.map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(",")).join("\n");
      const blob = new Blob([csv], { type: "text/csv" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `analytics_export_${new Date().toISOString().split("T")[0]}.csv`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      showToast("Analytics CSV downloaded");
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Export failed", true);
    } finally {
      setExportLoading(false);
    }
  }

  // ── Export Quote CSV ─────────────────────────────────────────────────────────

  async function handleExportQuoteCSV() {
    if (!token) return;
    const totalQuotes = summary
      ? Object.values(summary.quote_status_counts).reduce((s, v) => s + v, 0)
      : 0;
    if (totalQuotes === 0) { showToast("No quote data available to export", true); return; }
    setQuoteExportLoading(true);
    try {
      const res = await fetch(`${API_BASE}/analytics/quote/export`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) throw new Error("Export failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `quotes_export_${new Date().toISOString().split("T")[0]}.csv`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      showToast("Quotes CSV downloaded");
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Export failed", true);
    } finally {
      setQuoteExportLoading(false);
    }
  }

  // ── Alert actions ────────────────────────────────────────────────────────────

  async function handleCreateAlert() {
    if (!newAlertMetric.trim()) { showToast("Metric is required", true); return; }
    setAlertSaving(true);
    try {
      const res = await fetch(`${API_BASE}/analytics/alerts`, {
        method: "POST",
        headers: authHeaders,
        body: JSON.stringify({
          metric: newAlertMetric.trim(),
          threshold: newAlertThreshold,
          direction: newAlertDirection,
          channel: newAlertChannel,
        }),
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to create alert");
      }
      showToast("Alert created");
      setNewAlertMetric("");
      setNewAlertThreshold(0);
      fetchAlerts();
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Failed to create alert", true);
    } finally {
      setAlertSaving(false);
    }
  }

  async function handleToggleAlert(alert: Alert) {
    const action = alert.enabled ? "disable" : "enable";
    try {
      const res = await fetch(`${API_BASE}/analytics/alerts/${alert.id}/${action}`, {
        method: "PATCH",
        headers: authHeaders,
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) throw new Error(`Failed to ${action} alert`);
      showToast(`Alert ${action}d`);
      fetchAlerts();
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Action failed", true);
    }
  }

  async function handleDeleteAlert(id: number) {
    try {
      const res = await fetch(`${API_BASE}/analytics/alerts/${id}`, {
        method: "DELETE",
        headers: authHeaders,
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) throw new Error("Failed to delete alert");
      showToast("Alert deleted");
      fetchAlerts();
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Delete failed", true);
    }
  }

  // ── Derived stats ────────────────────────────────────────────────────────────

  const totalEvents = summary
    ? Object.values(summary.event_counts).reduce((s, v) => s + v, 0)
    : 0;

  const emailOpens = summary
    ? (summary.event_counts["email_open"] ?? summary.event_counts["open"] ?? 0)
    : 0;

  const linkClicks = summary
    ? (summary.event_counts["email_click"] ?? summary.event_counts["click"] ?? 0)
    : 0;

  const replies = summary
    ? (summary.event_counts["reply"] ?? 0) + (summary.event_counts["whatsapp_reply"] ?? 0)
    : 0;

  const callStatusTotal = summary
    ? Object.values(summary.call_task_status_counts).reduce((s, v) => s + v, 0)
    : 0;

  const sortedEngines = latency
    ? [...latency.engines].sort((a, b) => a.total_avg - b.total_avg)
    : [];

  const latencyTrendMax = latency && latency.trend.length > 0
    ? Math.max(...latency.trend.map((t) => t.avg_ms), 1)
    : 1;

  const totalRows = sortedEngines.reduce((s, e) => s + e.rows, 0);
  const weightedAvg = (field: keyof EngineRow) =>
    totalRows > 0
      ? sortedEngines.reduce((s, e) => s + (e[field] as number) * e.rows, 0) / totalRows
      : null;

  // ── Render ───────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-6 pb-8">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.2em] text-violet-600 dark:text-violet-300">
            Insights
          </p>
          <h1 className="text-4xl font-bold tracking-tight text-slate-900 dark:text-white">
            <span className="gradient-text">Analytics</span>
          </h1>
          <p className="mt-2 text-slate-600 dark:text-slate-400">
            Track engagement, latency, and alert thresholds across your platform.
          </p>
        </div>
        <button
          onClick={handleExportAnalyticsCSV}
          disabled={exportLoading || (!summary && !latency)}
          className="inline-flex shrink-0 items-center gap-2 rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 transition hover:border-violet-300 hover:text-violet-700 disabled:opacity-50 dark:border-white/10 dark:text-slate-200 dark:hover:border-violet-500/40 dark:hover:text-violet-300"
        >
          {exportLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
          Export Analytics CSV
        </button>
      </div>

      {/* Toast */}
      {toast && (
        <div
          className={`rounded-xl border px-4 py-3 text-sm ${
            toastError
              ? "border-red-200 bg-red-50 text-red-700 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-300"
              : "border-violet-200 bg-violet-50 text-violet-700 dark:border-violet-500/20 dark:bg-violet-500/10 dark:text-violet-200"
          }`}
        >
          {toast}
        </div>
      )}

      {/* Tab bar */}
      <div className="flex gap-1 rounded-xl bg-slate-100 p-1 dark:bg-slate-800/50 w-fit">
        {TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-all ${
              activeTab === tab
                ? "bg-white text-slate-900 shadow-sm dark:bg-slate-700 dark:text-white"
                : "text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
            }`}
          >
            {tab === "Overview" && <BarChart2 className="h-3.5 w-3.5" />}
            {tab === "Latency" && <Clock className="h-3.5 w-3.5" />}
            {tab === "Alerts" && <Bell className="h-3.5 w-3.5" />}
            {tab}
          </button>
        ))}
      </div>

      {/* ── OVERVIEW TAB ─────────────────────────────────────────────────────── */}
      {activeTab === "Overview" && (
        <div className="space-y-6">
          {/* Days selector */}
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-slate-500 dark:text-slate-400">Period:</span>
            <div className="flex gap-1 rounded-xl bg-slate-100 p-1 dark:bg-slate-800/50">
              {DAYS_OPTIONS.map((d) => (
                <button
                  key={d}
                  onClick={() => setDays(d)}
                  className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-all ${
                    days === d
                      ? "bg-white text-violet-700 shadow-sm dark:bg-slate-700 dark:text-violet-300"
                      : "text-slate-500 hover:text-slate-700 dark:text-slate-400"
                  }`}
                >
                  {d}d
                </button>
              ))}
            </div>
          </div>

          {summaryLoading ? (
            <div className="flex items-center justify-center py-16 text-slate-500">
              <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading analytics…
            </div>
          ) : (
            <>
              {/* Row 1: Engagement stats */}
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                {[
                  { label: "Total Events", value: totalEvents, icon: Activity, color: "text-violet-600 dark:text-violet-400", bg: "bg-violet-100 dark:bg-violet-500/10" },
                  { label: "Email Opens", value: emailOpens, icon: BarChart2, color: "text-blue-600 dark:text-blue-400", bg: "bg-blue-100 dark:bg-blue-500/10" },
                  { label: "Link Clicks", value: linkClicks, icon: Activity, color: "text-amber-600 dark:text-amber-400", bg: "bg-amber-100 dark:bg-amber-500/10" },
                  { label: "Replies", value: replies, icon: Activity, color: "text-emerald-600 dark:text-emerald-400", bg: "bg-emerald-100 dark:bg-emerald-500/10" },
                ].map(({ label, value, icon: Icon, color, bg }) => (
                  <div key={label} className="rounded-2xl glass border border-white/40 dark:border-white/10 p-6 flex items-center gap-4">
                    <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl ${bg}`}>
                      <Icon className={`h-5 w-5 ${color}`} />
                    </div>
                    <div>
                      <p className="text-2xl font-bold text-slate-900 dark:text-white">{value.toLocaleString()}</p>
                      <p className="text-xs text-slate-500 dark:text-slate-400">{label}</p>
                    </div>
                  </div>
                ))}
              </div>

              {/* Row 2: Campaign performance table */}
              {summary && summary.campaign_conversion_trends.length > 0 && (
                <div className="rounded-2xl glass border border-white/40 dark:border-white/10 p-6 space-y-4">
                  <h2 className="text-base font-semibold text-slate-900 dark:text-white">Campaign Performance</h2>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-slate-200 dark:border-white/10">
                          {["Campaign", "Sent", "Responded", "Conversion Rate"].map((col) => (
                            <th key={col} className="pb-2 pr-4 text-left text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                              {col}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100 dark:divide-white/5">
                        {summary.campaign_conversion_trends.map((c) => (
                          <tr key={c.campaign_id} className="hover:bg-slate-50/60 dark:hover:bg-white/[0.02]">
                            <td className="py-3 pr-4 font-medium text-slate-800 dark:text-slate-100">{c.name}</td>
                            <td className="py-3 pr-4 text-slate-600 dark:text-slate-300">{c.sent.toLocaleString()}</td>
                            <td className="py-3 pr-4 text-slate-600 dark:text-slate-300">{c.responded.toLocaleString()}</td>
                            <td className={`py-3 pr-4 font-semibold ${conversionColor(c.conversion_rate)}`}>
                              {c.conversion_rate.toFixed(1)}%
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Row 3: Call task status breakdown */}
              {summary && Object.keys(summary.call_task_status_counts).length > 0 && (
                <div className="rounded-2xl glass border border-white/40 dark:border-white/10 p-6 space-y-4">
                  <h2 className="text-base font-semibold text-slate-900 dark:text-white">Call Task Status</h2>
                  <div className="space-y-3">
                    {Object.entries(summary.call_task_status_counts).map(([status, count]) => {
                      const pct = callStatusTotal > 0 ? (count / callStatusTotal) * 100 : 0;
                      const barColor = CALL_STATUS_COLORS[status] ?? "bg-slate-400";
                      return (
                        <div key={status} className="space-y-1">
                          <div className="flex items-center justify-between text-xs">
                            <span className="font-medium capitalize text-slate-700 dark:text-slate-200">{status}</span>
                            <span className="text-slate-500 dark:text-slate-400">
                              {count.toLocaleString()} ({pct.toFixed(1)}%)
                            </span>
                          </div>
                          <div className="h-2.5 w-full rounded-full bg-slate-100 dark:bg-slate-800">
                            <div
                              className={`h-2.5 rounded-full ${barColor} transition-all`}
                              style={{ width: `${pct}%` }}
                            />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Row 4: Quote status cards + export */}
              {summary && (
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <h2 className="text-base font-semibold text-slate-900 dark:text-white">Quote Status</h2>
                    <button
                      onClick={handleExportQuoteCSV}
                      disabled={quoteExportLoading}
                      className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-violet-500/20 disabled:opacity-60"
                    >
                      {quoteExportLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                      Export Quote CSV
                    </button>
                  </div>
                  <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                    {Object.entries(summary.quote_status_counts).map(([status, count]) => {
                      const colors: Record<string, { text: string; bg: string }> = {
                        draft: { text: "text-slate-600 dark:text-slate-300", bg: "bg-slate-100 dark:bg-slate-800" },
                        sent: { text: "text-blue-700 dark:text-blue-300", bg: "bg-blue-100 dark:bg-blue-500/10" },
                        accepted: { text: "text-emerald-700 dark:text-emerald-300", bg: "bg-emerald-100 dark:bg-emerald-500/10" },
                        rejected: { text: "text-red-700 dark:text-red-300", bg: "bg-red-100 dark:bg-red-500/10" },
                      };
                      const c = colors[status] ?? colors.draft;
                      return (
                        <div key={status} className={`rounded-2xl border border-white/40 dark:border-white/10 p-5 ${c.bg}`}>
                          <p className={`text-2xl font-bold ${c.text}`}>{count}</p>
                          <p className={`text-xs font-medium capitalize mt-0.5 ${c.text} opacity-80`}>{status}</p>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* ── LATENCY TAB ──────────────────────────────────────────────────────── */}
      {activeTab === "Latency" && (
        <div className="space-y-6">
          {/* Days selector */}
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-slate-500 dark:text-slate-400">Period:</span>
            <div className="flex gap-1 rounded-xl bg-slate-100 p-1 dark:bg-slate-800/50">
              {DAYS_OPTIONS.map((d) => (
                <button
                  key={d}
                  onClick={() => setLatencyDays(d)}
                  className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-all ${
                    latencyDays === d
                      ? "bg-white text-violet-700 shadow-sm dark:bg-slate-700 dark:text-violet-300"
                      : "text-slate-500 hover:text-slate-700 dark:text-slate-400"
                  }`}
                >
                  {d}d
                </button>
              ))}
            </div>
          </div>

          {latencyLoading ? (
            <div className="flex items-center justify-center py-16 text-slate-500">
              <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading latency data…
            </div>
          ) : latency ? (
            <>
              {/* Stat boxes */}
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                {[
                  { label: "Avg STT", value: weightedAvg("stt_avg") },
                  { label: "Avg LLM", value: weightedAvg("llm_avg") },
                  { label: "Avg TTS", value: weightedAvg("tts_avg") },
                  { label: "Avg Total", value: weightedAvg("total_avg") },
                ].map(({ label, value }) => (
                  <div key={label} className="rounded-2xl glass border border-white/40 dark:border-white/10 p-6">
                    <p className="text-2xl font-bold text-slate-900 dark:text-white">{fmtMs(value)}</p>
                    <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">{label}</p>
                  </div>
                ))}
              </div>

              {/* Engine table */}
              {sortedEngines.length > 0 && (
                <div className="rounded-2xl glass border border-white/40 dark:border-white/10 p-6 space-y-4">
                  <h2 className="text-base font-semibold text-slate-900 dark:text-white">Engine Performance</h2>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-slate-200 dark:border-white/10">
                          {["Engine", "Requests", "Avg Latency"].map((col) => (
                            <th key={col} className="pb-2 pr-6 text-left text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                              {col}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100 dark:divide-white/5">
                        {sortedEngines.map((e) => (
                          <tr key={e.engine} className="hover:bg-slate-50/60 dark:hover:bg-white/[0.02]">
                            <td className="py-3 pr-6 font-medium text-slate-800 dark:text-slate-100">{e.engine}</td>
                            <td className="py-3 pr-6 text-slate-600 dark:text-slate-300">{e.rows.toLocaleString()}</td>
                            <td className="py-3 pr-6 font-semibold text-violet-600 dark:text-violet-400">{fmtMs(e.total_avg)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Latency trend sparkline */}
              {latency.trend.length > 0 && (
                <div className="rounded-2xl glass border border-white/40 dark:border-white/10 p-6 space-y-4">
                  <h2 className="text-base font-semibold text-slate-900 dark:text-white">Latency Trend</h2>
                  <div className="relative">
                    {/* Y-axis hint */}
                    <div className="flex items-end gap-2 overflow-x-auto pb-2">
                      {latency.trend.map((point, idx) => {
                        const heightPct = (point.avg_ms / latencyTrendMax) * 100;
                        const barH = Math.max(4, Math.round((heightPct / 100) * 80));
                        return (
                          <div key={idx} className="flex flex-col items-center gap-1 min-w-[40px]">
                            <span className="text-[10px] font-medium text-violet-600 dark:text-violet-400">
                              {Math.round(point.avg_ms)}
                            </span>
                            <div
                              className="w-full rounded-t-md bg-gradient-to-t from-violet-600 to-blue-400 opacity-80"
                              style={{ height: `${barH}px` }}
                            />
                            <span className="text-[9px] text-slate-400 dark:text-slate-500 text-center leading-tight whitespace-nowrap">
                              {new Date(point.day).toLocaleDateString("en-IN", { day: "2-digit", month: "short" })}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                    {/* Baseline */}
                    <div className="mt-1 border-t border-slate-200 dark:border-white/10" />
                    <p className="mt-2 text-right text-xs text-slate-400">
                      Max: {fmtMs(latencyTrendMax)}
                    </p>
                  </div>
                </div>
              )}
            </>
          ) : (
            <div className="rounded-2xl glass border border-dashed border-slate-300 px-6 py-16 text-center text-slate-500 dark:border-white/10">
              No latency data available for this period.
            </div>
          )}
        </div>
      )}

      {/* ── ALERTS TAB ───────────────────────────────────────────────────────── */}
      {activeTab === "Alerts" && (
        <div className="space-y-6">
          {/* New alert form */}
          <div className="rounded-2xl glass border border-white/40 dark:border-white/10 p-6 space-y-4">
            <h2 className="text-base font-semibold text-slate-900 dark:text-white flex items-center gap-2">
              <Plus className="h-4 w-4" /> New Alert
            </h2>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <div className="space-y-1">
                <label className="block text-xs font-medium text-slate-500 dark:text-slate-400">Metric</label>
                <input
                  value={newAlertMetric}
                  onChange={(e) => setNewAlertMetric(e.target.value)}
                  placeholder="e.g. email_open"
                  className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
                />
              </div>
              <div className="space-y-1">
                <label className="block text-xs font-medium text-slate-500 dark:text-slate-400">Threshold</label>
                <input
                  type="number"
                  value={newAlertThreshold}
                  onChange={(e) => setNewAlertThreshold(Number(e.target.value))}
                  className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
                />
              </div>
              <div className="space-y-1">
                <label className="block text-xs font-medium text-slate-500 dark:text-slate-400">Direction</label>
                <select
                  value={newAlertDirection}
                  onChange={(e) => setNewAlertDirection(e.target.value)}
                  className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
                >
                  <option value="gte">≥ (gte)</option>
                  <option value="lte">≤ (lte)</option>
                </select>
              </div>
              <div className="space-y-1">
                <label className="block text-xs font-medium text-slate-500 dark:text-slate-400">Channel</label>
                <select
                  value={newAlertChannel}
                  onChange={(e) => setNewAlertChannel(e.target.value)}
                  className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
                >
                  <option value="email">Email</option>
                  <option value="webhook">Webhook</option>
                  <option value="slack">Slack</option>
                </select>
              </div>
            </div>
            <button
              onClick={handleCreateAlert}
              disabled={alertSaving || !newAlertMetric.trim()}
              className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-violet-500/20 disabled:opacity-60"
            >
              {alertSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              Create Alert
            </button>
          </div>

          {/* Alerts table */}
          {alertsLoading ? (
            <div className="flex items-center justify-center py-16 text-slate-500">
              <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading alerts…
            </div>
          ) : alerts.length === 0 ? (
            <div className="rounded-2xl glass border border-dashed border-slate-300 px-6 py-16 text-center text-slate-500 dark:border-white/10">
              No alerts configured yet. Create one above.
            </div>
          ) : (
            <div className="rounded-2xl glass border border-white/40 dark:border-white/10 overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-200 bg-slate-50/80 dark:border-white/10 dark:bg-slate-800/40">
                      {["Metric", "Threshold", "Direction", "Channel", "Status", "Last Triggered", "Actions"].map(
                        (col) => (
                          <th
                            key={col}
                            className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400"
                          >
                            {col}
                          </th>
                        )
                      )}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 dark:divide-white/5">
                    {alerts.map((alert) => (
                      <tr key={alert.id} className="hover:bg-slate-50/60 dark:hover:bg-white/[0.02] transition-colors">
                        <td className="px-4 py-3 font-mono text-xs font-medium text-slate-800 dark:text-slate-100">
                          {alert.metric}
                        </td>
                        <td className="px-4 py-3 text-slate-700 dark:text-slate-200">{alert.threshold}</td>
                        <td className="px-4 py-3 text-slate-600 dark:text-slate-300">
                          {alert.direction === "gte" ? "≥" : "≤"}
                        </td>
                        <td className="px-4 py-3 capitalize text-slate-600 dark:text-slate-300">{alert.channel}</td>
                        <td className="px-4 py-3">
                          <span
                            className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${
                              alert.enabled
                                ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300"
                                : "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400"
                            }`}
                          >
                            {alert.enabled ? "Enabled" : "Disabled"}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-xs text-slate-500 dark:text-slate-400">
                          {fmtDate(alert.last_triggered_at)}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <button
                              onClick={() => handleToggleAlert(alert)}
                              className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
                                alert.enabled
                                  ? "bg-amber-100 text-amber-700 hover:bg-amber-200 dark:bg-amber-500/10 dark:text-amber-300"
                                  : "bg-emerald-100 text-emerald-700 hover:bg-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-300"
                              }`}
                            >
                              {alert.enabled ? "Disable" : "Enable"}
                            </button>
                            <button
                              onClick={() => handleDeleteAlert(alert.id)}
                              className="rounded-lg p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-500/10"
                            >
                              <Trash2 className="h-4 w-4" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
