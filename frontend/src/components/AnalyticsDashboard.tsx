"use client";

import React, { useEffect, useState, useCallback } from "react";
import { useAuth } from "@/context/AuthContext";
import {
  Activity, RefreshCw, Mic, Brain, Volume2,
  TrendingDown, TrendingUp, Phone,
} from "lucide-react";
import clsx from "clsx";

// Types

interface EngineRow {
  engine: string; rows: number;
  stt_avg: number; llm_avg: number; tts_avg: number;
  total_avg: number; total_min: number; total_max: number;
}
interface CallRow {
  id: number; engine: string;
  stt_model: string; llm_model: string; tts_model: string;
  turns: number; stt_avg: number; llm_avg: number; tts_avg: number;
  total_avg: number; total_min: number; total_max: number;
}
interface ModelRow {
  model: string; provider: string; rows: number;
  avg: number; min: number; max: number;
}
interface TrendPoint { day: string; engine: string; avg_ms: number; turns: number; }
interface AnalyticsData {
  engines: EngineRow[];
  interactions: CallRow[];
  stt_models: ModelRow[];
  llm_models: ModelRow[];
  tts_models: ModelRow[];
  trend: TrendPoint[];
  meta: { days: number; total_turns: number; total_calls: number };
}

interface SummaryData {
  campaign_conversion_trends: Array<{
    name: string;
    responded: number;
    sent: number;
    conversion_rate: number;
    campaign_id?: number;
  }>;
  quote_timeline_export: Array<{
    quote_id: number;
    quote_number: string;
    status: string;
    dates: Record<string, string | null>;
  }>;
  campaign_status_over_time: Array<{
    day: string;
    status: string;
    count: number;
  }>;
  campaign_funnel: Array<{
    status: string;
    count: number;
    percent: number;
  }>;
}

interface CampaignDrillPoint {
  day: string;
  status: string;
  count: number;
}

interface AlertInfo {
  id: number;
  metric: string;
  threshold: number;
  direction: string;
  channel: string;
  last_triggered_at?: string | null;
}

// Helpers

const fms = (v: number) => v >= 1000 ? `${(v / 1000).toFixed(2)}s` : `${Math.round(v)}ms`;

const ENGINE_COLORS: Record<string, string> = {
  "deepgram-cerebras-cartesia": "#34d399",
  "deepgram-mistral-cartesia":  "#60a5fa",
  "deepgram-mistral-deepgram":  "#818cf8",
  "sarvam-cerebras-sarvam":     "#fbbf24",
  "cartesia-mistral-cartesia":  "#f87171",
};

const engineColor = (e: string) => {
  if (ENGINE_COLORS[e]) return ENGINE_COLORS[e];
  // Simple hash for dynamic colors
  let hash = 0;
  for (let i = 0; i < e.length; i++) {
    hash = e.charCodeAt(i) + ((hash << 5) - hash);
  }
  const h = Math.abs(hash) % 360;
  return `hsl(${h}, 70%, 65%)`;
};

// Sub-components

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
        {([["STT","#818cf8",stt],["LLM","#34d399",llm],["TTS","#fb923c",tts]] as const).map(([k,c,v]) => (
          <span key={k} className="text-[10px] font-mono" style={{ color: c }}>
            {k} {fms(v as number)} <span className="opacity-40">({((v as number)/total*100).toFixed(0)}%)</span>
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
        <div
          className="h-full rounded-full transition-all duration-700"
          style={{ width: `${Math.max((value / (max || 1)) * 100, 2)}%`, background: color }}
        />
      </div>
      <span className="font-mono text-[10px] w-14 text-right" style={{ color }}>{fms(value)}</span>
    </div>
  );
}

function Pulse() {
  return (
    <span className="relative inline-flex h-2 w-2">
      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
      <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
    </span>
  );
}

function KpiCard({
  label, value, sub, color, icon: Icon,
}: { label: string; value: string; sub?: string; color: string; icon: React.ElementType }) {
  return (
    <div
      className="glass rounded-2xl p-5 border border-white/10"
      style={{ borderLeftColor: color, borderLeftWidth: 3 }}
    >
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

// Main Component

export default function AnalyticsDashboard() {
  const { token, sessionTimeout } = useAuth();
  const [data, setData]             = useState<AnalyticsData | null>(null);
  const [loading, setLoading]       = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [days, setDays]             = useState(7);
  const [startDate, setStartDate]   = useState("");
  const [endDate, setEndDate]       = useState("");
  const [tab, setTab]               = useState<"engines" | "calls" | "models" | "trend">("engines");
  const [expandedCall, setExpandedCall] = useState<number | null>(null);
  const [lastAt, setLastAt]         = useState(new Date());
  const [summary, setSummary] = useState<SummaryData | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [drilldown, setDrilldown] = useState<CampaignDrillPoint[]>([]);
  const [drilldownLoading, setDrilldownLoading] = useState(false);
  const [selectedCampaign, setSelectedCampaign] = useState<number | null>(null);
  const [alerts, setAlerts] = useState<AlertInfo[]>([]);
  const [alertMetric, setAlertMetric] = useState("quote.viewed");
  const [alertThreshold, setAlertThreshold] = useState(1);
  const [alertDirection, setAlertDirection] = useState<"gte" | "lte">("gte");
  const [alertChannel, setAlertChannel] = useState("email");
  const [alertLoading, setAlertLoading] = useState(false);
  const [alertMessage, setAlertMessage] = useState<string | null>(null);

  const API_BASE = "http://localhost:6060";

  const loadSummary = useCallback(async () => {
    if (!token) return;
    setSummaryLoading(true);
    try {
      let url = `${API_BASE}/analytics/engagement-summary?days=${days}`;
      if (days === 0 && startDate && endDate) {
        url = `${API_BASE}/analytics/engagement-summary?start_date=${startDate}&end_date=${endDate}`;
      }
      const res = await fetch(url, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.status === 401) {
        sessionTimeout();
        return;
      }
      if (res.ok) {
        setSummary(await res.json());
      }
    } finally {
      setSummaryLoading(false);
    }
  }, [token, days, startDate, endDate, sessionTimeout]);

  const load = useCallback(async (silent = false) => {
    if (!token) return;
    silent ? setRefreshing(true) : setLoading(true);
    try {
      let url = `${API_BASE}/analytics/latency?days=${days}`;
      if (days === 0 && startDate && endDate) {
        url = `${API_BASE}/analytics/latency?start_date=${startDate}&end_date=${endDate}`;
      }
      const res = await fetch(url, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.status === 401) {
        sessionTimeout();
        return;
      }
      if (res.ok) { setData(await res.json()); setLastAt(new Date()); }
    } finally {
      setLoading(false); setRefreshing(false);
    }
  }, [token, days, startDate, endDate]);

  const loadAlerts = useCallback(async () => {
    if (!token) return;
    try {
      const res = await fetch(`${API_BASE}/analytics/alerts`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.status === 401) {
        sessionTimeout();
        return;
      }
      if (res.ok) {
        setAlerts(await res.json());
      }
    } catch (err) {
      console.error("Failed to load alerts", err);
    }
  }, [token, sessionTimeout]);

  const createAlert = useCallback(async () => {
    if (!token) return;
    setAlertLoading(true);
    setAlertMessage(null);
    try {
      const res = await fetch(`${API_BASE}/analytics/alerts`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          metric: alertMetric,
          threshold: alertThreshold,
          direction: alertDirection,
          channel: alertChannel,
        }),
      });
      if (res.status === 401) {
        sessionTimeout();
        return;
      }
      if (!res.ok) {
        throw new Error("Unable to create alert");
      }
      setAlertMessage("Alert created");
      await loadAlerts();
    } catch (err) {
      setAlertMessage((err as Error).message);
    } finally {
      setAlertLoading(false);
    }
  }, [alertChannel, alertDirection, alertMetric, alertThreshold, loadAlerts, sessionTimeout, token]);

  const evaluateAlerts = useCallback(async () => {
    if (!token) return;
    setAlertLoading(true);
    setAlertMessage(null);
    try {
      const res = await fetch(`${API_BASE}/analytics/alerts/evaluate`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.status === 401) {
        sessionTimeout();
        return;
      }
      if (!res.ok) {
        throw new Error("Evaluation failed");
      }
      const triggered = await res.json();
      const message =
        triggered.length > 0
          ? `Triggered: ${triggered.map((item: { metric: string; value: number; threshold: number }) => `${item.metric} (${item.value} vs ${item.threshold})`).join(", ")}`
          : "No alerts triggered";
      setAlertMessage(message);
      await loadAlerts();
    } catch (err) {
      setAlertMessage((err as Error).message);
    } finally {
      setAlertLoading(false);
    }
  }, [loadAlerts, sessionTimeout, token]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    const id = setInterval(() => load(true), 30_000);
    return () => clearInterval(id);
  }, [load]);
  useEffect(() => {
    loadSummary();
    loadAlerts();
  }, [loadSummary, loadAlerts]);

  const best  = data?.engines?.[0];
  const worst = data?.engines?.at(-1);

  return (
    <div className="space-y-6 pb-12">

      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-4xl font-bold tracking-tight text-white">
            Latency Analytics
          </h1>
          <p className="mt-1.5 text-slate-500 text-sm font-medium flex items-center gap-2">
            <Pulse />
            Live · auto-refresh 30s · {lastAt.toLocaleTimeString()}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {days === 0 && (
            <div className="flex items-center gap-2 bg-white/5 border border-white/10 rounded-xl px-3 py-1 animate-in fade-in slide-in-from-right-4">
              <input 
                type="date" 
                value={startDate} 
                onChange={(e) => setStartDate(e.target.value)}
                className="bg-transparent text-xs text-white border-none focus:ring-0" 
              />
              <span className="text-slate-600 text-[10px]">to</span>
              <input 
                type="date" 
                value={endDate} 
                onChange={(e) => setEndDate(e.target.value)}
                className="bg-transparent text-xs text-white border-none focus:ring-0" 
              />
            </div>
          )}
          <div className="flex rounded-xl overflow-hidden border border-white/10">
            {([1, 7, 30, 0] as const).map(d => (
              <button key={d} onClick={() => setDays(d)}
                className={clsx("px-4 py-2 text-xs font-semibold transition-colors",
                  days === d ? "bg-violet-600 text-white" : "bg-white/5 text-slate-400 hover:text-white")}>
                {d === 1 ? "Today" : d === 0 ? "Custom" : `${d}d`}
              </button>
            ))}
          </div>
          <button onClick={() => load(true)} disabled={refreshing || (days === 0 && (!startDate || !endDate))}
            className="flex items-center gap-2 px-4 py-2 rounded-xl bg-white/5 border border-white/10 text-sm text-slate-400 hover:text-white transition-colors disabled:opacity-30">
            <RefreshCw className={clsx("h-4 w-4", refreshing && "animate-spin")} />
            Refresh
          </button>
        </div>
      </div>

      {/* KPI Strip */}
      {data && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <KpiCard label="Total Turns"    value={data.meta.total_turns.toLocaleString()} icon={Activity}     color="#818cf8" />
          <KpiCard label="Total Calls"    value={data.meta.total_calls.toString()}       icon={Phone}        color="#60a5fa" />
          <KpiCard label="Fastest Engine" value={fms(best?.total_avg ?? 0)}             sub={best?.engine}  icon={TrendingDown} color="#34d399" />
          <KpiCard label="Slowest Engine" value={fms(worst?.total_avg ?? 0)}            sub={worst?.engine} icon={TrendingUp}   color="#f87171" />
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 border-b border-white/10">
        {(["engines","calls","models","trend"] as const).map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={clsx("px-5 py-3 text-sm font-semibold capitalize rounded-t-xl transition-all border-b-2",
              tab === t ? "text-violet-400 border-violet-500 bg-white/5" : "text-slate-500 border-transparent hover:text-white")}>
            {t === "engines" ? "⚡ Engines" : t === "calls" ? "📞 Calls" : t === "models" ? "🔬 Models" : "📈 Trend"}
          </button>
        ))}
      </div>

      {/* Loading / Empty */}
      {loading ? (
        <div className="flex items-center justify-center py-24 gap-3 text-slate-500">
          <RefreshCw className="h-5 w-5 animate-spin" /> Loading analytics…
        </div>
      ) : !data || data.engines.length === 0 ? (
        <div className="text-center py-24 text-slate-500">No latency data yet. Make a call to generate data.</div>
      ) : (
        <>
          {/* ENGINES TAB */}
          {tab === "engines" && (
            <div className="space-y-3">
              <p className="text-[10px] text-slate-500 uppercase tracking-widest">
                {data.engines.length} engines · ranked by avg turn latency
              </p>
              {data.engines.map((e, i) => {
                const col = engineColor(e.engine);
                const maxVal = data.engines.at(-1)!.total_avg || 1;
                return (
                  <div key={e.engine}
                    className="glass rounded-2xl p-5 border border-white/10 hover:border-white/20 transition-all"
                    style={{ borderLeftColor: col, borderLeftWidth: 3 }}>
                    <div className="flex items-start justify-between flex-wrap gap-3">
                      <div>
                        <p className="text-[10px] text-slate-500 font-mono">#{i+1} · {e.rows.toLocaleString()} turns</p>
                        <p className="text-base font-bold mt-0.5" style={{ color: col }}>{e.engine}</p>
                        <p className="text-[10px] text-slate-500 mt-0.5">best {fms(e.total_min)} · worst {fms(e.total_max)}</p>
                      </div>
                      <div className="text-right">
                        <p className="text-3xl font-black leading-none" style={{ color: col }}>{fms(e.total_avg)}</p>
                        <p className="text-[10px] text-slate-500 mt-1">avg / turn</p>
                      </div>
                    </div>
                    <div className="mt-3 h-5 rounded-lg bg-white/5 overflow-hidden">
                      <div className="h-full rounded-lg transition-all duration-700"
                        style={{ width: `${Math.max((e.total_avg/maxVal)*100,3)}%`, background: `linear-gradient(90deg,${col}cc,${col}44)`, minWidth:"3%" }} />
                    </div>
                    <StackBar stt={e.stt_avg} llm={e.llm_avg} tts={e.tts_avg} total={e.total_avg} />
                  </div>
                );
              })}
            </div>
          )}

          {/* CALLS TAB */}
          {tab === "calls" && (
            <div className="space-y-2">
              <p className="text-[10px] text-slate-500 uppercase tracking-widest">
                {data.interactions.length} calls · click any row to drill in
              </p>
              <div className="glass rounded-2xl border border-white/10 overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="w-full text-xs text-slate-300">
                    <thead>
                      <tr className="bg-white/5 border-b border-white/10 text-slate-500">
                        {["#","ID","Engine","STT","LLM","TTS","Turns","Avg/Turn","Best","Worst","STT%"].map(h => (
                          <th key={h} className="px-4 py-3 text-left font-medium whitespace-nowrap">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {data.interactions.map((c, i) => {
                        const col = i < 3 ? "#34d399" : i >= data.interactions.length - 3 ? "#f87171" : "#94a3b8";
                        const sttPct = c.total_avg ? Math.round((c.stt_avg/c.total_avg)*100) : 0;
                        const expanded = expandedCall === c.id;
                        return (
                          <React.Fragment key={c.id}>
                            <tr 
                              onClick={() => setExpandedCall(expanded ? null : c.id)}
                              className="border-b border-white/5 cursor-pointer hover:bg-white/5 transition-colors">
                              <td className="px-4 py-3 font-bold" style={{ color: col }}>#{i+1}</td>
                              <td className="px-4 py-3">{c.id}</td>
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
                                    <div style={{ width:`${sttPct}%`, background:"#818cf8" }} className="h-full" />
                                  </div>
                                  <span className="text-violet-400 text-[10px]">{sttPct}%</span>
                                </div>
                              </td>
                            </tr>
                            {expanded && (
                              <tr className="bg-white/[0.02] border-b border-white/5">
                                <td colSpan={11} className="px-6 py-4">
                                  <p className="text-[10px] text-slate-500 uppercase tracking-widest mb-3">Detail — Call #{c.id} · {c.engine}</p>
                                  <div className="flex flex-wrap gap-6 mb-3">
                                    {[["Avg STT",fms(c.stt_avg),"#818cf8"],["Avg LLM",fms(c.llm_avg),"#34d399"],["Avg TTS",fms(c.tts_avg),"#fb923c"],
                                      ["STT %",`${Math.round((c.stt_avg/c.total_avg)*100)}%`,"#818cf8"],["LLM %",`${Math.round((c.llm_avg/c.total_avg)*100)}%`,"#34d399"]
                                    ].map(([l,v,col]) => (
                                      <div key={l as string}>
                                        <p className="text-[9px] text-slate-500 uppercase tracking-widest">{l}</p>
                                        <p className="text-lg font-bold mt-0.5" style={{ color: col as string }}>{v}</p>
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

          {/* MODELS TAB */}
          {tab === "models" && (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
              <ModelCard title="STT Models" icon={Mic}     accent="#818cf8" models={data.stt_models} />
              <ModelCard title="LLM Models" icon={Brain}   accent="#34d399" models={data.llm_models} />
              <ModelCard title="TTS Models" icon={Volume2} accent="#fb923c" models={data.tts_models} />
              <div className="md:col-span-3 flex items-center gap-6 px-1">
                {[["#818cf8","STT"],["#34d399","LLM"],["#fb923c","TTS"]].map(([c,l]) => (
                  <span key={l} className="flex items-center gap-1.5 text-xs text-slate-500">
                    <span className="h-2 w-2 rounded-full" style={{ background: c }} />{l} stage
                  </span>
                ))}
                <span className="text-xs text-slate-600 ml-auto font-mono uppercase tracking-widest">Ranked fastest → slowest</span>
              </div>
            </div>
          )}

          {/* ── TREND TAB ── */}
          {tab === "trend" && (
            <div className="space-y-4">
              <p className="text-[10px] text-slate-500 uppercase tracking-widest">Daily avg turn latency per engine</p>
              {data.trend.length === 0 ? (
                <p className="text-center py-16 text-slate-600">No trend data for this period.</p>
              ) : (
                <div className="glass rounded-2xl border border-white/10 overflow-hidden">
                  <table className="w-full text-xs text-slate-300">
                    <thead>
                      <tr className="bg-white/5 border-b border-white/10 text-slate-500">
                        {["Date","Engine","Avg","Turns","Bar"].map(h => (
                          <th key={h} className="px-4 py-3 text-left font-medium">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {data.trend.map((t, i) => {
                        const maxMs = Math.max(...data.trend.map(x => x.avg_ms)) || 1;
                        return (
                          <tr key={i} className="border-b border-white/5 hover:bg-white/5">
                            <td className="px-4 py-2 font-mono text-slate-400">{t.day}</td>
                            <td className="px-4 py-2 font-mono text-[10px]" style={{ color: engineColor(t.engine) }}>{t.engine}</td>
                            <td className="px-4 py-2 font-bold text-slate-200">{fms(t.avg_ms)}</td>
                            <td className="px-4 py-2 text-slate-500">{t.turns}</td>
                            <td className="px-4 py-2 w-32">
                              <div className="h-[4px] rounded bg-white/10 overflow-hidden">
                                <div className="h-full rounded" style={{ width:`${(t.avg_ms/maxMs)*100}%`, background: engineColor(t.engine) }} />
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
              {data.trend.length > 0 && <DoDSummary trend={data.trend} />}
            </div>
          )}
          {summary && (
            <div className="space-y-4 rounded-3xl border border-white/10 bg-white/5 p-5">
              <div className="flex items-center justify-between">
                <h3 className="text-lg font-semibold text-white">Campaign & quote insights</h3>
                <span className="text-xs text-slate-400">{summaryLoading ? "Loading…" : "Live"}</span>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                {summary.campaign_funnel.slice(0, 4).map((item) => (
                  <div key={item.status} className="rounded-2xl border border-white/10 bg-white/10 p-3 text-sm">
                    <p className="text-[10px] uppercase tracking-[0.3em] text-slate-500">{item.status}</p>
                    <p className="text-2xl font-semibold text-white">{item.count}</p>
                    <p className="text-xs text-slate-400">{item.percent}%</p>
                  </div>
                ))}
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                <div>
                  <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Conversion trends</p>
                  <div className="mt-2 space-y-2 text-sm text-slate-200">
                    {summary.campaign_conversion_trends.slice(0, 3).map((row) => (
                      <div key={row.name} className="flex items-center justify-between">
                        <span>{row.name}</span>
                        <span className="text-xs text-slate-400">{row.conversion_rate}%</span>
                      </div>
                    ))}
                  </div>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Campaign status over time</p>
                  <div className="mt-2 grid gap-1 text-xs text-slate-400">
                    {summary.campaign_status_over_time.slice(-4).map((row) => (
                      <div key={`${row.day}-${row.status}`} className="flex justify-between">
                        <span>{row.day}</span>
                        <span>{row.status}</span>
                        <span>{row.count}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Quote timeline export</p>
                <ul className="mt-2 space-y-2 text-sm text-slate-200">
                  {summary.quote_timeline_export.slice(0, 3).map((quote) => (
                    <li key={quote.quote_id} className="rounded-xl border border-white/5 px-3 py-2">
                      <p className="font-semibold">{quote.quote_number}</p>
                      <p className="text-xs text-slate-400">{quote.status}</p>
                      <p className="text-xs text-slate-500">Created {quote.dates.created_at ?? "—"}</p>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}
          <div className="space-y-4 rounded-3xl border border-white/10 bg-white/5 p-5">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold text-white">Engagement alerts</h3>
              <button
                type="button"
                onClick={evaluateAlerts}
                disabled={alertLoading}
                className="text-xs font-semibold uppercase tracking-[0.3em] text-slate-400 hover:text-white transition"
              >
                Evaluate now
              </button>
            </div>
            <div className="grid gap-3 md:grid-cols-4">
              <label className="block text-xs uppercase tracking-[0.3em] text-slate-400">
                Metric
                <select
                  value={alertMetric}
                  onChange={(event) => setAlertMetric(event.target.value)}
                  className="mt-1 w-full rounded-xl border border-white/10 bg-transparent px-3 py-2 text-white outline-none"
                >
                  {["quote.viewed", "quote.accepted", "quote.rejected", "email.open", "email.reply", "campaign.responded"].map((metric) => (
                    <option key={metric} value={metric}>
                      {metric}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block text-xs uppercase tracking-[0.3em] text-slate-400">
                Threshold
                <input
                  type="number"
                  min={0}
                  value={alertThreshold}
                  onChange={(event) => setAlertThreshold(Number(event.target.value) || 0)}
                  className="mt-1 w-full rounded-xl border border-white/10 bg-transparent px-3 py-2 text-white outline-none"
                />
              </label>
              <label className="block text-xs uppercase tracking-[0.3em] text-slate-400">
                Direction
                <select
                  value={alertDirection}
                  onChange={(event) => setAlertDirection(event.target.value as "gte" | "lte")}
                  className="mt-1 w-full rounded-xl border border-white/10 bg-transparent px-3 py-2 text-white outline-none"
                >
                  <option value="gte">≥</option>
                  <option value="lte">≤</option>
                </select>
              </label>
              <label className="block text-xs uppercase tracking-[0.3em] text-slate-400">
                Channel
                <select
                  value={alertChannel}
                  onChange={(event) => setAlertChannel(event.target.value)}
                  className="mt-1 w-full rounded-xl border border-white/10 bg-transparent px-3 py-2 text-white outline-none"
                >
                  <option value="email">Email</option>
                  <option value="whatsapp">WhatsApp</option>
                  <option value="quote">Quote</option>
                </select>
              </label>
            </div>
            <button
              type="button"
              onClick={createAlert}
              disabled={alertLoading}
              className="w-full rounded-2xl border border-white/20 bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2 text-xs font-semibold uppercase tracking-[0.3em] text-white transition hover:opacity-90 disabled:opacity-50"
            >
              {alertLoading ? "Working…" : "Create alert"}
            </button>
            {alertMessage && <p className="text-xs text-slate-400">{alertMessage}</p>}
            <div className="space-y-2">
              {alerts.length === 0 ? (
                <p className="text-xs text-slate-500">No rules configured yet.</p>
              ) : (
                <ul className="space-y-2 text-sm text-slate-200">
                  {alerts.map((alert) => (
                    <li key={alert.id} className="rounded-2xl border border-white/10 bg-white/5 px-3 py-2">
                      <div className="flex items-center justify-between text-xs uppercase tracking-[0.3em] text-slate-400">
                        <span>{alert.metric}</span>
                        <span>{alert.direction === "gte" ? "≥" : "≤"} {alert.threshold}</span>
                      </div>
                      <p className="text-[10px] text-slate-500">Channel: {alert.channel}</p>
                      <p className="text-[10px] text-slate-500">
                        Last triggered: {alert.last_triggered_at ? new Date(alert.last_triggered_at).toLocaleString() : "never"}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

// ModelCard

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
              <div className="flex-1 min-w-0">
                <p className="text-[10px]" style={{ color: col }}>Model #{i+1}</p>
                <p className="font-semibold text-slate-200 text-sm mt-0.5 truncate">{m.model}</p>
                <p className="text-[10px] text-slate-500 uppercase tracking-widest">{m.provider} · {m.rows} turns</p>
              </div>
              <p className="text-xl font-black ml-4" style={{ color: col }}>{fms(m.avg)}</p>
            </div>
            <HorizBar value={m.avg} max={maxVal} color={col} />
            <p className="text-[10px] text-slate-600 mt-1">min {fms(m.min)} · max {fms(m.max)}</p>
          </div>
        );
      })}
    </div>
  );
}

// DoDSummary

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
    const latestDays = days.slice(-2);
    const from = map[e][latestDays[0]];
    const to   = map[e][latestDays[1]];
    if (from && to) items.push({ engine: e, from, to, pct: ((to - from) / from) * 100 });
  }
  if (!items.length) return null;
  items.sort((a, b) => a.pct - b.pct);

  return (
    <div>
      <p className="text-[10px] text-slate-500 uppercase tracking-widest mb-3">
        Latest day-over-day · {days.at(-2)} → {days.at(-1)}
      </p>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {items.map(item => {
          const improved = item.pct < 0;
          const col = improved ? "#34d399" : "#f87171";
          return (
            <div key={item.engine}
              className="glass rounded-xl px-4 py-3 border border-white/10"
              style={{ borderLeftColor: engineColor(item.engine), borderLeftWidth: 3 }}>
              <p className="text-[10px] font-mono text-slate-400">{item.engine}</p>
              <div className="flex items-center justify-between mt-1">
                <span className="text-sm text-slate-400 font-mono tracking-tight">{fms(item.from)} → {fms(item.to)}</span>
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
