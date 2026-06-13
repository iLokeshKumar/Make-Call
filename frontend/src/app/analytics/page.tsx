"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  Activity, BarChart2, Bell, Brain, Clock, Download, Loader2,
  Mic, Phone, Plus, RefreshCw, Trash2, TrendingDown, TrendingUp, Volume2, Zap } from "lucide-react";
import clsx from "clsx";
import { useAuth } from "@/context/AuthContext";

import { apiFetch } from "@/utils/apiFetch";
import CampaignStatusTimelineChart from "@/components/analytics/CampaignStatusTimelineChart";
import CampaignConversionChart from "@/components/analytics/CampaignConversionChart";
import FunnelChart from "@/components/analytics/FunnelChart";
import HorizontalMetricBars from "@/components/analytics/HorizontalMetricBars";
import LatencyTrendChart from "@/components/analytics/LatencyTrendChart";
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || (typeof window !== "undefined" ? (window.location.hostname.includes("ngrok-free.dev") ? `${window.location.protocol}//${window.location.host}` : `${window.location.protocol}//127.0.0.1:6060`) : "http://127.0.0.1:6060");

type EngagementSummary = {
  event_counts: Record<string, number>;
  channel_counts: Record<string, number>;
  event_timeline: { day: string; event_type: string; count: number }[];
  quote_status_counts: Record<string, number>;
  call_task_status_counts: Record<string, number>;
  campaign_conversion_trends: { campaign_id: number; name: string; responded: number; sent: number; conversion_rate: number }[];
  campaign_status_over_time: { day: string; status: string; count: number }[];
  campaign_funnel: { status: string; count: number; percent: number }[];
  meta: Record<string, unknown>;
};

type EngineRow  = { engine: string; rows: number; stt_avg: number; llm_avg: number; tts_avg: number; total_avg: number; total_min: number; total_max: number; total_p95?: number; llm_p95?: number };
type CallRow    = { id: number; engine: string; stt_model: string; llm_model: string; tts_model: string; turns: number; stt_avg: number; llm_avg: number; tts_avg: number; total_avg: number; total_min: number; total_max: number };
type ModelRow   = { model: string; provider: string; rows: number; avg: number; min: number; max: number };
type TrendPoint = { day: string; engine: string; avg_ms: number; turns: number };
type LatencyData = {
  engines: EngineRow[];
  interactions: CallRow[];
  stt_models: ModelRow[];
  llm_models: ModelRow[];
  tts_models: ModelRow[];
  trend: TrendPoint[];
  meta: { days: number; total_turns: number; total_calls: number };
};

type Alert = { id: number; metric: string; threshold: number; direction: string; channel: string; enabled: boolean; last_triggered_at: string | null };

const fms = (v: number) => v >= 1000 ? `${(v / 1000).toFixed(2)}s` : `${Math.round(v)}ms`;
const fmtDate = (v: string | null | undefined) => v ? new Date(v).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }) : "—";

const ENGINE_PALETTE: Record<string, string> = {
  "deepgram-cerebras-cartesia":  "#34d399",
  "deepgram-mistral-cartesia":   "#60a5fa",
  "deepgram-mistral-deepgram":   "#818cf8",
  "sarvam-cerebras-sarvam":      "#fbbf24",
  "cartesia-mistral-cartesia":   "#f87171",
  "sarvam-mistral-sarvam":       "#fb923c",
  "deepgram-openrouter-cartesia":"#a78bfa",
  "cartesia-openrouter-cartesia":"#e879f9" };
const engineColor = (e: string) => ENGINE_PALETTE[e] ?? "#94a3b8";

const CALL_STATUS_COLORS: Record<string, string> = {
  // terminal
  completed:   "bg-emerald-500",
  failed:      "bg-red-500",
  error:       "bg-red-400",
  busy:        "bg-orange-500",
  no_answer:   "bg-amber-500",
  cancelled:   "bg-slate-400",
  low_balance: "bg-pink-500",
  stopped:     "bg-slate-500",
  // active
  in_progress: "bg-green-500",
  connected:   "bg-green-500",
  ringing:     "bg-yellow-400",
  initiated:   "bg-indigo-400",
  // pre-call / queued
  queued:      "bg-blue-500",
  scheduled:   "bg-cyan-500",
  prepared:    "bg-teal-500",
  dialing:     "bg-violet-500",
  wrapup:      "bg-purple-400",
  // default
  pending:     "bg-slate-400",
};

function Pulse() {
  return (
    <span className="relative inline-flex h-2 w-2">
      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
      <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
    </span>
  );
}

function KpiCard({ label, value, sub, color, icon: Icon }: { label: string; value: string; sub?: string; color: string; icon: React.ElementType }) {
  return (
    <div className="glass rounded-2xl p-5 border border-white/10" style={{ borderLeftColor: color, borderLeftWidth: 3 }}>
      <div className="flex items-start justify-between">
        <div>
          <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest">{label}</p>
          <p className="mt-2 text-2xl font-bold leading-none" style={{ color }}>{value}</p>
          {sub && <p className="text-[10px] text-slate-500 mt-1 truncate max-w-[140px]">{sub}</p>}
        </div>
        <div className="p-2 rounded-xl" style={{ background: `${color}18` }}>
          <Icon className="h-5 w-5" style={{ color }} />
        </div>
      </div>
    </div>
  );
}

function StackBar({ stt, llm, tts, total }: { stt: number; llm: number; tts: number; total: number }) {
  if (!total) return null;
  const pct = (v: number) => `${Math.max((v / total) * 100, 2).toFixed(1)}%`;
  return (
    <div className="mt-3">
      <div className="flex h-[5px] rounded-full overflow-hidden gap-[2px]">
        <div style={{ width: pct(stt), background: "#818cf8" }} />
        <div style={{ width: pct(llm), background: "#34d399" }} />
        <div style={{ width: pct(tts), background: "#fb923c" }} />
      </div>
      <div className="flex gap-4 mt-1.5">
        {([["STT", "#818cf8", stt], ["LLM", "#34d399", llm], ["TTS", "#fb923c", tts]] as const).map(([k, c, v]) => (
          <span key={k} className="text-[10px] font-mono" style={{ color: c }}>
            {k} {fms(v as number)} <span className="opacity-40">({((v as number) / total * 100).toFixed(0)}%)</span>
          </span>
        ))}
      </div>
    </div>
  );
}

function HorizBar({ value, max, color }: { value: number; max: number; color: string }) {
  return (
    <div className="flex items-center gap-2 mt-1">
      <div className="flex-1 h-[4px] rounded-full bg-white/10 overflow-hidden">
        <div className="h-full rounded-full transition-all duration-700"
          style={{ width: `${Math.max((value / (max || 1)) * 100, 2)}%`, background: color }} />
      </div>
      <span className="font-mono text-[10px] w-14 text-right" style={{ color }}>{fms(value)}</span>
    </div>
  );
}

function ModelCard({ title, icon: Icon, accent, models }: { title: string; icon: React.ElementType; accent: string; models: ModelRow[] }) {
  const maxVal = models.at(-1)?.avg || 1;
  return (
    <div className="glass rounded-2xl border border-white/10 p-5">
      <div className="flex items-center gap-2 mb-4">
        <Icon className="h-4 w-4" style={{ color: accent }} />
        <p className="text-xs uppercase tracking-widest font-semibold" style={{ color: accent }}>{title}</p>
      </div>
      {models.length === 0 && <p className="text-slate-600 text-xs">No data</p>}
      {models.map((m, i) => {
        const col = i === 0 ? "#34d399" : i === 1 ? "#fbbf24" : "#f87171";
        return (
          <div key={m.model} className="mb-4 pb-4 border-b border-white/5 last:border-0 last:pb-0">
            <div className="flex justify-between items-start">
              <div>
                <p className="text-[10px]" style={{ color: col }}>#{i + 1}</p>
                <p className="font-semibold text-slate-200 text-sm mt-0.5 truncate max-w-[140px]">{m.model}</p>
                <p className="text-[10px] text-slate-500">{m.provider} · {m.rows} turns</p>
              </div>
              <p className="text-xl font-black" style={{ color: col }}>{fms(m.avg)}</p>
            </div>
            <HorizBar value={m.avg} max={maxVal} color={col} />
            <p className="text-[10px] text-slate-600 mt-1">min {fms(m.min)} · max {fms(m.max)}</p>
          </div>
        );
      })}
    </div>
  );
}

function DoDSummary({ trend }: { trend: TrendPoint[] }) {
  const map: Record<string, Record<string, number>> = {};
  for (const t of trend) {
    if (!map[t.engine]) map[t.engine] = {};
    map[t.engine][t.day] = t.avg_ms;
  }
  const days = [...new Set(trend.map(t => t.day))].sort();
  if (days.length < 2) return null;
  const items: { engine: string; from: number; to: number; pct: number }[] = [];
  for (const e of Object.keys(map)) {
    const latest = days.slice(-2);
    const from = map[e][latest[0]]; const to = map[e][latest[1]];
    if (from && to) items.push({ engine: e, from, to, pct: ((to - from) / from) * 100 });
  }
  if (!items.length) return null;
  items.sort((a, b) => a.pct - b.pct);
  return (
    <div>
      <p className="text-[10px] text-slate-500 uppercase tracking-widest mb-3">Latest day-over-day · {days.at(-2)} → {days.at(-1)}</p>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {items.map(item => {
          const improved = item.pct < 0;
          const col = improved ? "#34d399" : "#f87171";
          return (
            <div key={item.engine} className="glass rounded-xl px-4 py-3 border border-white/10"
              style={{ borderLeftColor: engineColor(item.engine), borderLeftWidth: 3 }}>
              <p className="text-[10px] font-mono text-slate-400">{item.engine}</p>
              <div className="flex items-center justify-between mt-1">
                <span className="text-sm text-slate-400">{fms(item.from)} → {fms(item.to)}</span>
                <span className="font-bold text-sm flex items-center gap-1" style={{ color: col }}>
                  {improved ? "▼" : "▲"} {Math.abs(item.pct).toFixed(1)}%
                  {improved ? <TrendingDown className="h-3.5 w-3.5" /> : <TrendingUp className="h-3.5 w-3.5" />}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

type CallPerformance = {
  days: number;
  connect_rate_pct: number;
  avg_talk_time_seconds: number;
  total_with_outcome: number;
  connected_calls: number;
  outcome_counts: Record<string, number>;
};

type CallConversion = {
  total_calls: number;
  leads_called: number;
  demos_booked: number;
  quotes_sent: number;
  closed_won: number;
};

const MAIN_TABS = ["Overview", "Latency", "Alerts", "Performance"] as const;
type MainTab = typeof MAIN_TABS[number];
type LatencySubTab = "engines" | "calls" | "models" | "trend";

export default function AnalyticsPage() {
  const { user, sessionTimeout } = useAuth();
  const isSalesRep = user?.role === "sales_representative";

  // Main tab
  const [activeTab, setActiveTab]   = useState<MainTab>("Overview");

  // Overview
  const [days, setDays]             = useState(30);
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo]     = useState("");
  const [useCustom, setUseCustom]   = useState(false);
  const [summary, setSummary]       = useState<EngagementSummary | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);

  // Latency
  const [latencyDays, setLatencyDays]   = useState(7);
  const [scope, setScope]               = useState<"all" | "mine">(isSalesRep ? "mine" : "all");
  const [latency, setLatency]           = useState<LatencyData | null>(null);
  const [latencyLoading, setLatencyLoading] = useState(false);
  const [latencyRefreshing, setLatencyRefreshing] = useState(false);
  const [latencySubTab, setLatencySubTab] = useState<LatencySubTab>("engines");
  const [expandedCall, setExpandedCall] = useState<number | null>(null);
  const [lastAt, setLastAt]             = useState(new Date());

  // Alerts
  const [alerts, setAlerts]         = useState<Alert[]>([]);
  const [alertsLoading, setAlertsLoading] = useState(false);
  const [newAlertMetric, setNewAlertMetric]       = useState("");
  const [newAlertThreshold, setNewAlertThreshold] = useState<number>(0);
  const [newAlertDirection, setNewAlertDirection] = useState("gte");
  const [newAlertChannel, setNewAlertChannel]     = useState("email");
  const [alertSaving, setAlertSaving] = useState(false);

  // Performance
  const [perfDays, setPerfDays]               = useState(30);
  const [perfLoading, setPerfLoading]         = useState(false);
  const [perf, setPerf]                       = useState<CallPerformance | null>(null);
  const [conv, setConv]                       = useState<CallConversion | null>(null);

  // Exports
  const [exportLoading, setExportLoading]           = useState(false);
  const [quoteExportLoading, setQuoteExportLoading] = useState(false);

  // Toast
  const [toast, setToast]         = useState<string | null>(null);
  const [toastError, setToastError] = useState(false);
  function showToast(msg: string, error = false) {
    setToast(msg); setToastError(error); setTimeout(() => setToast(null), 3500);
  }

  const authH = {"Content-Type": "application/json" };


  const fetchSummary = useCallback(async (d: number, from?: string, to?: string) => {
    if (!user) return;
    setSummaryLoading(true);
    try {
      let url: string;
      if (from && to) {
        url = `${API_BASE}/analytics/engagement-summary?date_from=${from}&date_to=${to}`;
      } else {
        url = `${API_BASE}/analytics/engagement-summary?days=${d}`;
      }
      const res = await apiFetch(url, { headers: authH });
      if (res.status === 401) { sessionTimeout(); return; }
      if (res.ok) setSummary(await res.json());
    } catch {} finally { setSummaryLoading(false); }
  }, [user]);

  const fetchLatency = useCallback(async (silent = false) => {
    if (!user) return;
    silent ? setLatencyRefreshing(true) : setLatencyLoading(true);
    try {
      const res = await apiFetch(`${API_BASE}/analytics/latency?days=${latencyDays}&scope=${scope}`, { headers: authH });
      if (res.status === 401) { sessionTimeout(); return; }
      if (res.ok) { setLatency(await res.json()); setLastAt(new Date()); }
    } catch {} finally { setLatencyLoading(false); setLatencyRefreshing(false); }
  }, [user, latencyDays, scope]);

  const fetchAlerts = useCallback(async () => {
    if (!user) return;
    setAlertsLoading(true);
    try {
      const res = await apiFetch(`${API_BASE}/analytics/alerts`, { headers: authH });
      if (res.status === 401) { sessionTimeout(); return; }
      if (res.ok) setAlerts(await res.json());
    } catch {} finally { setAlertsLoading(false); }
  }, [user]);

  const fetchPerformance = useCallback(async (d: number) => {
    if (!user) return;
    setPerfLoading(true);
    try {
      const [pr, cr] = await Promise.all([
        apiFetch(`${API_BASE}/analytics/call-performance?days=${d}`, { headers: authH }),
        apiFetch(`${API_BASE}/analytics/call-conversion?days=${d}`, { headers: authH }),
      ]);
      if (pr.status === 401 || cr.status === 401) { sessionTimeout(); return; }
      if (pr.ok) setPerf(await pr.json());
      if (cr.ok) setConv(await cr.json());
    } catch {} finally { setPerfLoading(false); }
  }, [user]);

  useEffect(() => { if (activeTab === "Performance") fetchPerformance(perfDays); }, [activeTab, fetchPerformance, perfDays]);

  useEffect(() => {
    if (useCustom && customFrom && customTo) {
      fetchSummary(0, customFrom, customTo);
    } else if (!useCustom) {
      fetchSummary(days);
    }
  }, [fetchSummary, days, useCustom, customFrom, customTo]);
  useEffect(() => { fetchLatency(); }, [fetchLatency]);
  // Auto-refresh latency every 30 s when on that tab
  useEffect(() => {
    if (activeTab !== "Latency") return;
    const id = setInterval(() => fetchLatency(true), 30_000);
    return () => clearInterval(id);
  }, [activeTab, fetchLatency]);
  useEffect(() => { fetchAlerts(); }, [fetchAlerts]);

  async function handleCreateAlert() {
    if (!newAlertMetric.trim()) { showToast("Metric is required", true); return; }
    setAlertSaving(true);
    try {
      const res = await apiFetch(`${API_BASE}/analytics/alerts`, {
        method: "POST",        body: JSON.stringify({ metric: newAlertMetric.trim(), threshold: newAlertThreshold, direction: newAlertDirection, channel: newAlertChannel }) });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Failed");
      showToast("Alert created"); setNewAlertMetric(""); setNewAlertThreshold(0); fetchAlerts();
    } catch (e) { showToast(e instanceof Error ? e.message : "Failed", true); }
    finally { setAlertSaving(false); }
  }

  async function handleToggleAlert(a: Alert) {
    const action = a.enabled ? "disable" : "enable";
    const res = await apiFetch(`${API_BASE}/analytics/alerts/${a.id}/${action}`, { method: "PATCH", headers: authH });
    if (res.ok) { showToast(`Alert ${action}d`); fetchAlerts(); }
  }

  async function handleDeleteAlert(id: number) {
    const res = await apiFetch(`${API_BASE}/analytics/alerts/${id}`, { method: "DELETE", headers: authH });
    if (res.ok) { showToast("Alert deleted"); fetchAlerts(); }
  }

  function handleExportCSV() {
    setExportLoading(true);
    try {
      const rows: string[][] = [];
      if (summary) {
        rows.push(["Event Type", "Count"]);
        for (const [k, v] of Object.entries(summary.event_counts)) rows.push([k, String(v)]);
        rows.push([]);
        rows.push(["Channel", "Count"]);
        for (const [k, v] of Object.entries(summary.channel_counts)) rows.push([k, String(v)]);
        rows.push([]);
      }
      if (latency) {
        rows.push(["Engine", "Turns", "Avg STT", "Avg LLM", "Avg TTS", "Avg Total", "Min", "Max"]);
        for (const e of latency.engines)
          rows.push([e.engine, String(e.rows), fms(e.stt_avg), fms(e.llm_avg), fms(e.tts_avg), fms(e.total_avg), fms(e.total_min), fms(e.total_max)]);
      }
      const csv = rows.map(r => r.map(c => `"${c.replace(/"/g, '""')}"`).join(",")).join("\n");
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
      a.download = `analytics_${new Date().toISOString().split("T")[0]}.csv`;
      a.click();
      showToast("CSV downloaded");
    } finally { setExportLoading(false); }
  }

  async function handleExportQuoteCSV() {
    setQuoteExportLoading(true);
    try {
      const res = await apiFetch(`${API_BASE}/analytics/quote/export`, { headers: authH });
      if (!res.ok) throw new Error("Export failed");
      const a = document.createElement("a");
      a.href = URL.createObjectURL(await res.blob());
      a.download = `quotes_${new Date().toISOString().split("T")[0]}.csv`;
      a.click();
      showToast("Quotes CSV downloaded");
    } catch (e) { showToast(e instanceof Error ? e.message : "Failed", true); }
    finally { setQuoteExportLoading(false); }
  }

  const totalEvents    = summary ? Object.values(summary.event_counts).reduce((s, v) => s + v, 0) : 0;
  const emailOpens     = summary ? (summary.event_counts["email_open"] ?? summary.event_counts["open"] ?? 0) : 0;
  const linkClicks     = summary ? (summary.event_counts["email_click"] ?? summary.event_counts["click"] ?? 0) : 0;
  const replies        = summary ? (summary.event_counts["reply"] ?? 0) + (summary.event_counts["whatsapp_reply"] ?? 0) : 0;
  const best           = latency?.engines[0];
  const worst          = latency?.engines.at(-1);

  return (
    <div className="space-y-6 pb-12">

      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.2em] text-violet-400">Insights</p>
          <h1 className="text-4xl font-bold tracking-tight"><span className="gradient-text">Analytics</span></h1>
          <p className="mt-1.5 text-slate-500 text-sm font-medium flex items-center gap-2">
            <Pulse /> Live · {lastAt.toLocaleTimeString()}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={handleExportCSV} disabled={exportLoading || (!summary && !latency)}
            className="flex items-center gap-2 px-4 py-2 rounded-xl border border-white/10 bg-white/5 text-sm text-slate-400 hover:text-white transition-colors disabled:opacity-40">
            {exportLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
            Export CSV
          </button>
          <button onClick={handleExportQuoteCSV} disabled={quoteExportLoading}
            className="flex items-center gap-2 px-4 py-2 rounded-xl border border-white/10 bg-white/5 text-sm text-slate-400 hover:text-white transition-colors disabled:opacity-40">
            {quoteExportLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
            Quotes CSV
          </button>
        </div>
      </div>

      {/* Toast */}
      {toast && (
        <div className={clsx("rounded-xl border px-4 py-3 text-sm",
          toastError ? "border-red-500/30 bg-red-500/10 text-red-300" : "border-violet-500/30 bg-violet-500/10 text-violet-200")}>
          {toast}
        </div>
      )}

      {/* Main Tabs */}
      <div className="flex gap-1 border-b border-white/10">
        {MAIN_TABS.map(t => (
          <button key={t} onClick={() => setActiveTab(t)}
            className={clsx("px-5 py-3 text-sm font-semibold capitalize rounded-t-xl transition-all border-b-2",
              activeTab === t ? "text-violet-400 border-violet-500 bg-violet-500/10" : "text-slate-500 border-transparent hover:text-white")}>
            {t === "Overview"    ? <><BarChart2 className="inline h-3.5 w-3.5 mr-1.5" />Overview</>    :
             t === "Latency"     ? <><Clock     className="inline h-3.5 w-3.5 mr-1.5" />Latency</>     :
             t === "Performance" ? <><Zap       className="inline h-3.5 w-3.5 mr-1.5" />Performance</> :
                                   <><Bell      className="inline h-3.5 w-3.5 mr-1.5" />Alerts</>}
          </button>
        ))}
      </div>

      {/* OVERVIEW TAB */}
      {activeTab === "Overview" && (
        <div className="space-y-6">
          {/* Day selector */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-slate-500 font-medium">Period:</span>
            <div className="flex rounded-xl overflow-hidden border border-white/10">
              {[7, 14, 30, 90].map(d => (
                <button key={d} onClick={() => { setUseCustom(false); setDays(d); }}
                  className={clsx("px-4 py-2 text-xs font-semibold transition-colors",
                    !useCustom && days === d ? "bg-violet-600 text-white" : "bg-white/5 text-slate-400 hover:text-white")}>
                  {d}d
                </button>
              ))}
              <button onClick={() => setUseCustom(v => !v)}
                className={clsx("px-4 py-2 text-xs font-semibold transition-colors",
                  useCustom ? "bg-violet-600 text-white" : "bg-white/5 text-slate-400 hover:text-white")}>
                Custom
              </button>
            </div>
            {useCustom && (
              <div className="flex items-center gap-2">
                <input
                  type="date"
                  value={customFrom}
                  max={customTo || undefined}
                  onChange={e => setCustomFrom(e.target.value)}
                  className="rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-slate-300 focus:outline-none focus:ring-2 focus:ring-violet-500"
                />
                <span className="text-xs text-slate-500">→</span>
                <input
                  type="date"
                  value={customTo}
                  min={customFrom || undefined}
                  max={new Date().toISOString().split("T")[0]}
                  onChange={e => setCustomTo(e.target.value)}
                  className="rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-slate-300 focus:outline-none focus:ring-2 focus:ring-violet-500"
                />
                {customFrom && customTo && (
                  <span className="text-[10px] text-violet-400 font-medium">
                    {Math.round((new Date(customTo).getTime() - new Date(customFrom).getTime()) / 86400000) + 1}d range
                  </span>
                )}
              </div>
            )}
          </div>

          {summaryLoading ? (
            <div className="flex items-center justify-center py-24 gap-3 text-slate-500">
              <RefreshCw className="h-5 w-5 animate-spin" /> Loading…
            </div>
          ) : !summary ? (
            <p className="text-center py-24 text-slate-600">No engagement data yet.</p>
          ) : (
            <>
              {/* KPI strip */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <KpiCard label="Total Events"  value={totalEvents.toLocaleString()}  icon={Activity}     color="#818cf8" />
                <KpiCard label="Email Opens"   value={emailOpens.toLocaleString()}   icon={Activity}     color="#34d399" />
                <KpiCard label="Link Clicks"   value={linkClicks.toLocaleString()}   icon={Activity}     color="#60a5fa" />
                <KpiCard label="Replies"       value={replies.toLocaleString()}      icon={Activity}     color="#fb923c" />
              </div>

              {/* Channel breakdown */}
              <div className="glass rounded-2xl border border-white/10 p-5">
                <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-4">Channel Breakdown</p>
                <HorizontalMetricBars
                  rows={Object.entries(summary.channel_counts).map(([label, value]) => ({ label, value }))}
                />
              </div>

              {/* Campaign conversion */}
              {summary.campaign_conversion_trends.length > 0 && (
                <div className="glass rounded-2xl border border-white/10 p-5">
                  <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-4">Campaign Conversion</p>
                  <CampaignConversionChart rows={summary.campaign_conversion_trends} />
                </div>
              )}

              {summary.campaign_status_over_time.length > 0 && (
                <div className="glass rounded-2xl border border-white/10 p-5">
                  <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-4">Campaign Status Timeline</p>
                  <CampaignStatusTimelineChart rows={summary.campaign_status_over_time} limitDays={5} />
                </div>
              )}

              {/* Call task + Quote status side by side */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                <div className="glass rounded-2xl border border-white/10 p-5">
                  <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-4">Call Task Status</p>
                  <div className="space-y-3">
                    {Object.entries(summary.call_task_status_counts).map(([st, cnt]) => (
                      <div key={st} className="flex items-center gap-3">
                        <span className={clsx("h-2 w-2 rounded-full flex-shrink-0", CALL_STATUS_COLORS[st] ?? "bg-slate-400")} />
                        <span className="flex-1 text-xs text-slate-400 capitalize">{st}</span>
                        <span className="text-xs font-bold text-slate-300">{cnt}</span>
                      </div>
                    ))}
                  </div>
                </div>
                <div className="glass rounded-2xl border border-white/10 p-5">
                  <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-4">Quote Status</p>
                  <div className="space-y-3">
                    {Object.entries(summary.quote_status_counts).map(([st, cnt]) => (
                      <div key={st} className="flex items-center gap-3">
                        <span className="h-2 w-2 rounded-full bg-blue-500 flex-shrink-0" />
                        <span className="flex-1 text-xs text-slate-400 capitalize">{st}</span>
                        <span className="text-xs font-bold text-slate-300">{cnt}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      )}

      {/* LATENCY TAB */}
      {activeTab === "Latency" && (
        <div className="space-y-5">
          {/* Controls */}
          <div className="flex items-center flex-wrap gap-3">
            {/* Day range */}
            <div className="flex rounded-xl overflow-hidden border border-white/10">
              {([1, 7, 30] as const).map(d => (
                <button key={d} onClick={() => setLatencyDays(d)}
                  className={clsx("px-4 py-2 text-xs font-semibold transition-colors",
                    latencyDays === d ? "bg-violet-600 text-white" : "bg-white/5 text-slate-400 hover:text-white")}>
                  {d === 1 ? "Today" : `${d}d`}
                </button>
              ))}
            </div>
            {/* Scope */}
            <div className="flex rounded-xl overflow-hidden border border-white/10">
              {(["all", "mine"] as const).map(s => (
                <button key={s} onClick={() => setScope(s)}
                  className={clsx("px-4 py-2 text-xs font-semibold capitalize transition-colors",
                    scope === s ? "bg-violet-600 text-white" : "bg-white/5 text-slate-400 hover:text-white")}>
                  {s === "all" ? "All Users" : "My Calls"}
                </button>
              ))}
            </div>
            <button onClick={() => fetchLatency(true)} disabled={latencyRefreshing}
              className="flex items-center gap-2 px-4 py-2 rounded-xl bg-white/5 border border-white/10 text-sm text-slate-400 hover:text-white transition-colors ml-auto">
              <RefreshCw className={clsx("h-4 w-4", latencyRefreshing && "animate-spin")} />
              Refresh
            </button>
          </div>

          {/* KPI strip */}
          {latency && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <KpiCard label="Total Turns"    value={latency.meta.total_turns.toLocaleString()} icon={Activity}     color="#818cf8" />
              <KpiCard label="Total Calls"    value={latency.meta.total_calls.toString()}        icon={Phone}        color="#60a5fa" />
              <KpiCard label="Fastest Engine" value={fms(best?.total_avg ?? 0)}                 sub={best?.engine}  icon={TrendingDown} color="#34d399" />
              <KpiCard label="Slowest Engine" value={fms(worst?.total_avg ?? 0)}                sub={worst?.engine} icon={TrendingUp}   color="#f87171" />
            </div>
          )}

          {/* Sub-tabs */}
          <div className="flex gap-1 border-b border-white/10">
            {(["engines", "calls", "models", "trend"] as const).map(t => (
              <button key={t} onClick={() => setLatencySubTab(t)}
                className={clsx("px-5 py-2.5 text-xs font-semibold rounded-t-lg transition-all border-b-2",
                  latencySubTab === t ? "text-violet-400 border-violet-500 bg-violet-500/10" : "text-slate-500 border-transparent hover:text-white")}>
                {t === "engines" ? "⚡ Engines" : t === "calls" ? "📞 Calls" : t === "models" ? "🔬 Models" : "📈 Trend"}
              </button>
            ))}
          </div>

          {latencyLoading ? (
            <div className="flex items-center justify-center py-24 gap-3 text-slate-500">
              <RefreshCw className="h-5 w-5 animate-spin" /> Loading analytics…
            </div>
          ) : !latency || latency.engines.length === 0 ? (
            <div className="text-center py-24 text-slate-500">No latency data yet. Make a call to generate data.</div>
          ) : (
            <>
              {/* Engines */}
              {latencySubTab === "engines" && (
                <div className="space-y-3">
                  <p className="text-[10px] text-slate-500 uppercase tracking-widest">
                    {latency.engines.length} engines · ranked by avg turn latency
                  </p>
                  {latency.engines.map((e, i) => {
                    const col    = engineColor(e.engine);
                    const maxVal = latency.engines.at(-1)!.total_avg || 1;
                    return (
                      <div key={e.engine} className="glass rounded-2xl p-5 border border-white/10 hover:border-white/20 transition-all"
                        style={{ borderLeftColor: col, borderLeftWidth: 3 }}>
                        <div className="flex items-start justify-between flex-wrap gap-3">
                          <div>
                            <p className="text-[10px] text-slate-500 font-mono">#{i + 1} · {e.rows.toLocaleString()} turns</p>
                            <p className="text-base font-bold mt-0.5" style={{ color: col }}>{e.engine}</p>
                            <p className="text-[10px] text-slate-500 mt-0.5">best {fms(e.total_min)} · worst {fms(e.total_max)}</p>
                            {(e.total_p95 || e.llm_p95) ? (
                              <p className="text-[10px] text-slate-400 mt-0.5 font-mono">
                                p95 total <span className={clsx(e.total_p95 && e.total_p95 > 800 ? "text-red-400" : "text-emerald-400")}>{fms(e.total_p95 || 0)}</span>
                                {" · "}p95 llm <span className="text-slate-300">{fms(e.llm_p95 || 0)}</span>
                              </p>
                            ) : null}
                          </div>
                          <div className="text-right">
                            <p className="text-3xl font-black leading-none" style={{ color: col }}>{fms(e.total_avg)}</p>
                            <p className="text-[10px] text-slate-500 mt-1">avg / turn</p>
                          </div>
                        </div>
                        <div className="mt-3 h-5 rounded-lg bg-white/5 overflow-hidden">
                          <div className="h-full rounded-lg transition-all duration-700"
                            style={{ width: `${Math.max((e.total_avg / maxVal) * 100, 3)}%`, background: `linear-gradient(90deg,${col}cc,${col}44)`, minWidth: "3%" }} />
                        </div>
                        <StackBar stt={e.stt_avg} llm={e.llm_avg} tts={e.tts_avg} total={e.total_avg} />
                      </div>
                    );
                  })}
                </div>
              )}

              {/* Calls */}
              {latencySubTab === "calls" && (
                <div className="space-y-2">
                  <p className="text-[10px] text-slate-500 uppercase tracking-widest">
                    {latency.interactions.length} calls · click any row to expand
                  </p>
                  <div className="glass rounded-2xl border border-white/10 overflow-hidden">
                    <div className="overflow-x-auto">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="bg-white/5 border-b border-white/10">
                            {["#","ID","Engine","STT","LLM","TTS","Turns","Avg/Turn","Best","Worst","STT%"].map(h => (
                              <th key={h} className="px-4 py-3 text-left text-slate-500 font-medium whitespace-nowrap">{h}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {latency.interactions.map((c, i) => {
                            const col     = i < 3 ? "#34d399" : i >= latency.interactions.length - 3 ? "#f87171" : "#94a3b8";
                            const sttPct  = c.total_avg ? Math.round((c.stt_avg / c.total_avg) * 100) : 0;
                            const isExp   = expandedCall === c.id;
                            return (
                              <React.Fragment key={c.id}>
                                <tr onClick={() => setExpandedCall(isExp ? null : c.id)}
                                  className="border-b border-white/5 cursor-pointer hover:bg-white/5 transition-colors">
                                  <td className="px-4 py-3 font-bold" style={{ color: col }}>#{i + 1}</td>
                                  <td className="px-4 py-3 text-slate-300">{c.id}</td>
                                  <td className="px-4 py-3 font-mono text-[10px]" style={{ color: engineColor(c.engine) }}>{c.engine}</td>
                                  <td className="px-4 py-3 text-violet-400 text-[10px]">{c.stt_model}</td>
                                  <td className="px-4 py-3 text-emerald-400 text-[10px] max-w-[100px] truncate">{c.llm_model.split("/").pop()}</td>
                                  <td className="px-4 py-3 text-orange-400 text-[10px]">{c.tts_model}</td>
                                  <td className="px-4 py-3 text-slate-400">{c.turns}</td>
                                  <td className="px-4 py-3 font-bold" style={{ color: col }}>{fms(c.total_avg)}</td>
                                  <td className="px-4 py-3 text-emerald-400">{fms(c.total_min)}</td>
                                  <td className="px-4 py-3 text-red-400">{fms(c.total_max)}</td>
                                  <td className="px-4 py-3">
                                    <div className="flex items-center gap-1">
                                      <div className="w-10 h-[4px] rounded bg-white/10 overflow-hidden">
                                        <div style={{ width: `${sttPct}%`, background: "#818cf8" }} className="h-full" />
                                      </div>
                                      <span className="text-violet-400 text-[10px]">{sttPct}%</span>
                                    </div>
                                  </td>
                                </tr>
                                {isExp && (
                                  <tr className="bg-white/[0.02] border-b border-white/5">
                                    <td colSpan={11} className="px-6 py-4">
                                      <p className="text-[10px] text-slate-500 uppercase tracking-widest mb-3">Detail — Call #{c.id} · {c.engine}</p>
                                      <div className="flex flex-wrap gap-6 mb-3">
                                        {[["Avg STT", fms(c.stt_avg), "#818cf8"], ["Avg LLM", fms(c.llm_avg), "#34d399"], ["Avg TTS", fms(c.tts_avg), "#fb923c"],
                                          ["STT %", `${Math.round((c.stt_avg / c.total_avg) * 100)}%`, "#818cf8"],
                                          ["LLM %", `${Math.round((c.llm_avg / c.total_avg) * 100)}%`, "#34d399"]
                                        ].map(([l, v, cl]) => (
                                          <div key={l as string}>
                                            <p className="text-[9px] text-slate-500 uppercase tracking-widest">{l}</p>
                                            <p className="text-lg font-bold mt-0.5" style={{ color: cl as string }}>{v}</p>
                                          </div>
                                        ))}
                                      </div>
                                      <StackBar stt={c.stt_avg} llm={c.llm_avg} tts={c.tts_avg} total={c.total_avg} />
                                    </td>
                                  </tr>
                                )}
                              </React.Fragment>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </div>
              )}

              {/* Models */}
              {latencySubTab === "models" && (
                <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
                  <ModelCard title="STT Models" icon={Mic}     accent="#818cf8" models={latency.stt_models} />
                  <ModelCard title="LLM Models" icon={Brain}   accent="#34d399" models={latency.llm_models} />
                  <ModelCard title="TTS Models" icon={Volume2} accent="#fb923c" models={latency.tts_models} />
                  <div className="md:col-span-3 flex items-center gap-6 px-1">
                    {[["#818cf8", "STT"], ["#34d399", "LLM"], ["#fb923c", "TTS"]].map(([c, l]) => (
                      <span key={l} className="flex items-center gap-1.5 text-xs text-slate-500">
                        <span className="h-2 w-2 rounded-full" style={{ background: c }} />{l} stage
                      </span>
                    ))}
                    <span className="text-xs text-slate-600 ml-auto">Ranked fastest → slowest</span>
                  </div>
                </div>
              )}

              {/* Trend */}
              {latencySubTab === "trend" && (
                <div className="space-y-4">
                  <p className="text-[10px] text-slate-500 uppercase tracking-widest">Daily avg turn latency per engine</p>
                  {latency.trend.length === 0 ? (
                    <p className="text-center py-16 text-slate-600">No trend data for this period.</p>
                  ) : (
                    <LatencyTrendChart trend={latency.trend} formatMs={fms} colorForEngine={engineColor} />
                  )}
                  {latency.trend.length > 1 && <DoDSummary trend={latency.trend} />}
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* ALERTS TAB */}
      {activeTab === "Alerts" && (
        <div className="space-y-6">
          {/* Create alert */}
          <div className="glass rounded-2xl border border-white/10 p-5">
            <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-4">New Alert</p>
            <div className="grid grid-cols-1 md:grid-cols-5 gap-3 items-end">
              <div className="md:col-span-2">
                <label className="text-[10px] text-slate-500 uppercase mb-1 block">Metric</label>
                <input value={newAlertMetric} onChange={e => setNewAlertMetric(e.target.value)}
                  placeholder="e.g. email_open_rate"
                  className="w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:ring-1 focus:ring-violet-500" />
              </div>
              <div>
                <label className="text-[10px] text-slate-500 uppercase mb-1 block">Threshold</label>
                <input type="number" value={newAlertThreshold} onChange={e => setNewAlertThreshold(Number(e.target.value))}
                  className="w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-1 focus:ring-violet-500" />
              </div>
              <div>
                <label className="text-[10px] text-slate-500 uppercase mb-1 block">Direction</label>
                <select value={newAlertDirection} onChange={e => setNewAlertDirection(e.target.value)}
                  className="w-full rounded-xl border border-white/10 bg-slate-800 px-3 py-2 text-sm text-slate-200 focus:outline-none">
                  <option value="gte">≥ (gte)</option>
                  <option value="lte">≤ (lte)</option>
                </select>
              </div>
              <button onClick={handleCreateAlert} disabled={alertSaving}
                className="flex items-center justify-center gap-2 rounded-xl bg-violet-600 px-4 py-2 text-sm font-semibold text-white hover:bg-violet-700 disabled:opacity-50 transition-colors">
                {alertSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                Create
              </button>
            </div>
          </div>

          {/* Alert list */}
          {alertsLoading ? (
            <div className="flex items-center justify-center py-16 gap-3 text-slate-500">
              <RefreshCw className="h-5 w-5 animate-spin" /> Loading alerts…
            </div>
          ) : alerts.length === 0 ? (
            <p className="text-center py-16 text-slate-600">No alerts configured yet.</p>
          ) : (
            <div className="glass rounded-2xl border border-white/10 overflow-hidden">
              <table className="w-full text-xs">
                <thead>
                  <tr className="bg-white/5 border-b border-white/10">
                    {["Metric", "Threshold", "Direction", "Channel", "Last Triggered", "Status", ""].map(h => (
                      <th key={h} className="px-4 py-3 text-left text-slate-500 font-medium whitespace-nowrap">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {alerts.map(a => (
                    <tr key={a.id} className="border-b border-white/5 hover:bg-white/5">
                      <td className="px-4 py-3 text-slate-300 font-mono">{a.metric}</td>
                      <td className="px-4 py-3 text-slate-400">{a.threshold}</td>
                      <td className="px-4 py-3 text-slate-400">{a.direction}</td>
                      <td className="px-4 py-3 text-slate-400">{a.channel}</td>
                      <td className="px-4 py-3 text-slate-500">{fmtDate(a.last_triggered_at)}</td>
                      <td className="px-4 py-3">
                        <button onClick={() => handleToggleAlert(a)}
                          className={clsx("px-2.5 py-1 rounded-full text-[10px] font-bold transition-colors",
                            a.enabled ? "bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30" : "bg-slate-500/20 text-slate-400 hover:bg-slate-500/30")}>
                          {a.enabled ? "Enabled" : "Disabled"}
                        </button>
                      </td>
                      <td className="px-4 py-3">
                        <button onClick={() => handleDeleteAlert(a.id)}
                          className="p-1.5 rounded-lg text-slate-500 hover:text-red-400 hover:bg-red-400/10 transition-colors">
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* PERFORMANCE TAB */}
      {activeTab === "Performance" && (
        <div className="space-y-6">
          {/* Days selector */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500 font-medium">Period:</span>
            <div className="flex rounded-xl overflow-hidden border border-white/10">
              {[7, 14, 30, 90].map(d => (
                <button key={d} onClick={() => setPerfDays(d)}
                  className={clsx("px-4 py-2 text-xs font-semibold transition-colors",
                    perfDays === d ? "bg-violet-600 text-white" : "bg-white/5 text-slate-400 hover:text-white")}>
                  {d}d
                </button>
              ))}
            </div>
          </div>

          {perfLoading ? (
            <div className="flex items-center justify-center py-24 gap-3 text-slate-500">
              <RefreshCw className="h-5 w-5 animate-spin" /> Loading…
            </div>
          ) : (
            <>
              {/* Stat cards */}
              {(() => {
                const connectRate  = perf?.connect_rate_pct ?? 0;
                const talkSec      = perf?.avg_talk_time_seconds ?? 0;
                const talkMin      = Math.floor(talkSec / 60);
                const talkRemSec   = talkSec % 60;
                const talkLabel    = talkSec > 0 ? `${talkMin}m ${talkRemSec}s` : "—";
                const totalCalls   = conv?.total_calls ?? 0;
                const demosBooked  = conv?.demos_booked ?? 0;
                const closedWon    = conv?.closed_won ?? 0;
                const demoRate     = totalCalls > 0 ? ((demosBooked / totalCalls) * 100).toFixed(1) : "0.0";
                const closeRate    = totalCalls > 0 ? ((closedWon  / totalCalls) * 100).toFixed(1) : "0.0";
                return (
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <KpiCard label="Connect Rate"  value={`${connectRate}%`}  icon={Phone}    color="#34d399" sub={`${perf?.connected_calls ?? 0} of ${perf?.total_with_outcome ?? 0} calls`} />
                    <KpiCard label="Avg Talk Time" value={talkLabel}           icon={Mic}      color="#60a5fa" sub={`${perfDays}d window`} />
                    <KpiCard label="Demo Rate"     value={`${demoRate}%`}      icon={Activity} color="#fbbf24" sub={`${demosBooked} demos / ${totalCalls} calls`} />
                    <KpiCard label="Close Rate"    value={`${closeRate}%`}     icon={TrendingUp} color="#a78bfa" sub={`${closedWon} closed / ${totalCalls} calls`} />
                  </div>
                );
              })()}

              {/* Conversion funnel */}
              {conv && (
                <div className="glass rounded-2xl border border-white/10 p-6">
                  <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-5">Conversion Funnel</p>
                  {(() => {
                    const connected  = perf?.connected_calls ?? 0;
                    const stages: { label: string; value: number; color: string }[] = [
                      { label: "Called",     value: conv.total_calls,    color: "#818cf8" },
                      { label: "Connected",  value: connected,           color: "#60a5fa" },
                      { label: "Interested", value: conv.leads_called,   color: "#34d399" },
                      { label: "Quoted",     value: conv.quotes_sent,    color: "#fbbf24" },
                      { label: "Closed Won", value: conv.closed_won,     color: "#a78bfa" },
                    ];
                    const totalCalls = Math.max(conv.total_calls || 0, 1);
                    return (
                      <FunnelChart
                        items={stages.map((stage) => ({
                          status: stage.label,
                          count: stage.value,
                          percent: (stage.value / totalCalls) * 100,
                        }))}
                      />
                    );
                  })()}
                </div>
              )}

              {/* Outcome breakdown table */}
              {perf && Object.keys(perf.outcome_counts).length > 0 && (
                <div className="glass rounded-2xl border border-white/10 overflow-hidden">
                  <div className="px-5 py-4 border-b border-white/10">
                    <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500">Call Outcome Breakdown</p>
                  </div>
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="bg-white/5 border-b border-white/10">
                        <th className="px-5 py-3 text-left text-slate-500 font-medium">Outcome</th>
                        <th className="px-5 py-3 text-right text-slate-500 font-medium">Count</th>
                        <th className="px-5 py-3 text-right text-slate-500 font-medium">Share</th>
                        <th className="px-5 py-3 text-left text-slate-500 font-medium w-48">Bar</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(perf.outcome_counts)
                        .sort(([, a], [, b]) => b - a)
                        .map(([outcome, count]) => {
                          const total = perf.total_with_outcome || 1;
                          const pct   = ((count / total) * 100).toFixed(1);
                          const isConn = outcome.startsWith("answered_");
                          const color  = isConn ? "#34d399" : outcome.includes("busy") || outcome.includes("no") ? "#fbbf24" : "#f87171";
                          return (
                            <tr key={outcome} className="border-b border-white/5 hover:bg-white/5">
                              <td className="px-5 py-3 font-mono text-slate-300">{outcome}</td>
                              <td className="px-5 py-3 text-right font-bold" style={{ color }}>{count}</td>
                              <td className="px-5 py-3 text-right text-slate-400">{pct}%</td>
                              <td className="px-5 py-3">
                                <div className="h-[4px] rounded-full bg-white/10 overflow-hidden">
                                  <div className="h-full rounded-full transition-all duration-700"
                                    style={{ width: `${(count / total) * 100}%`, background: color }} />
                                </div>
                              </td>
                            </tr>
                          );
                        })}
                    </tbody>
                  </table>
                </div>
              )}

              {!perf && !conv && (
                <p className="text-center py-24 text-slate-600">No call data for this period.</p>
              )}
            </>
          )}
        </div>
      )}

    </div>
  );
}
