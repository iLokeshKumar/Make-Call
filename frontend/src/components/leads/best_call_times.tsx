"use client";

import { useCallback, useEffect, useState } from "react";
import { Clock, Loader2, RefreshCw, TrendingUp } from "lucide-react";

import { apiFetch } from "@/utils/apiFetch";
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || (typeof window !== "undefined" ? (window.location.hostname.includes("ngrok-free.dev") ? `${window.location.protocol}//${window.location.host}` : `${window.location.protocol}//127.0.0.1:6060`) : "http://127.0.0.1:6060");

type Window = {
  datetime: string;
  hour: number;
  day_of_week: string;
  probability: number;
  confidence: "ml" | "heuristic";
};

type BestCallData = {
  lead_id: number;
  model_type: "ml" | "heuristic";
  training_samples: number;
  windows: Window[];
};

type Props = {
  leadId: number;
  onSessionTimeout?: () => void;
  onScheduleCall?: (dt: string) => void;
};

function probColor(p: number): string {
  if (p >= 0.6) return "text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-500/10 border-emerald-200 dark:border-emerald-500/30";
  if (p >= 0.35) return "text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-500/10 border-amber-200 dark:border-amber-500/30";
  return "text-slate-500 dark:text-slate-400 bg-slate-50 dark:bg-slate-800/50 border-slate-200 dark:border-white/10";
}

function probBar(p: number): string {
  if (p >= 0.6) return "bg-emerald-500";
  if (p >= 0.35) return "bg-amber-500";
  return "bg-slate-400";
}

function formatSlot(iso: string): { date: string; time: string } {
  const d = new Date(iso);
  return {
    date: d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" }),
    time: d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }) };
}

export default function BestCallTimes({ leadId, onSessionTimeout, onScheduleCall }: Props) {
  const [data, setData] = useState<BestCallData | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const fetchWindows = useCallback(
    async (quiet = false) => {
      if (!quiet) setLoading(true);
      else setRefreshing(true);
      try {
        const res = await apiFetch(
          `${API_BASE}/crm/leads/${leadId}/best-call-times?n_windows=5&lookahead_hours=72`,
          { }
        );
        if (res.status === 401) { onSessionTimeout?.(); return; }
        if (!res.ok) return;
        setData(await res.json());
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [leadId, onSessionTimeout]
  );

  useEffect(() => { fetchWindows(); }, [fetchWindows]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-xs text-slate-400 dark:text-slate-500 py-2">
        <Loader2 className="h-3.5 w-3.5 animate-spin" /> Predicting best call times...
      </div>
    );
  }

  if (!data || data.windows.length === 0) return null;

  const best = data.windows[0];
  const { date: bestDate, time: bestTime } = formatSlot(best.datetime);

  return (
    <div className="rounded-2xl glass border border-blue-200/60 dark:border-blue-500/20 overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 px-5 py-4 border-b border-slate-200 dark:border-white/10">
        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-blue-100 dark:bg-blue-500/10">
          <TrendingUp className="h-4 w-4 text-blue-600 dark:text-blue-400" />
        </div>
        <div>
          <h3 className="font-semibold text-slate-900 dark:text-white">Predictive Call Windows</h3>
          <p className="text-[11px] text-slate-500 dark:text-slate-400">
            {data.model_type === "ml"
              ? `ML model · ${data.training_samples} training calls`
              : `Heuristic · ${data.training_samples} historical calls`}
          </p>
        </div>
        <button
          onClick={() => fetchWindows(true)}
          disabled={refreshing}
          className="ml-auto text-slate-400 hover:text-blue-500 transition"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} />
        </button>
      </div>

      <div className="p-5 space-y-3">
        {/* Best slot highlight */}
        <div className="rounded-xl bg-blue-50 dark:bg-blue-500/10 border border-blue-200 dark:border-blue-500/30 px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Clock className="h-4 w-4 text-blue-600 dark:text-blue-400" />
            <div>
              <p className="text-xs font-semibold text-blue-900 dark:text-blue-200">Best time to call</p>
              <p className="text-sm font-bold text-blue-700 dark:text-blue-300">
                {bestDate} at {bestTime}
              </p>
            </div>
          </div>
          <div className="text-right">
            <div className="text-lg font-bold text-blue-700 dark:text-blue-300">
              {Math.round(best.probability * 100)}%
            </div>
            <div className="text-[10px] text-blue-500 dark:text-blue-400 uppercase tracking-wide">
              connect rate
            </div>
          </div>
        </div>

        {/* All windows */}
        <div className="space-y-1.5">
          {data.windows.map((w, i) => {
            const { date, time } = formatSlot(w.datetime);
            const pct = Math.round(w.probability * 100);
            return (
              <div
                key={i}
                className={`flex items-center gap-3 rounded-xl border px-3 py-2 ${probColor(w.probability)}`}
              >
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-semibold">{date} · {time}</p>
                  <div className="mt-1 h-1.5 w-full rounded-full bg-white/50 dark:bg-black/20 overflow-hidden">
                    <div
                      className={`h-full rounded-full ${probBar(w.probability)}`}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </div>
                <span className="text-xs font-bold flex-shrink-0">{pct}%</span>
                {onScheduleCall && i === 0 && (
                  <button
                    onClick={() => onScheduleCall(w.datetime)}
                    className="flex-shrink-0 rounded-lg bg-blue-500 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-blue-600 transition"
                  >
                    Schedule
                  </button>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
