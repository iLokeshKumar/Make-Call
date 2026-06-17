"use client";

import React, { useCallback, useEffect, useState } from "react";
import { Loader2, RefreshCw } from "lucide-react";
import { apiFetch } from "@/utils/apiFetch";

type Preset = "7d" | "30d" | "90d" | "custom";

interface UsageRow {
  service_type: string;
  provider: string;
  model: string | null;
  context: string | null;
  events: number;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  characters: number | null;
  audio_seconds: number | null;
}

interface UsageSummary {
  date_from: string;
  date_to: string;
  rows: UsageRow[];
}

function presetToDates(p: Preset): { from: string; to: string } {
  const to = new Date();
  const from = new Date();
  if (p === "7d") from.setDate(to.getDate() - 7);
  else if (p === "30d") from.setDate(to.getDate() - 30);
  else from.setDate(to.getDate() - 90);
  const fmt = (d: Date) => d.toISOString().slice(0, 10);
  return { from: fmt(from), to: fmt(to) };
}

const fmtN = (v: number | null | undefined) =>
  v == null ? "—" : v.toLocaleString();

const SERVICE_COLORS: Record<string, string> = {
  llm: "text-violet-400 bg-violet-500/10 border-violet-500/30",
  stt: "text-sky-400 bg-sky-500/10 border-sky-500/30",
  tts: "text-emerald-400 bg-emerald-500/10 border-emerald-500/30",
};

function ServiceBadge({ type }: { type: string }) {
  const cls = SERVICE_COLORS[type] ?? "text-slate-400 bg-slate-500/10 border-slate-500/30";
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-bold border uppercase tracking-wide ${cls}`}>
      {type}
    </span>
  );
}

export default function UsageTab({
  apiBase,
  sessionTimeout,
}: {
  apiBase: string;
  sessionTimeout: () => void;
}) {
  const [preset, setPreset] = useState<Preset>("30d");
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");
  const [data, setData] = useState<UsageSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { from, to } =
        preset === "custom"
          ? { from: customFrom, to: customTo }
          : presetToDates(preset);
      const res = await apiFetch(
        `${apiBase}/analytics/usage/summary?date_from=${from}&date_to=${to}`,
        { method: "GET" }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData(await res.json());
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [apiBase, preset, customFrom, customTo, sessionTimeout]);

  useEffect(() => {
    if (preset !== "custom") fetch();
  }, [fetch, preset]);

  // group by service_type
  const grouped: Record<string, UsageRow[]> = {};
  for (const r of data?.rows ?? []) {
    (grouped[r.service_type] ??= []).push(r);
  }

  // totals per service
  const totals = Object.entries(grouped).map(([svc, rows]) => ({
    svc,
    events: rows.reduce((s, r) => s + r.events, 0),
    prompt: rows.reduce((s, r) => s + (r.prompt_tokens ?? 0), 0),
    completion: rows.reduce((s, r) => s + (r.completion_tokens ?? 0), 0),
    total: rows.reduce((s, r) => s + (r.total_tokens ?? 0), 0),
    chars: rows.reduce((s, r) => s + (r.characters ?? 0), 0),
    secs: rows.reduce((s, r) => s + (r.audio_seconds ?? 0), 0),
  }));

  const PRESETS: { label: string; value: Preset }[] = [
    { label: "7 days", value: "7d" },
    { label: "30 days", value: "30d" },
    { label: "90 days", value: "90d" },
    { label: "Custom", value: "custom" },
  ];

  return (
    <div className="space-y-5">
      {/* Controls */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex rounded-xl overflow-hidden border border-white/10">
          {PRESETS.map(p => (
            <button
              key={p.value}
              onClick={() => setPreset(p.value)}
              className={`px-4 py-1.5 text-xs font-semibold transition-all ${
                preset === p.value
                  ? "bg-violet-600 text-white"
                  : "text-slate-400 hover:text-white hover:bg-white/5"
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>

        {preset === "custom" && (
          <div className="flex items-center gap-2">
            <input
              type="date"
              value={customFrom}
              onChange={e => setCustomFrom(e.target.value)}
              className="bg-slate-800 border border-white/10 rounded-lg px-3 py-1.5 text-xs text-white"
            />
            <span className="text-slate-500 text-xs">→</span>
            <input
              type="date"
              value={customTo}
              onChange={e => setCustomTo(e.target.value)}
              className="bg-slate-800 border border-white/10 rounded-lg px-3 py-1.5 text-xs text-white"
            />
            <button
              onClick={fetch}
              disabled={!customFrom || !customTo}
              className="px-3 py-1.5 text-xs bg-violet-600 hover:bg-violet-700 text-white rounded-lg disabled:opacity-40"
            >
              Apply
            </button>
          </div>
        )}

        <button
          onClick={fetch}
          disabled={loading}
          className="ml-auto p-1.5 rounded-lg border border-white/10 text-slate-400 hover:text-white"
        >
          {loading ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <RefreshCw className="h-3.5 w-3.5" />
          )}
        </button>
      </div>

      {error && (
        <p className="text-red-400 text-sm">{error}</p>
      )}

      {loading && !data && (
        <div className="flex justify-center py-16">
          <Loader2 className="h-6 w-6 animate-spin text-violet-400" />
        </div>
      )}

      {data && (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            {totals.map(t => (
              <div key={t.svc} className="bg-slate-900/60 border border-white/8 rounded-xl p-4 space-y-1">
                <div className="flex items-center gap-2">
                  <ServiceBadge type={t.svc} />
                  <span className="text-slate-500 text-xs">{t.events.toLocaleString()} events</span>
                </div>
                {t.svc === "llm" && (
                  <>
                    <div className="text-2xl font-bold text-white">{t.total.toLocaleString()}</div>
                    <div className="text-xs text-slate-500">total tokens</div>
                    <div className="text-xs text-slate-600 mt-1">
                      {t.prompt.toLocaleString()} prompt · {t.completion.toLocaleString()} completion
                    </div>
                  </>
                )}
                {t.svc === "tts" && (
                  <>
                    <div className="text-2xl font-bold text-white">{t.chars.toLocaleString()}</div>
                    <div className="text-xs text-slate-500">characters</div>
                  </>
                )}
                {t.svc === "stt" && (
                  <>
                    <div className="text-2xl font-bold text-white">{t.secs.toFixed(1)}s</div>
                    <div className="text-xs text-slate-500">audio processed</div>
                  </>
                )}
              </div>
            ))}
          </div>

          {/* Detail table */}
          {Object.entries(grouped).map(([svc, rows]) => (
            <div key={svc} className="bg-slate-900/60 border border-white/8 rounded-xl overflow-hidden">
              <div className="px-4 py-3 border-b border-white/8 flex items-center gap-2">
                <ServiceBadge type={svc} />
                <span className="text-sm font-semibold text-white capitalize">{svc} usage breakdown</span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-white/8 text-slate-500">
                      <th className="text-left px-4 py-2">Provider</th>
                      <th className="text-left px-4 py-2">Model</th>
                      <th className="text-left px-4 py-2">Context</th>
                      <th className="text-right px-4 py-2">Events</th>
                      {svc === "llm" && (
                        <>
                          <th className="text-right px-4 py-2">Prompt Tokens</th>
                          <th className="text-right px-4 py-2">Completion</th>
                          <th className="text-right px-4 py-2">Total</th>
                        </>
                      )}
                      {svc === "tts" && <th className="text-right px-4 py-2">Characters</th>}
                      {svc === "stt" && <th className="text-right px-4 py-2">Audio (s)</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r, i) => (
                      <tr key={i} className="border-b border-white/5 hover:bg-white/3 transition-colors">
                        <td className="px-4 py-2.5 font-medium text-white capitalize">{r.provider}</td>
                        <td className="px-4 py-2.5 text-slate-400 font-mono">{r.model ?? "—"}</td>
                        <td className="px-4 py-2.5">
                          {r.context ? (
                            <span className="px-2 py-0.5 rounded bg-white/5 text-slate-400 border border-white/10">
                              {r.context}
                            </span>
                          ) : "—"}
                        </td>
                        <td className="px-4 py-2.5 text-right text-slate-300">{fmtN(r.events)}</td>
                        {svc === "llm" && (
                          <>
                            <td className="px-4 py-2.5 text-right text-sky-400">{fmtN(r.prompt_tokens)}</td>
                            <td className="px-4 py-2.5 text-right text-emerald-400">{fmtN(r.completion_tokens)}</td>
                            <td className="px-4 py-2.5 text-right text-violet-300 font-semibold">{fmtN(r.total_tokens)}</td>
                          </>
                        )}
                        {svc === "tts" && (
                          <td className="px-4 py-2.5 text-right text-emerald-400">{fmtN(r.characters)}</td>
                        )}
                        {svc === "stt" && (
                          <td className="px-4 py-2.5 text-right text-sky-400">
                            {r.audio_seconds != null ? r.audio_seconds.toFixed(1) : "—"}
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}

          {data.rows.length === 0 && (
            <div className="text-center py-16 text-slate-500 text-sm">
              No usage data for this period. Usage is recorded once the voice pipeline runs a turn.
            </div>
          )}
        </>
      )}
    </div>
  );
}
