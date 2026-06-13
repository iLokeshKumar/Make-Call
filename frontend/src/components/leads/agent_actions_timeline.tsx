"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, Ban, Bot, UserRoundCog } from "lucide-react";

import { apiFetch } from "@/utils/apiFetch";
import { formatInteractionSubtitle } from "@/utils/interaction_format";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || (typeof window !== "undefined" ? (window.location.hostname.includes("ngrok-free.dev") ? `${window.location.protocol}//${window.location.host}` : `${window.location.protocol}//127.0.0.1:6060`) : "http://127.0.0.1:6060");

type Item =
  | {
      kind: "agent_task";
      id: number;
      timestamp: string | null;
      agent: string;
      task_type: string;
      status: string;
      requires_approval: boolean;
      input?: Record<string, unknown> | null;
      output?: Record<string, unknown> | null;
      error?: Record<string, unknown> | null;
      undoable: boolean;
      takeoverable: boolean;
    }
  | {
      kind: "engagement_event";
      id: number;
      timestamp: string | null;
      event_type: string;
      channel: string | null;
      payload?: Record<string, unknown> | null;
    }
  | {
      kind: "interaction";
      id: number;
      timestamp: string | null;
      type: string | null;
      channel: string | null;
      direction: string | null;
      status: string | null;
      content: string | null;
    };

function formatTs(value: string | null) {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function statusTone(status?: string | null): string {
  switch ((status || "").toLowerCase()) {
    case "done":
    case "completed":
    case "approved":
      return "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-200";
    case "failed":
    case "rejected":
    case "needs_human":
      return "bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-200";
    case "running":
    case "awaiting_approval":
    case "pending":
      return "bg-blue-100 text-blue-700 dark:bg-blue-500/10 dark:text-blue-200";
    default:
      return "bg-slate-100 text-slate-600 dark:bg-white/5 dark:text-slate-300";
  }
}

export default function AgentActionsTimeline({
  leadId,
  onSessionTimeout,
}: {
  leadId: number;
  onSessionTimeout: () => void;
}) {
  const qc = useQueryClient();

  const query = useQuery<{ lead_id: number; items: Item[] }>({
    queryKey: ["agent-actions", leadId],
    queryFn: async () => {
      const res = await apiFetch(`${API_BASE}/crm/leads/${leadId}/agent-actions`);
      if (res.status === 401) { onSessionTimeout(); throw new Error("unauthorized"); }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    },
  });

  const undo = useMutation({
    mutationFn: async (taskId: number) => {
      const res = await apiFetch(`${API_BASE}/crm/agent-tasks/${taskId}/undo`, { method: "POST" });
      if (!res.ok) throw new Error(await res.text());
      return res.json();
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["agent-actions", leadId] }),
  });

  const takeover = useMutation({
    mutationFn: async (taskId: number) => {
      const res = await apiFetch(`${API_BASE}/crm/agent-tasks/${taskId}/takeover`, { method: "POST" });
      if (!res.ok) throw new Error(await res.text());
      return res.json();
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["agent-actions", leadId] }),
  });

  if (query.isLoading) return <p className="text-sm text-slate-500">Loading agent actions...</p>;
  if (query.error) return <p className="text-sm text-amber-600">Could not load agent actions.</p>;

  const items = query.data?.items ?? [];
  if (items.length === 0) {
    return <p className="text-sm text-slate-500">No agent actions yet for this lead.</p>;
  }

  return (
    <div className="space-y-3">
      {items.map((item) => {
        const ts = formatTs(item.timestamp);
        if (item.kind === "agent_task") {
          return (
            <div key={`task-${item.id}`} className="flex gap-3 rounded-xl border border-violet-200/40 bg-violet-50/30 p-3 dark:border-violet-500/20 dark:bg-violet-500/5">
              <Bot className="h-4 w-4 flex-shrink-0 text-violet-600 dark:text-violet-300" />
              <div className="flex-1 min-w-0">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm font-semibold text-slate-900 dark:text-white">
                    {item.agent} · {item.task_type}
                  </p>
                  <div className="flex items-center gap-1">
                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${statusTone(item.status)}`}>{item.status}</span>
                    <span className="text-[11px] text-slate-400">{ts}</span>
                  </div>
                </div>
                {item.error && item.error.undo_reason ? (
                  <p className="mt-1 text-[11px] text-slate-500">Undone by operator</p>
                ) : null}
                <div className="mt-2 flex gap-1">
                  {item.undoable && (
                    <button
                      type="button"
                      onClick={() => undo.mutate(item.id)}
                      disabled={undo.isPending}
                      className="inline-flex items-center gap-1 rounded-lg border border-red-200 px-2 py-0.5 text-[11px] font-semibold text-red-600 hover:bg-red-50 disabled:opacity-50 dark:border-red-500/30 dark:text-red-300"
                    >
                      <Ban className="h-3 w-3" /> Undo
                    </button>
                  )}
                  {item.takeoverable && (
                    <button
                      type="button"
                      onClick={() => takeover.mutate(item.id)}
                      disabled={takeover.isPending}
                      className="inline-flex items-center gap-1 rounded-lg border border-amber-200 px-2 py-0.5 text-[11px] font-semibold text-amber-700 hover:bg-amber-50 disabled:opacity-50 dark:border-amber-500/30 dark:text-amber-300"
                    >
                      <UserRoundCog className="h-3 w-3" /> Take over
                    </button>
                  )}
                </div>
              </div>
            </div>
          );
        }
        if (item.kind === "engagement_event") {
          return (
            <div key={`event-${item.id}`} className="flex gap-3 rounded-xl border border-blue-200/40 bg-blue-50/30 p-3 dark:border-blue-500/20 dark:bg-blue-500/5">
              <Activity className="h-4 w-4 flex-shrink-0 text-blue-600 dark:text-blue-300" />
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-sm font-semibold text-slate-900 dark:text-white">{item.event_type}</p>
                  <span className="text-[11px] text-slate-400">{ts}</span>
                </div>
                {item.channel && <p className="text-[11px] text-slate-500">via {item.channel}</p>}
              </div>
            </div>
          );
        }
        // interaction
        const subtitle = formatInteractionSubtitle(item.type, item.content);
        return (
          <div key={`intr-${item.id}`} className="flex gap-3 rounded-xl border border-slate-200 bg-white/40 p-3 dark:border-white/10 dark:bg-slate-900/30">
            <Activity className="h-4 w-4 flex-shrink-0 text-slate-400" />
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-medium text-slate-900 dark:text-white">
                  {item.type} {item.status}
                </p>
                <span className="text-[11px] text-slate-400">{ts}</span>
              </div>
              {subtitle && <p className="mt-1 whitespace-pre-line text-xs text-slate-600 dark:text-slate-300 line-clamp-3">{subtitle}</p>}
            </div>
          </div>
        );
      })}
    </div>
  );
}
