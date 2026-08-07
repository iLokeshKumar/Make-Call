"use client";

import { useEffect, useState, useCallback } from "react";
import { KeyRound, ShieldAlert, Check, Play, Pause, Loader2, AlertCircle, RefreshCw, Activity, CheckCircle, Clock } from "lucide-react";
import { apiFetch } from "@/utils/apiFetch";
import { API_BASE } from "@/lib/api";

type FeatureMap = Record<string, boolean>;

type WorkerHealth = {
  last_cycle_at?: string | null;
  last_cycle_status?: string | null;
  last_cycle_duration_seconds?: number | null;
  total_cycles?: number | null;
  total_failed_cycles?: number | null;
  paused?: boolean | null;
  worker_last_cycle_at?: string | null;
  worker_last_cycle_status?: string | null;
  worker_last_cycle_duration_seconds?: number | null;
  worker_total_cycles?: number | null;
  worker_total_failed_cycles?: number | null;
  worker_paused?: boolean | null;
};

export default function FeatureFlagsTab({ sessionTimeout }: { sessionTimeout: () => void }) {
  const [flags, setFlags] = useState<FeatureMap>({});
  const [flagsLoading, setFlagsLoading] = useState(true);
  const [updatingFlag, setUpdatingFlag] = useState<string | null>(null);

  // Worker state
  const [worker, setWorker] = useState<WorkerHealth | null>(null);
  const [workerLoading, setWorkerLoading] = useState(true);
  const [workerToggling, setWorkerToggling] = useState(false);

  const fetchFlags = useCallback(async () => {
    setFlagsLoading(true);
    try {
      const res = await apiFetch(`${API_BASE}/admin/feature-flags`);
      if (res.status === 401) {
        sessionTimeout();
        return;
      }
      if (res.ok) {
        setFlags(await res.json());
      }
    } catch (e) {
      console.error(e);
    } finally {
      setFlagsLoading(false);
    }
  }, [sessionTimeout]);

  const fetchWorkerHealth = useCallback(async () => {
    setWorkerLoading(true);
    try {
      const res = await apiFetch(`${API_BASE}/admin/worker/health`);
      if (res.ok) {
        setWorker(await res.json());
      }
    } catch (e) {
      console.error(e);
    } finally {
      setWorkerLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchFlags();
    fetchWorkerHealth();
  }, [fetchFlags, fetchWorkerHealth]);

  const handleToggleFlag = async (feature: string, currentVal: boolean) => {
    setUpdatingFlag(feature);
    try {
      const res = await apiFetch(`${API_BASE}/admin/feature-flags/${feature}?enabled=${!currentVal}`, {
        method: "PUT",
      });
      if (res.ok) {
        // Toggle local state directly or refresh
        setFlags(prev => ({ ...prev, [feature]: !currentVal }));
      }
    } catch (e) {
      console.error(e);
    } finally {
      setUpdatingFlag(null);
    }
  };

  const handleToggleWorker = async (pause: boolean) => {
    setWorkerToggling(true);
    try {
      const action = pause ? "pause" : "resume";
      const res = await apiFetch(`${API_BASE}/admin/worker/${action}`, {
        method: "POST",
      });
      if (res.ok) {
        fetchWorkerHealth();
      }
    } catch (e) {
      console.error(e);
    } finally {
      setWorkerToggling(false);
    }
  };

  // Helper to resolve nested worker response structures
  const isPaused = worker?.paused ?? worker?.worker_paused ?? false;
  const lastCycleAt = worker?.last_cycle_at ?? worker?.worker_last_cycle_at ?? null;
  const lastStatus = worker?.last_cycle_status ?? worker?.worker_last_cycle_status ?? "N/A";
  const lastDuration = worker?.last_cycle_duration_seconds ?? worker?.worker_last_cycle_duration_seconds ?? null;
  const totalCycles = worker?.total_cycles ?? worker?.worker_total_cycles ?? 0;
  const failedCycles = worker?.total_failed_cycles ?? worker?.worker_total_failed_cycles ?? 0;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
      {/* Feature Flags Override column */}
      <div className="lg:col-span-2 rounded-2xl glass p-6 border border-white/40 dark:border-white/10 space-y-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600">
              <KeyRound className="h-5 w-5 text-white" />
            </div>
            <div>
              <h3 className="text-lg font-bold text-slate-900 dark:text-slate-100">Feature Flags</h3>
              <p className="text-sm text-slate-500 dark:text-slate-400">Override company plan gates and toggles (superadmin control)</p>
            </div>
          </div>
          <button onClick={fetchFlags} className="p-1.5 text-slate-450 hover:text-violet-650 transition-colors">
            <RefreshCw className="h-4 w-4" />
          </button>
        </div>

        {flagsLoading ? (
          <div className="flex justify-center py-8 text-slate-455 text-xs">
            <Loader2 className="h-5 w-5 animate-spin mr-2 text-violet-500" /> Loading features config...
          </div>
        ) : Object.keys(flags).length === 0 ? (
          <p className="text-center text-slate-400 text-sm py-6">No feature flags registered in database.</p>
        ) : (
          <div className="divide-y divide-slate-100 dark:divide-slate-800 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden bg-white/30 dark:bg-slate-900/10">
            {Object.entries(flags).map(([feature, enabled]) => (
              <div key={feature} className="flex items-center justify-between p-4 hover:bg-slate-50/50 dark:hover:bg-slate-850/20">
                <div>
                  <span className="text-xs font-bold font-mono text-slate-700 dark:text-slate-200 uppercase">{feature}</span>
                  <p className="text-[10px] text-slate-400 mt-0.5">
                    {feature === "campaigns" && "Enables multi-step lead outreach and dialing campaign runner"}
                    {feature === "outbound_calls" && "Enables auto-dialer outbound VoIP call dispatch"}
                    {feature === "whatsapp" && "Enables template notifications and messaging via Twilio Sandbox"}
                    {!["campaigns", "outbound_calls", "whatsapp"].includes(feature) && "Standard plan feature gate override"}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <span className={`text-[10px] font-bold uppercase ${enabled ? "text-emerald-600 dark:text-emerald-400" : "text-slate-400"}`}>
                    {enabled ? "enabled" : "disabled"}
                  </span>
                  <button
                    onClick={() => handleToggleFlag(feature, enabled)}
                    disabled={updatingFlag === feature}
                    className={`relative inline-flex h-5 w-10 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
                      enabled ? "bg-violet-600" : "bg-slate-250 dark:bg-slate-700"
                    }`}
                  >
                    <span
                      className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
                        enabled ? "translate-x-5" : "translate-x-0"
                      }`}
                    />
                  </button>
                  {updatingFlag === feature && <Loader2 className="h-3 w-3 animate-spin text-slate-400" />}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Admin Worker Health column */}
      <div className="rounded-2xl glass p-6 border border-white/40 dark:border-white/10 space-y-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-rose-500 to-red-600">
              <Activity className="h-5 w-5 text-white" />
            </div>
            <div>
              <h3 className="text-lg font-bold text-slate-900 dark:text-slate-100">Automation Worker</h3>
              <p className="text-sm text-slate-500 dark:text-slate-400">Background task engine scheduler status</p>
            </div>
          </div>
          <button onClick={fetchWorkerHealth} className="p-1.5 text-slate-450 hover:text-rose-650 transition-colors">
            <RefreshCw className="h-4 w-4" />
          </button>
        </div>

        {workerLoading ? (
          <div className="flex justify-center py-8 text-slate-455 text-xs">
            <Loader2 className="h-5 w-5 animate-spin mr-2 text-rose-500" /> Fetching worker metrics...
          </div>
        ) : (
          <div className="space-y-4">
            <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white/20 dark:bg-slate-900/10 space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-400 font-semibold uppercase">Engine Status</span>
                <span className={`px-2.5 py-0.5 rounded-full text-xs font-bold flex items-center gap-1 ${
                  isPaused 
                    ? "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300"
                    : "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300"
                }`}>
                  {isPaused ? <Pause className="h-3 w-3" /> : <Play className="h-3 w-3" />}
                  {isPaused ? "Paused" : "Running"}
                </span>
              </div>

              <div className="space-y-2 border-t border-slate-150 dark:border-slate-800/80 pt-3 text-xs font-mono">
                <div className="flex justify-between">
                  <span className="text-slate-400">Last run cycle:</span>
                  <span className="text-slate-700 dark:text-slate-200 font-semibold">
                    {lastCycleAt ? new Date(lastCycleAt).toLocaleString() : "Never"}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Cycle Status:</span>
                  <span className={`font-semibold capitalize ${lastStatus === "success" || lastStatus === "ok" ? "text-emerald-600" : "text-rose-600"}`}>{lastStatus}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Cycle duration:</span>
                  <span className="text-slate-700 dark:text-slate-200 font-semibold">{lastDuration ? `${lastDuration.toFixed(2)}s` : "—"}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Completed cycles:</span>
                  <span className="text-slate-700 dark:text-slate-200 font-semibold">{totalCycles}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Failed cycles:</span>
                  <span className="text-rose-650 dark:text-rose-400 font-semibold">{failedCycles}</span>
                </div>
              </div>
            </div>

            <div className="flex gap-3">
              <button
                onClick={() => handleToggleWorker(true)}
                disabled={workerToggling || isPaused}
                className="flex-1 flex items-center justify-center gap-1.5 px-4 py-2.5 rounded-lg border border-amber-200 dark:border-amber-900 bg-amber-50 dark:bg-amber-950/20 text-amber-700 dark:text-amber-300 text-xs font-semibold hover:bg-amber-100 disabled:opacity-50 transition-colors"
              >
                <Pause className="h-3.5 w-3.5" /> Pause Worker
              </button>
              <button
                onClick={() => handleToggleWorker(false)}
                disabled={workerToggling || !isPaused}
                className="flex-1 flex items-center justify-center gap-1.5 px-4 py-2.5 rounded-lg border border-emerald-200 dark:border-emerald-900 bg-emerald-50 dark:bg-emerald-950/20 text-emerald-700 dark:text-emerald-300 text-xs font-semibold hover:bg-emerald-100 disabled:opacity-50 transition-colors"
              >
                <Play className="h-3.5 w-3.5" /> Resume Worker
              </button>
            </div>
            {workerToggling && (
              <p className="text-[10px] text-center text-slate-400 animate-pulse">Sending engine instruction to scheduler...</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
