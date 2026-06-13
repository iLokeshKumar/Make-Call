"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity, AlertCircle, BarChart3, DollarSign, Gauge, Loader2,
  RefreshCw, TrendingUp,
} from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { apiFetch } from "@/utils/apiFetch";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || (typeof window !== "undefined" ? (window.location.hostname.includes("ngrok-free.dev") ? `${window.location.protocol}//${window.location.host}` : `${window.location.protocol}//127.0.0.1:6060`) : "http://127.0.0.1:6060");

// Types

type DispatchRow = { day: string; channel: string; count: number };

type FunnelData = Record<string, {
  dispatched: number;
  delivered: number;
  replied: number;
  converted: number;
}>;

type CostRow = { stage: string; cost_usd: number; leads: number };
type LatencyRow = { task_type: string; p50_ms: number; p95_ms: number; count: number };

// Channel colors — consistent across charts

const CHANNEL_COLORS: Record<string, string> = {
  email:    "bg-indigo-500",
  whatsapp: "bg-emerald-500",
  call:     "bg-amber-500",
  sms:      "bg-rose-500",
  unknown:  "bg-slate-500",
};

function channelColor(ch: string): string {
  return CHANNEL_COLORS[ch] ?? "bg-slate-500";
}

// Chart: dispatches by channel (stacked vertical bars per day)

function DispatchesChart({ data }: { data: DispatchRow[] }) {
  // Group by day, channels as segments
  const byDay = useMemo(() => {
    const map = new Map<string, Record<string, number>>();
    for (const row of data) {
      const day = map.get(row.day) ?? {};
      day[row.channel] = (day[row.channel] ?? 0) + row.count;
      map.set(row.day, day);
    }
    return Array.from(map.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [data]);

  const maxDayTotal = useMemo(() => {
    return Math.max(1, ...byDay.map(([, ch]) => Object.values(ch).reduce((s, n) => s + n, 0)));
  }, [byDay]);

  const channels = useMemo(() => {
    const set = new Set<string>();
    for (const row of data) set.add(row.channel);
    return Array.from(set).sort();
  }, [data]);

  if (byDay.length === 0) {
    return <EmptyState message="No outbound interactions in this window." />;
  }

  return (
    <div className="space-y-2">
      <div className="flex gap-3 text-xs text-slate-400 mb-1">
        {channels.map(ch => (
          <div key={ch} className="flex items-center gap-1.5">
            <span className={`w-2.5 h-2.5 rounded-sm ${channelColor(ch)}`} />
            <span>{ch}</span>
          </div>
        ))}
      </div>
      <div className="flex items-end gap-1 h-40">
        {byDay.map(([day, counts]) => {
          const total = Object.values(counts).reduce((s, n) => s + n, 0);
          const heightPct = (total / maxDayTotal) * 100;
          return (
            <div key={day} className="flex-1 flex flex-col justify-end group relative">
              <div
                className="flex flex-col-reverse rounded-t overflow-hidden"
                style={{ height: `${heightPct}%` }}
              >
                {channels.map(ch => {
                  const c = counts[ch] ?? 0;
                  if (c === 0) return null;
                  const segPct = (c / total) * 100;
                  return <div key={ch} className={channelColor(ch)} style={{ height: `${segPct}%` }} />;
                })}
              </div>
              {/* Tooltip */}
              <div className="absolute bottom-full mb-1 left-1/2 -translate-x-1/2 bg-slate-900 border border-white/10 rounded px-2 py-1 text-xs text-slate-200 whitespace-nowrap opacity-0 group-hover:opacity-100 pointer-events-none z-10">
                <div className="font-medium">{day}</div>
                {channels.map(ch => counts[ch] ? (
                  <div key={ch} className="flex items-center gap-1.5">
                    <span className={`w-2 h-2 rounded-sm ${channelColor(ch)}`} />
                    <span>{ch}: {counts[ch]}</span>
                  </div>
                ) : null)}
              </div>
            </div>
          );
        })}
      </div>
      <div className="flex justify-between text-xs text-slate-600">
        <span>{byDay[0]?.[0]}</span>
        <span>{byDay[byDay.length - 1]?.[0]}</span>
      </div>
    </div>
  );
}

// Chart: funnel (one row per channel; horizontal segments)

function FunnelChart({ data }: { data: FunnelData }) {
  const channels = Object.keys(data).sort();
  if (channels.length === 0) {
    return <EmptyState message="No funnel data in this window." />;
  }

  return (
    <div className="space-y-3">
      {channels.map(ch => {
        const row = data[ch];
        const max = Math.max(row.dispatched, 1);
        const stages = [
          { key: "dispatched", value: row.dispatched, color: "bg-indigo-500/70" },
          { key: "delivered",  value: row.delivered,  color: "bg-indigo-500/50" },
          { key: "replied",    value: row.replied,    color: "bg-emerald-500/60" },
          { key: "converted",  value: row.converted,  color: "bg-amber-500/70" },
        ];
        return (
          <div key={ch}>
            <div className="flex items-center gap-2 mb-1">
              <span className={`w-2.5 h-2.5 rounded-sm ${channelColor(ch)}`} />
              <span className="text-sm text-slate-300 font-medium capitalize">{ch}</span>
            </div>
            <div className="grid grid-cols-4 gap-1.5">
              {stages.map(s => (
                <div key={s.key} className="relative">
                  <div className="h-7 rounded bg-black/30 relative overflow-hidden">
                    <div className={s.color} style={{ width: `${(s.value / max) * 100}%`, height: "100%" }} />
                  </div>
                  <div className="mt-0.5 flex justify-between text-xs">
                    <span className="text-slate-500 capitalize">{s.key}</span>
                    <span className="text-slate-300 font-mono">{s.value}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// Chart: cost by stage (horizontal bar)

function CostChart({ data }: { data: CostRow[] }) {
  if (data.length === 0) {
    return <EmptyState message="No completed tasks with cost data yet." />;
  }
  const maxCost = Math.max(...data.map(r => r.cost_usd), 0.01);
  return (
    <div className="space-y-2">
      {data.map(row => (
        <div key={row.stage}>
          <div className="flex justify-between text-sm mb-0.5">
            <span className="text-slate-300 capitalize">{row.stage.replace("_", " ")}</span>
            <span className="text-slate-500 font-mono">
              ${row.cost_usd.toFixed(4)} <span className="text-slate-600">· {row.leads} leads</span>
            </span>
          </div>
          <div className="h-5 rounded bg-black/30 relative overflow-hidden">
            <div
              className="bg-gradient-to-r from-amber-500/70 to-rose-500/60 h-full"
              style={{ width: `${(row.cost_usd / maxCost) * 100}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

// Chart: latency percentiles

function LatencyChart({ data }: { data: LatencyRow[] }) {
  if (data.length === 0) {
    return <EmptyState message="No latency data yet. Run some tasks to populate." />;
  }
  const maxLatency = Math.max(...data.map(r => r.p95_ms), 1);
  return (
    <div className="space-y-3">
      {data.map(row => (
        <div key={row.task_type}>
          <div className="flex justify-between text-sm mb-1">
            <span className="text-slate-300 font-mono text-xs">{row.task_type}</span>
            <span className="text-slate-600 text-xs">{row.count} tasks</span>
          </div>
          <div className="relative h-5 rounded bg-black/30 overflow-hidden">
            <div
              className="bg-emerald-500/60 absolute h-full"
              style={{ width: `${(row.p50_ms / maxLatency) * 100}%` }}
              title={`p50: ${row.p50_ms}ms`}
            />
            <div
              className="bg-amber-500/60 absolute h-full"
              style={{
                left: `${(row.p50_ms / maxLatency) * 100}%`,
                width: `${((row.p95_ms - row.p50_ms) / maxLatency) * 100}%`,
              }}
              title={`p95: ${row.p95_ms}ms`}
            />
          </div>
          <div className="flex justify-between text-xs text-slate-500 mt-0.5">
            <span>p50: {row.p50_ms}ms</span>
            <span>p95: {row.p95_ms}ms</span>
          </div>
        </div>
      ))}
    </div>
  );
}

// Card shell

function Card({ icon: Icon, title, children, accent = "indigo" }: {
  icon: typeof BarChart3; title: string; children: React.ReactNode; accent?: string;
}) {
  const accentColor = {
    indigo: "text-indigo-400",
    emerald: "text-emerald-400",
    amber: "text-amber-400",
    rose: "text-rose-400",
  }[accent] ?? "text-indigo-400";
  return (
    <div className="border border-white/10 rounded-lg bg-white/3 p-4">
      <div className={`flex items-center gap-2 mb-3 ${accentColor}`}>
        <Icon className="w-4 h-4" />
        <h2 className="font-semibold text-sm">{title}</h2>
      </div>
      {children}
    </div>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="text-center py-8 text-slate-500 text-sm">
      <Activity className="w-8 h-8 mx-auto mb-2 opacity-30" />
      <p>{message}</p>
    </div>
  );
}

// Main page

export default function PerformancePage() {
  const { user, sessionTimeout } = useAuth();
  const [dispatches, setDispatches] = useState<DispatchRow[]>([]);
  const [funnel, setFunnel] = useState<FunnelData>({});
  const [cost, setCost] = useState<CostRow[]>([]);
  const [latency, setLatency] = useState<LatencyRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [days30, setDays30] = useState(30);
  const [days7, setDays7] = useState(7);

  const fetchAll = useCallback(async () => {
    if (!user) return;
    setLoading(true);
    setError(null);
    try {
      const [d, f, c, l] = await Promise.all([
        apiFetch(`${API_BASE}/crm/agent-analytics/dispatches-by-channel?days=${days30}`),
        apiFetch(`${API_BASE}/crm/agent-analytics/channel-funnel?days=${days30}`),
        apiFetch(`${API_BASE}/crm/agent-analytics/cost-by-stage?days=${days7}`),
        apiFetch(`${API_BASE}/crm/agent-analytics/latency-percentiles?days=${days7}`),
      ]);
      if (d.status === 401 || f.status === 401 || c.status === 401 || l.status === 401) {
        sessionTimeout(); return;
      }
      setDispatches(await d.json());
      setFunnel(await f.json());
      setCost(await c.json());
      setLatency(await l.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load analytics");
    } finally {
      setLoading(false);
    }
  }, [user, sessionTimeout, days30, days7]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <TrendingUp className="w-6 h-6 text-indigo-400" />
            Agent Performance
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            Channel mix, funnel, cost, and latency at a glance.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 text-xs text-slate-400">
            <span>Time-series window:</span>
            <select
              value={days30}
              onChange={e => setDays30(Number(e.target.value))}
              className="bg-black/40 border border-white/10 rounded px-2 py-1 text-sm text-slate-300"
            >
              <option value={7}>7d</option>
              <option value={14}>14d</option>
              <option value={30}>30d</option>
              <option value={90}>90d</option>
            </select>
          </div>
          <button
            onClick={fetchAll}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded text-sm text-slate-300 border border-white/10 hover:bg-white/5 disabled:opacity-40"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-4 flex items-start gap-2 rounded border border-red-500/30 bg-red-500/5 px-3 py-2 text-sm text-red-400">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" /><span>{error}</span>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card icon={BarChart3} title={`Dispatches by channel (${days30}d)`} accent="indigo">
          <DispatchesChart data={dispatches} />
        </Card>
        <Card icon={TrendingUp} title={`Channel funnel (${days30}d)`} accent="emerald">
          <FunnelChart data={funnel} />
        </Card>
        <Card icon={DollarSign} title={`LLM cost by stage (${days7}d)`} accent="amber">
          <CostChart data={cost} />
        </Card>
        <Card icon={Gauge} title={`Latency p50/p95 (${days7}d)`} accent="rose">
          <LatencyChart data={latency} />
        </Card>
      </div>
    </div>
  );
}
