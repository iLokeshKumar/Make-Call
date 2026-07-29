"use client";

import { useEffect, useState, useCallback } from "react";
import { Loader2, CheckCircle, XCircle, Clock, RefreshCw, Filter } from "lucide-react";
import { apiFetch } from "@/utils/apiFetch";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  (typeof window !== "undefined"
    ? window.location.hostname.includes("ngrok-free.dev")
      ? `${window.location.protocol}//${window.location.host}`
      : `${window.location.protocol}//127.0.0.1:6060`
    : "http://127.0.0.1:6060");

type LogRow = {
  id: number;
  tool_name: string;
  status: "success" | "error" | "timeout";
  duration_ms: number;
  error_message: string | null;
  user_id: number | null;
  interaction_id: number | null;
  created_at: string;
};

type SummaryRow = {
  tool_name: string;
  total: number;
  success: number;
  error: number;
  timeout: number;
  avg_ms: number;
};

const STATUS_STYLE: Record<string, string> = {
  success: "text-emerald-600 dark:text-emerald-400",
  error: "text-rose-600 dark:text-rose-400",
  timeout: "text-amber-600 dark:text-amber-400",
};

const STATUS_ICON = {
  success: <CheckCircle className="w-3.5 h-3.5 inline mr-1" />,
  error: <XCircle className="w-3.5 h-3.5 inline mr-1" />,
  timeout: <Clock className="w-3.5 h-3.5 inline mr-1" />,
};

export default function ToolCallLogsTab({ sessionTimeout }: { sessionTimeout: () => void }) {
  const [logs, setLogs] = useState<LogRow[]>([]);
  const [summary, setSummary] = useState<SummaryRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterTool, setFilterTool] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [lookbackDays, setLookbackDays] = useState(7);
  const [view, setView] = useState<"logs" | "summary">("summary");

  const fetchLogs = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: "100" });
      if (filterTool) params.set("tool_name", filterTool);
      if (filterStatus) params.set("status", filterStatus);

      const [logsRes, summaryRes] = await Promise.all([
        apiFetch(`${API_BASE}/crm/tool-logs?${params}`, { sessionTimeout }),
        apiFetch(`${API_BASE}/crm/tool-logs/summary?lookback_days=${lookbackDays}`, { sessionTimeout }),
      ]);
      setLogs(logsRes.logs ?? []);
      setSummary(summaryRes.summary ?? []);
    } catch {
      // handled by apiFetch
    } finally {
      setLoading(false);
    }
  }, [filterTool, filterStatus, lookbackDays, sessionTimeout]);

  useEffect(() => { fetchLogs(); }, [fetchLogs]);

  const uniqueTools = Array.from(new Set(logs.map((l) => l.tool_name))).sort();

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex gap-2">
          <button
            onClick={() => setView("summary")}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              view === "summary"
                ? "bg-violet-600 text-white"
                : "text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800"
            }`}
          >
            Summary
          </button>
          <button
            onClick={() => setView("logs")}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              view === "logs"
                ? "bg-violet-600 text-white"
                : "text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800"
            }`}
          >
            Raw Logs
          </button>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={lookbackDays}
            onChange={(e) => setLookbackDays(Number(e.target.value))}
            className="text-xs rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2 py-1.5 text-slate-700 dark:text-slate-300"
          >
            {[1, 7, 14, 30].map((d) => (
              <option key={d} value={d}>Last {d}d</option>
            ))}
          </select>
          <button
            onClick={fetchLogs}
            disabled={loading}
            className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 dark:text-slate-400 transition-colors disabled:opacity-40"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      {/* Summary View */}
      {view === "summary" && (
        loading ? (
          <div className="flex justify-center py-12"><Loader2 className="w-6 h-6 animate-spin text-violet-500" /></div>
        ) : summary.length === 0 ? (
          <div className="text-center py-12 text-slate-400 text-sm">No tool calls recorded in the last {lookbackDays} day{lookbackDays > 1 ? "s" : ""}.</div>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-slate-200 dark:border-slate-700">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 dark:bg-slate-800/60 text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
                <tr>
                  <th className="px-4 py-3 text-left">Tool</th>
                  <th className="px-4 py-3 text-right">Total</th>
                  <th className="px-4 py-3 text-right text-emerald-600 dark:text-emerald-400">Success</th>
                  <th className="px-4 py-3 text-right text-rose-600 dark:text-rose-400">Error</th>
                  <th className="px-4 py-3 text-right text-amber-600 dark:text-amber-400">Timeout</th>
                  <th className="px-4 py-3 text-right">Avg ms</th>
                  <th className="px-4 py-3 text-right">Success %</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {summary.map((row) => {
                  const pct = row.total > 0 ? Math.round((row.success / row.total) * 100) : 0;
                  return (
                    <tr key={row.tool_name} className="hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors">
                      <td className="px-4 py-3 font-mono text-xs text-slate-700 dark:text-slate-300">{row.tool_name}</td>
                      <td className="px-4 py-3 text-right font-medium text-slate-800 dark:text-slate-200">{row.total}</td>
                      <td className="px-4 py-3 text-right text-emerald-600 dark:text-emerald-400">{row.success}</td>
                      <td className="px-4 py-3 text-right text-rose-600 dark:text-rose-400">{row.error || 0}</td>
                      <td className="px-4 py-3 text-right text-amber-600 dark:text-amber-400">{row.timeout || 0}</td>
                      <td className="px-4 py-3 text-right text-slate-600 dark:text-slate-400">{row.avg_ms}</td>
                      <td className="px-4 py-3 text-right">
                        <span className={`font-semibold ${pct >= 95 ? "text-emerald-600 dark:text-emerald-400" : pct >= 80 ? "text-amber-600 dark:text-amber-400" : "text-rose-600 dark:text-rose-400"}`}>
                          {pct}%
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )
      )}

      {/* Raw Logs View */}
      {view === "logs" && (
        <>
          {/* Filters */}
          <div className="flex gap-2 flex-wrap">
            <div className="flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400">
              <Filter className="w-3.5 h-3.5" /> Filter:
            </div>
            <select
              value={filterTool}
              onChange={(e) => setFilterTool(e.target.value)}
              className="text-xs rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2 py-1 text-slate-700 dark:text-slate-300"
            >
              <option value="">All tools</option>
              {uniqueTools.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
            <select
              value={filterStatus}
              onChange={(e) => setFilterStatus(e.target.value)}
              className="text-xs rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2 py-1 text-slate-700 dark:text-slate-300"
            >
              <option value="">All statuses</option>
              <option value="success">Success</option>
              <option value="error">Error</option>
              <option value="timeout">Timeout</option>
            </select>
          </div>

          {loading ? (
            <div className="flex justify-center py-12"><Loader2 className="w-6 h-6 animate-spin text-violet-500" /></div>
          ) : logs.length === 0 ? (
            <div className="text-center py-12 text-slate-400 text-sm">No tool calls found.</div>
          ) : (
            <div className="overflow-x-auto rounded-xl border border-slate-200 dark:border-slate-700">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 dark:bg-slate-800/60 text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
                  <tr>
                    <th className="px-4 py-3 text-left">Time</th>
                    <th className="px-4 py-3 text-left">Tool</th>
                    <th className="px-4 py-3 text-left">Status</th>
                    <th className="px-4 py-3 text-right">ms</th>
                    <th className="px-4 py-3 text-left">Error</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                  {logs.map((row) => (
                    <tr key={row.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors">
                      <td className="px-4 py-2.5 text-xs text-slate-500 dark:text-slate-400 whitespace-nowrap">
                        {new Date(row.created_at).toLocaleString()}
                      </td>
                      <td className="px-4 py-2.5 font-mono text-xs text-slate-700 dark:text-slate-300">{row.tool_name}</td>
                      <td className={`px-4 py-2.5 text-xs font-medium ${STATUS_STYLE[row.status] ?? ""}`}>
                        {STATUS_ICON[row.status as keyof typeof STATUS_ICON]}
                        {row.status}
                      </td>
                      <td className="px-4 py-2.5 text-right text-xs text-slate-500 dark:text-slate-400">{row.duration_ms}</td>
                      <td className="px-4 py-2.5 text-xs text-rose-600 dark:text-rose-400 max-w-xs truncate">
                        {row.error_message ?? "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
