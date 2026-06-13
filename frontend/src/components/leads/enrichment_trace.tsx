"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/utils/apiFetch";
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Database,
  Loader2,
  RefreshCw,
  Search,
  ShieldCheck,
  XCircle,
  Zap } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || (typeof window !== "undefined" ? (window.location.hostname.includes("ngrok-free.dev") ? `${window.location.protocol}//${window.location.host}` : `${window.location.protocol}//127.0.0.1:6060`) : "http://127.0.0.1:6060");

type Step = {
  name: string;
  key: string;
  status: "enriched" | "partial" | "empty" | "available" | "not_configured" | "passed" | string;
  configured?: boolean;
  populated_fields?: string[];
  missing_fields?: string[];
  email_valid?: boolean;
  phone_valid?: boolean;
  description: string;
};

type Trace = {
  lead_id: number;
  enrichment_status: string | null;
  last_enriched_at: string | null;
  steps: Step[];
};

type Props = {
  leadId: number;
  onSessionTimeout?: () => void;
};

const STEP_ICONS: Record<string, React.ElementType> = {
  db: Database,
  apollo: Search,
  lusha: Zap,
  validation: ShieldCheck };

function statusColor(status: string) {
  switch (status) {
    case "enriched":
    case "passed":
      return "text-emerald-600 dark:text-emerald-400 bg-emerald-100 dark:bg-emerald-500/10 border-emerald-200 dark:border-emerald-500/30";
    case "partial":
    case "available":
      return "text-amber-600 dark:text-amber-400 bg-amber-100 dark:bg-amber-500/10 border-amber-200 dark:border-amber-500/30";
    case "empty":
    case "not_configured":
      return "text-slate-500 dark:text-slate-400 bg-slate-100 dark:bg-slate-800/50 border-slate-200 dark:border-white/10";
    default:
      return "text-slate-500 dark:text-slate-400 bg-slate-100 dark:bg-slate-800/50 border-slate-200 dark:border-white/10";
  }
}

function statusIcon(status: string) {
  switch (status) {
    case "enriched":
    case "passed":
      return <CheckCircle2 className="h-4 w-4 text-emerald-500" />;
    case "partial":
    case "available":
      return <CheckCircle2 className="h-4 w-4 text-amber-500" />;
    default:
      return <XCircle className="h-4 w-4 text-slate-400" />;
  }
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    enriched: "Enriched",
    partial: "Partial",
    empty: "Empty",
    available: "Available",
    not_configured: "Not configured",
    passed: "Passed" };
  return map[status] || status;
}

export default function EnrichmentTrace({ leadId, onSessionTimeout }: Props) {
  const [trace, setTrace] = useState<Trace | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);

  const fetchTrace = useCallback(
    async (quiet = false) => {
      if (!quiet) setLoading(true);
      else setRefreshing(true);
      try {
        const res = await apiFetch(`${API_BASE}/crm/leads/${leadId}/enrichment-trace`, {
        });
        if (res.status === 401) { onSessionTimeout?.(); return; }
        if (!res.ok) return;
        setTrace(await res.json());
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [leadId, onSessionTimeout]
  );

  useEffect(() => { fetchTrace(); }, [fetchTrace]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-xs text-slate-400 dark:text-slate-500 py-4">
        <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading enrichment trace...
      </div>
    );
  }

  if (!trace) return null;

  return (
    <div className="rounded-2xl glass border border-white/40 dark:border-white/10 overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 px-5 py-4 border-b border-slate-200 dark:border-white/10">
        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-blue-100 dark:bg-blue-500/10">
          <Database className="h-4 w-4 text-blue-600 dark:text-blue-400" />
        </div>
        <div>
          <h3 className="font-semibold text-slate-900 dark:text-white">Enrichment Pipeline</h3>
          {trace.last_enriched_at && (
            <p className="text-[11px] text-slate-500 dark:text-slate-400">
              Last enriched {new Date(trace.last_enriched_at).toLocaleString()}
            </p>
          )}
        </div>
        <button
          onClick={() => fetchTrace(true)}
          disabled={refreshing}
          className="ml-auto text-slate-400 hover:text-violet-500 dark:hover:text-violet-400 transition"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} />
        </button>
      </div>

      {/* Pipeline steps */}
      <div className="p-4 space-y-2">
        {/* Connector line */}
        <div className="relative">
          {trace.steps.map((step, i) => {
            const Icon = STEP_ICONS[step.key] || Database;
            const isExpanded = expanded === step.key;
            const isLast = i === trace.steps.length - 1;

            return (
              <div key={step.key} className="relative flex gap-3 mb-2">
                {/* Vertical connector */}
                {!isLast && (
                  <div className="absolute left-[17px] top-9 bottom-0 w-0.5 bg-slate-200 dark:bg-white/10 z-0" />
                )}

                {/* Step icon */}
                <div
                  className={`relative z-10 flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full border-2 ${statusColor(step.status)}`}
                >
                  <Icon className="h-4 w-4" />
                </div>

                {/* Step card */}
                <div className="flex-1 min-w-0">
                  <button
                    onClick={() => setExpanded(isExpanded ? null : step.key)}
                    className="w-full text-left rounded-xl border border-slate-200 dark:border-white/10 bg-white/60 dark:bg-slate-900/30 px-3 py-2.5 hover:bg-slate-50 dark:hover:bg-white/5 transition"
                  >
                    <div className="flex items-center gap-2">
                      {statusIcon(step.status)}
                      <span className="font-semibold text-sm text-slate-900 dark:text-white">
                        {step.name}
                      </span>
                      <span
                        className={`ml-auto text-xs font-semibold px-2 py-0.5 rounded-full border ${statusColor(step.status)}`}
                      >
                        {statusLabel(step.status)}
                      </span>
                      {isExpanded ? (
                        <ChevronDown className="h-3.5 w-3.5 text-slate-400 flex-shrink-0" />
                      ) : (
                        <ChevronRight className="h-3.5 w-3.5 text-slate-400 flex-shrink-0" />
                      )}
                    </div>
                    <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
                      {step.description}
                    </p>
                  </button>

                  {/* Expanded details */}
                  {isExpanded && (
                    <div className="mt-1 rounded-xl border border-slate-200 dark:border-white/10 bg-slate-50 dark:bg-slate-900/30 p-3 text-xs space-y-2">
                      {/* DB fields */}
                      {step.populated_fields && step.populated_fields.length > 0 && (
                        <div>
                          <p className="font-semibold text-emerald-700 dark:text-emerald-400 mb-1">
                            Present fields
                          </p>
                          <div className="flex flex-wrap gap-1">
                            {step.populated_fields.map((f) => (
                              <span
                                key={f}
                                className="rounded-full bg-emerald-100 dark:bg-emerald-500/10 px-2 py-0.5 text-emerald-700 dark:text-emerald-400"
                              >
                                {f}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                      {step.missing_fields && step.missing_fields.length > 0 && (
                        <div>
                          <p className="font-semibold text-slate-500 dark:text-slate-400 mb-1">
                            Missing fields
                          </p>
                          <div className="flex flex-wrap gap-1">
                            {step.missing_fields.map((f) => (
                              <span
                                key={f}
                                className="rounded-full bg-slate-200 dark:bg-white/10 px-2 py-0.5 text-slate-600 dark:text-slate-300"
                              >
                                {f}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Apollo/Lusha config status */}
                      {step.configured !== undefined && (
                        <p className={step.configured ? "text-emerald-700 dark:text-emerald-400" : "text-slate-500"}>
                          API key: {step.configured ? "configured" : "not configured — add in Settings → Credentials"}
                        </p>
                      )}

                      {/* Validation */}
                      {step.key === "validation" && (
                        <div className="space-y-1">
                          <div className="flex items-center gap-2">
                            {step.email_valid
                              ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
                              : <XCircle className="h-3.5 w-3.5 text-slate-400" />}
                            <span className={step.email_valid ? "text-emerald-700 dark:text-emerald-400" : "text-slate-500"}>
                              Email format
                            </span>
                          </div>
                          <div className="flex items-center gap-2">
                            {step.phone_valid
                              ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
                              : <XCircle className="h-3.5 w-3.5 text-slate-400" />}
                            <span className={step.phone_valid ? "text-emerald-700 dark:text-emerald-400" : "text-slate-500"}>
                              Phone E.164 format
                            </span>
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
