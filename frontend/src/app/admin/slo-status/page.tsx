"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Activity, AlertTriangle, CheckCircle2, Loader2, Pause } from "lucide-react";

import { apiFetch } from "@/utils/apiFetch";
import { useAuth } from "@/context/AuthContext";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { API_BASE } from "@/lib/api";



type SLOStatus = "ok" | "at_risk" | "breach" | "insufficient_data";
type SLO = {
  id: string;
  target: number;
  actual: number | null;
  status: SLOStatus;
  window: string;
  samples: number;
  unit: "ms" | "ratio";
  direction: "lower_is_better" | "higher_is_better";
};

type Payload = { slos: SLO[]; generated_at: string };

const SLO_LABEL: Record<string, string> = {
  api_availability: "API Availability",
  login_dashboard_p95_ms: "Login → Dashboard p95",
  voice_p95_ms: "Voice Turn-Taking p95",
  agent_task_dead_letter_rate: "Agent Task Dead-Letter Rate",
};

function formatValue(slo: SLO, value: number | null): string {
  if (value === null || value === undefined) return "—";
  if (slo.unit === "ratio") return `${(value * 100).toFixed(2)}%`;
  return `${Math.round(value)}ms`;
}

function statusVariant(s: SLOStatus): "default" | "secondary" | "destructive" | "outline" {
  if (s === "ok") return "default";
  if (s === "at_risk") return "secondary";
  if (s === "breach") return "destructive";
  return "outline";
}

function statusIcon(s: SLOStatus) {
  if (s === "ok") return <CheckCircle2 className="h-5 w-5 text-emerald-500" />;
  if (s === "at_risk") return <AlertTriangle className="h-5 w-5 text-amber-500" />;
  if (s === "breach") return <AlertTriangle className="h-5 w-5 text-red-500" />;
  return <Pause className="h-5 w-5 text-slate-400" />;
}

export default function SloStatusPage() {
  const { user, sessionTimeout } = useAuth();

  const query = useQuery<Payload>({
    queryKey: ["slo-status"],
    enabled: !!user,
    refetchInterval: 60_000,
    queryFn: async () => {
      const res = await apiFetch(`${API_BASE}/admin/slo-status`);
      if (res.status === 401) { sessionTimeout(); throw new Error("unauthorized"); }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    },
  });

  const slos = query.data?.slos ?? [];

  return (
    <div className="space-y-6 pb-8">
      <div className="flex items-start justify-between gap-4">
        <div>
          <Link href="/admin" className="mb-2 inline-flex items-center gap-1.5 text-sm font-semibold text-violet-600 dark:text-violet-300">
            <ArrowLeft className="h-4 w-4" /> Back to admin
          </Link>
          <h1 className="flex items-center gap-2 text-3xl font-bold tracking-tight text-slate-900 dark:text-white">
            <Activity className="h-7 w-7 text-violet-500" /> Status
          </h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            Service-level targets for API availability, voice latency, dashboard load, and agent-task health.
            Auto-refreshes every 60s.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => query.refetch()}>Refresh</Button>
      </div>

      {query.isLoading && (
        <div className="flex justify-center py-20"><Loader2 className="h-6 w-6 animate-spin text-slate-400" /></div>
      )}

      {query.error && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
          Could not load SLO status: {String(query.error)}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {slos.map((slo) => (
          <Card key={slo.id} className="border-slate-200 dark:border-white/10">
            <CardHeader>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <CardTitle className="text-base text-slate-900 dark:text-white">
                    {SLO_LABEL[slo.id] ?? slo.id}
                  </CardTitle>
                  <p className="mt-1 text-[11px] uppercase tracking-widest text-slate-500 dark:text-slate-400">
                    Window: {slo.window} · Samples: {slo.samples}
                  </p>
                </div>
                <Badge variant={statusVariant(slo.status)}>{slo.status.replace(/_/g, " ")}</Badge>
              </div>
            </CardHeader>
            <CardContent className="space-y-2">
              <div className="flex items-center gap-3">
                {statusIcon(slo.status)}
                <div className="flex-1 min-w-0">
                  <p className="text-xs uppercase tracking-widest text-slate-500 dark:text-slate-400">Actual</p>
                  <p className="text-2xl font-bold text-slate-900 dark:text-white">{formatValue(slo, slo.actual)}</p>
                </div>
                <div className="text-right">
                  <p className="text-xs uppercase tracking-widest text-slate-500 dark:text-slate-400">Target</p>
                  <p className="text-base font-medium text-slate-700 dark:text-slate-300">
                    {slo.direction === "lower_is_better" ? "≤ " : "≥ "}{formatValue(slo, slo.target)}
                  </p>
                </div>
              </div>
              {slo.status === "insufficient_data" && (
                <p className="text-[11px] italic text-slate-500 dark:text-slate-400">
                  Need ≥ 10 samples in the window to evaluate. Keep using the system.
                </p>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      {query.data && (
        <p className="text-center text-[11px] text-slate-400">
          Generated {new Date(query.data.generated_at).toLocaleString()}
        </p>
      )}
    </div>
  );
}