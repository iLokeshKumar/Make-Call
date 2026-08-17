"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Phone, Clock, TrendingUp, ArrowUpRight, ArrowDownLeft, Loader2 } from "lucide-react";
import clsx from "clsx";
import { apiFetch } from "@/utils/apiFetch";

// ── Types ──────────────────────────────────────────────────────────────────

type OutcomeRow = { status: string; count: number; pct: number; connected: boolean };
type DailyRow   = { day: string; status: string; count: number };
type HourRow    = { hour: number; count: number };
type AgentRow   = { agent_id: number; agent_name: string; total: number; connected: number; avg_duration: number; connect_rate: number };

type VoiceData = {
  summary: {
    total_calls: number;
    connected: number;
    connect_rate_pct: number;
    avg_duration_seconds: number;
    total_minutes: number;
    outbound: number;
    inbound: number;
  };
  outcome_distribution: OutcomeRow[];
  daily_volume: DailyRow[];
  hourly_heatmap: HourRow[];
  agent_stats: AgentRow[];
};

// ── Date Presets ───────────────────────────────────────────────────────────

type Preset = "today" | "yesterday" | "15d" | "30d" | "3mo" | "custom";

function presetToDates(p: Preset): { from: string; to: string } {
  const pad = (n: number) => String(n).padStart(2, "0");
  const fmt = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const today = new Date();
  const shift = (n: number) => { const d = new Date(); d.setDate(d.getDate() + n); return d; };

  switch (p) {
    case "today":     return { from: fmt(today), to: fmt(today) };
    case "yesterday": { const y = shift(-1); return { from: fmt(y), to: fmt(y) }; }
    case "15d":       return { from: fmt(shift(-14)), to: fmt(today) };
    case "30d":       return { from: fmt(shift(-29)), to: fmt(today) };
    case "3mo":       return { from: fmt(shift(-89)), to: fmt(today) };
    default:          return { from: fmt(shift(-29)), to: fmt(today) };
  }
}

// ── Colour helpers ─────────────────────────────────────────────────────────

const STATUS_HEX: Record<string, string> = {
  completed:   "#34d399",
  ended:       "#60a5fa",
  active:      "#a78bfa",
  in_progress: "#a78bfa",
  connected:   "#34d399",
  failed:      "#f87171",
  error:       "#f87171",
  busy:        "#fb923c",
  no_answer:   "#fbbf24",
  cancelled:   "#94a3b8",
  stopped:     "#94a3b8",
  low_balance: "#f472b6",
  default:     "#64748b",
};

const hex = (s: string) => STATUS_HEX[s] ?? STATUS_HEX.default;

function fmtDur(s: number) {
  if (!s) return "—";
  const m = Math.floor(s / 60), sec = Math.round(s % 60);
  return m > 0 ? `${m}m ${sec}s` : `${sec}s`;
}

// ── Donut Chart ────────────────────────────────────────────────────────────

function DonutChart({ data }: { data: OutcomeRow[] }) {
  const SIZE = 180, R = 70, STROKE = 22;
  const circumference = 2 * Math.PI * R;
  const total = data.reduce((s, d) => s + d.count, 0);
  if (!total) return <p className="text-slate-600 text-xs text-center py-8">No data</p>;

  let offset = 0;
  const slices = data.map(d => {
    const pct = d.count / total;
    const dash = pct * circumference;
    const gap  = circumference - dash;
    const slice = { ...d, dash, gap, offset };
    offset += dash;
    return slice;
  });

  return (
    <div className="flex flex-col items-center gap-4">
      <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`}>
        <g transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`}>
          {slices.map((s, i) => (
            <circle
              key={i}
              cx={SIZE / 2} cy={SIZE / 2} r={R}
              fill="none"
              stroke={hex(s.status)}
              strokeWidth={STROKE}
              strokeDasharray={`${s.dash} ${s.gap}`}
              strokeDashoffset={-s.offset}
              strokeLinecap="butt"
            />
          ))}
        </g>
        <text x={SIZE / 2} y={SIZE / 2 - 6} textAnchor="middle" className="fill-slate-100 text-2xl font-black" fontSize={28} fontWeight={800} fill="#f1f5f9">{total}</text>
        <text x={SIZE / 2} y={SIZE / 2 + 14} textAnchor="middle" fontSize={10} fill="#64748b" fontWeight={600} letterSpacing={1.5}>TOTAL</text>
      </svg>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 w-full max-w-[200px]">
        {data.map(d => (
          <div key={d.status} className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full flex-shrink-0" style={{ background: hex(d.status) }} />
            <span className="text-[10px] text-slate-400 truncate capitalize">{d.status.replace(/_/g, " ")}</span>
            <span className="text-[10px] font-bold ml-auto" style={{ color: hex(d.status) }}>{d.count}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Stacked Bar Chart (daily volume) ──────────────────────────────────────

function DailyBarChart({ data }: { data: DailyRow[] }) {
  const [tooltip, setTooltip] = useState<{ day: string; rows: DailyRow[]; x: number } | null>(null);

  const days = useMemo(() => {
    const map: Record<string, DailyRow[]> = {};
    for (const r of data) {
      if (!map[r.day]) map[r.day] = [];
      map[r.day].push(r);
    }
    return Object.entries(map).sort(([a], [b]) => a.localeCompare(b));
  }, [data]);

  if (!days.length) return <p className="text-slate-600 text-xs text-center py-8">No data</p>;

  const maxDay = Math.max(...days.map(([, rows]) => rows.reduce((s, r) => s + r.count, 0)));
  const BAR_W = Math.max(8, Math.min(28, Math.floor(560 / days.length) - 3));
  const H = 120;

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${Math.max(days.length * (BAR_W + 3), 200)} ${H + 28}`}
        className="w-full overflow-visible"
        onMouseLeave={() => setTooltip(null)}
      >
        {days.map(([day, rows], di) => {
          const total = rows.reduce((s, r) => s + r.count, 0);
          const x = di * (BAR_W + 3);
          let yOffset = H;
          return (
            <g key={day} onMouseEnter={() => setTooltip({ day, rows, x })}>
              {rows.map((r, ri) => {
                const bh = Math.max(2, (r.count / (maxDay || 1)) * H);
                yOffset -= bh;
                return (
                  <rect key={ri} x={x} y={yOffset} width={BAR_W} height={bh}
                    fill={hex(r.status)} rx={ri === rows.length - 1 ? 2 : 0} opacity={0.85} />
                );
              })}
              {days.length <= 20 && (
                <text x={x + BAR_W / 2} y={H + 16} textAnchor="middle" fontSize={7} fill="#475569">
                  {day.slice(5)}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      {tooltip && (
        <div className="absolute top-0 left-0 z-10 pointer-events-none bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs shadow-xl"
          style={{ transform: `translateX(${Math.min(tooltip.x, 260)}px) translateY(-80px)` }}>
          <p className="text-slate-400 font-mono mb-1">{tooltip.day}</p>
          {tooltip.rows.map(r => (
            <div key={r.status} className="flex items-center gap-2">
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: hex(r.status) }} />
              <span className="text-slate-300 capitalize">{r.status.replace(/_/g, " ")}</span>
              <span className="font-bold ml-auto" style={{ color: hex(r.status) }}>{r.count}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Hourly Heatmap ─────────────────────────────────────────────────────────

function HourlyHeatmap({ data }: { data: HourRow[] }) {
  const max = Math.max(...data.map(d => d.count), 1);
  const fmt = (h: number) => {
    const ampm = h < 12 ? "am" : "pm";
    const h12 = h % 12 || 12;
    return `${h12}${ampm}`;
  };
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-12 gap-1">
        {data.map(d => {
          const intensity = d.count / max;
          const bg = intensity === 0
            ? "bg-slate-800/40"
            : intensity < 0.3 ? "bg-violet-900/40"
            : intensity < 0.6 ? "bg-violet-700/60"
            : intensity < 0.85 ? "bg-violet-500/80"
            : "bg-violet-400";
          return (
            <div
              key={d.hour}
              title={`${fmt(d.hour)}: ${d.count} calls`}
              className={clsx("h-7 rounded flex items-center justify-center cursor-default transition-colors", bg)}
            >
              {d.count > 0 && (
                <span className="text-[8px] font-bold text-white/80">{d.count}</span>
              )}
            </div>
          );
        })}
      </div>
      <div className="grid grid-cols-12 gap-1">
        {data.map(d => (
          <div key={d.hour} className="text-center">
            <span className="text-[8px] text-slate-600">{d.hour % 3 === 0 ? fmt(d.hour) : ""}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Summary Card ───────────────────────────────────────────────────────────

function SummaryCard({ label, value, sub, color, icon: Icon }: {
  label: string; value: string; sub?: string; color: string; icon: React.ElementType
}) {
  return (
    <div className="glass rounded-2xl p-5 border border-white/10" style={{ borderLeftColor: color, borderLeftWidth: 3 }}>
      <div className="flex items-start justify-between">
        <div>
          <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest">{label}</p>
          <p className="mt-2 text-2xl font-bold leading-none" style={{ color }}>{value}</p>
          {sub && <p className="text-[10px] text-slate-500 mt-1">{sub}</p>}
        </div>
        <div className="p-2 rounded-xl" style={{ background: `${color}18` }}>
          <Icon className="h-5 w-5" style={{ color }} />
        </div>
      </div>
    </div>
  );
}

// ── Agent Table ────────────────────────────────────────────────────────────

function AgentTable({ data }: { data: AgentRow[] }) {
  if (!data.length) return <p className="text-slate-600 text-xs text-center py-6">No agent data.</p>;
  return (
    <div className="overflow-x-auto rounded-xl border border-white/10">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-white/10 bg-slate-800/40">
            {["Agent", "Total", "Connected", "Connect Rate", "Avg Duration"].map(h => (
              <th key={h} className="px-4 py-2.5 text-left text-[10px] font-bold uppercase tracking-widest text-slate-500">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-white/5">
          {data.map(a => (
            <tr key={a.agent_id} className="hover:bg-white/[0.03] transition-colors">
              <td className="px-4 py-3 font-semibold text-slate-200">{a.agent_name}</td>
              <td className="px-4 py-3 font-mono text-slate-300">{a.total}</td>
              <td className="px-4 py-3 font-mono text-emerald-400">{a.connected}</td>
              <td className="px-4 py-3">
                <div className="flex items-center gap-2">
                  <div className="flex-1 h-1 bg-slate-800 rounded-full overflow-hidden">
                    <div className="h-full rounded-full bg-violet-500" style={{ width: `${a.connect_rate}%` }} />
                  </div>
                  <span className="font-mono text-slate-300 w-10 text-right">{a.connect_rate}%</span>
                </div>
              </td>
              <td className="px-4 py-3 font-mono text-slate-400">{fmtDur(a.avg_duration)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Main Component ─────────────────────────────────────────────────────────

const PRESETS: { id: Preset; label: string }[] = [
  { id: "today",     label: "Today" },
  { id: "yesterday", label: "Yesterday" },
  { id: "15d",       label: "15 Days" },
  { id: "30d",       label: "30 Days" },
  { id: "3mo",       label: "3 Months" },
  { id: "custom",    label: "Custom" },
];

export default function VoiceOverviewTab({
  apiBase,
  sessionTimeout,
}: {
  apiBase: string;
  sessionTimeout: () => void;
}) {
  const [preset, setPreset]       = useState<Preset>("30d");
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo]   = useState("");
  const [data, setData]           = useState<VoiceData | null>(null);
  const [loading, setLoading]     = useState(false);

  const { from, to } = useMemo(() => {
    if (preset === "custom" && customFrom && customTo) return { from: customFrom, to: customTo };
    if (preset !== "custom") return presetToDates(preset);
    return { from: "", to: "" };
  }, [preset, customFrom, customTo]);

  const fetch = useCallback(async () => {
    if (!from || !to) return;
    setLoading(true);
    try {
      const res = await apiFetch(`${apiBase}/analytics/voice-overview?date_from=${from}&date_to=${to}`);
      if (res.status === 401) { sessionTimeout(); return; }
      if (res.ok) setData(await res.json());
    } catch {} finally { setLoading(false); }
  }, [from, to, apiBase, sessionTimeout]);

  useEffect(() => { fetch(); }, [fetch]);

  const s = data?.summary;

  return (
    <div className="space-y-6">
      {/* ── Date range picker ── */}
      <div className="glass rounded-2xl border border-white/10 p-4 flex flex-wrap items-center gap-3">
        <div className="flex gap-1 flex-wrap">
          {PRESETS.map(p => (
            <button
              key={p.id}
              onClick={() => setPreset(p.id)}
              className={clsx(
                "rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors",
                preset === p.id
                  ? "bg-violet-600 text-white shadow"
                  : "text-slate-400 hover:text-slate-200 hover:bg-slate-800"
              )}
            >
              {p.label}
            </button>
          ))}
        </div>
        {preset === "custom" && (
          <div className="flex items-center gap-2 ml-auto">
            <input
              type="date" value={customFrom} onChange={e => setCustomFrom(e.target.value)}
              className="rounded-lg border border-slate-700 bg-slate-800 px-2 py-1 text-xs text-slate-200 focus:outline-none focus:border-violet-500"
            />
            <span className="text-slate-600 text-xs">→</span>
            <input
              type="date" value={customTo} onChange={e => setCustomTo(e.target.value)}
              className="rounded-lg border border-slate-700 bg-slate-800 px-2 py-1 text-xs text-slate-200 focus:outline-none focus:border-violet-500"
            />
          </div>
        )}
        {from && to && preset !== "custom" && (
          <span className="ml-auto text-[10px] text-slate-600 font-mono">{from} → {to}</span>
        )}
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-16 gap-2 text-slate-500">
          <Loader2 className="h-5 w-5 animate-spin text-violet-500" />
          Loading voice analytics…
        </div>
      ) : !data ? null : (
        <>
          {/* ── Summary cards ── */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <SummaryCard label="Total Calls" value={String(s!.total_calls)} sub={`${s!.outbound} out · ${s!.inbound} in`} color="#a78bfa" icon={Phone} />
            <SummaryCard label="Connected" value={String(s!.connected)} sub={`${s!.connect_rate_pct}% connect rate`} color="#34d399" icon={TrendingUp} />
            <SummaryCard label="Avg Duration" value={fmtDur(s!.avg_duration_seconds)} sub={`${s!.total_minutes.toFixed(0)} total mins`} color="#60a5fa" icon={Clock} />
            <SummaryCard label="Outbound" value={String(s!.outbound)}
              sub={s!.total_calls ? `${Math.round(s!.outbound / s!.total_calls * 100)}% of calls` : ""}
              color="#fb923c" icon={ArrowUpRight} />
          </div>

          {/* ── Outcome + Daily ── */}
          <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
            <div className="glass rounded-2xl border border-white/10 p-5 lg:col-span-2">
              <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500 mb-4">Outcome Distribution</p>
              <DonutChart data={data.outcome_distribution} />
            </div>
            <div className="glass rounded-2xl border border-white/10 p-5 lg:col-span-3">
              <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500 mb-4">Daily Call Volume</p>
              <DailyBarChart data={data.daily_volume} />
              <div className="flex flex-wrap gap-3 mt-3">
                {data.outcome_distribution.map(d => (
                  <div key={d.status} className="flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-full" style={{ background: hex(d.status) }} />
                    <span className="text-[10px] text-slate-500 capitalize">{d.status.replace(/_/g, " ")}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* ── Hourly heatmap ── */}
          <div className="glass rounded-2xl border border-white/10 p-5">
            <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500 mb-4">Best Calling Hours</p>
            <HourlyHeatmap data={data.hourly_heatmap} />
            <p className="text-[10px] text-slate-600 mt-2">Darker cells = more calls at that hour (UTC)</p>
          </div>

          {/* ── Agent comparison ── */}
          {data.agent_stats.length > 0 && (
            <div className="glass rounded-2xl border border-white/10 p-5">
              <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500 mb-4">
                Voice Agent Performance
              </p>
              <AgentTable data={data.agent_stats} />
            </div>
          )}

          {/* ── Direction split ── */}
          {(s!.outbound > 0 || s!.inbound > 0) && (
            <div className="glass rounded-2xl border border-white/10 p-5">
              <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500 mb-3">Direction Split</p>
              <div className="flex gap-4">
                {[
                  { label: "Outbound", count: s!.outbound, icon: ArrowUpRight, color: "#a78bfa" },
                  { label: "Inbound",  count: s!.inbound,  icon: ArrowDownLeft, color: "#34d399" },
                ].map(d => {
                  const pct = s!.total_calls ? Math.round(d.count / s!.total_calls * 100) : 0;
                  return (
                    <div key={d.label} className="flex-1 rounded-xl border border-white/10 bg-slate-900/30 p-4">
                      <div className="flex items-center gap-2 mb-2">
                        <d.icon className="h-4 w-4" style={{ color: d.color }} />
                        <span className="text-xs font-semibold text-slate-300">{d.label}</span>
                      </div>
                      <p className="text-2xl font-black" style={{ color: d.color }}>{d.count}</p>
                      <div className="mt-2 h-1.5 bg-slate-800 rounded-full overflow-hidden">
                        <div className="h-full rounded-full" style={{ width: `${pct}%`, background: d.color }} />
                      </div>
                      <p className="text-[10px] text-slate-600 mt-1">{pct}% of total</p>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
