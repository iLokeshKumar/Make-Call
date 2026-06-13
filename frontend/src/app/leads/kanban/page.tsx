"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { ArrowLeft, Loader2, Phone, RefreshCw } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/context/AuthContext";

import { apiFetch } from "@/utils/apiFetch";
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || (typeof window !== "undefined" ? (window.location.hostname.includes("ngrok-free.dev") ? `${window.location.protocol}//${window.location.host}` : `${window.location.protocol}//127.0.0.1:6060`) : "http://127.0.0.1:6060");

const ISM_STAGES = [
  { key: "new",         label: "New",          cls: "border-slate-300  bg-slate-50   dark:border-slate-700 dark:bg-slate-900/30",  dot: "bg-slate-400" },
  { key: "contacted",   label: "Contacted",    cls: "border-blue-200   bg-blue-50    dark:border-blue-500/20 dark:bg-blue-500/5",  dot: "bg-blue-400" },
  { key: "engaged",     label: "Engaged",      cls: "border-violet-200 bg-violet-50  dark:border-violet-500/20 dark:bg-violet-500/5", dot: "bg-violet-500" },
  { key: "quote_sent",  label: "Quote Sent",   cls: "border-amber-200  bg-amber-50   dark:border-amber-500/20 dark:bg-amber-500/5",  dot: "bg-amber-400" },
  { key: "negotiation", label: "Negotiation",  cls: "border-orange-200 bg-orange-50  dark:border-orange-500/20 dark:bg-orange-500/5", dot: "bg-orange-400" },
  { key: "closed_won",  label: "Closed Won",   cls: "border-emerald-200 bg-emerald-50 dark:border-emerald-500/20 dark:bg-emerald-500/5", dot: "bg-emerald-500" },
  { key: "closed_lost", label: "Closed Lost",  cls: "border-red-200    bg-red-50     dark:border-red-500/20 dark:bg-red-500/5",   dot: "bg-red-400" },
] as const;

type StageKey = typeof ISM_STAGES[number]["key"];

type Lead = {
  id: number;
  name: string;
  normalized_phone: string;
  email?: string | null;
  ism_stage?: string | null;
  lead_score?: number | null;
  qualification_status?: string | null;
  last_outreach_at?: string | null;
};

function ScoreDot({ score }: { score?: number | null }) {
  if (score == null) return null;
  const s = Math.round(score);
  const cls = s >= 70 ? "bg-emerald-400" : s >= 40 ? "bg-amber-400" : "bg-slate-300";
  return (
    <span title={`ICP ${s}`} className={`inline-block h-2 w-2 rounded-full ${cls}`} />
  );
}

export default function KanbanPage() {
  const { user, sessionTimeout } = useAuth();
  const qc = useQueryClient();

  // drag state
  const dragLeadId   = useRef<number | null>(null);
  const dragFromStage = useRef<string | null>(null);
  const [dragOver, setDragOver] = useState<string | null>(null);

  const leadsQuery = useQuery<{ items: Lead[] }>({
    queryKey: ["kanban-leads"],
    enabled: !!user,
    queryFn: async () => {
      const res = await apiFetch(`${API_BASE}/crm/leads?page=1&limit=500`);
      if (res.status === 401) { sessionTimeout(); throw new Error("unauthorized"); }
      if (!res.ok) throw new Error("Failed to load leads");
      return res.json();
    },
  });
  const leads = leadsQuery.data?.items ?? [];
  const loading = leadsQuery.isLoading;

  const moveMutation = useMutation({
    mutationFn: async ({ leadId, stage }: { leadId: number; stage: StageKey }) => {
      const res = await apiFetch(`${API_BASE}/crm/leads/${leadId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ism_stage: stage }),
      });
      if (res.status === 401) { sessionTimeout(); throw new Error("unauthorized"); }
      if (!res.ok) throw new Error("patch failed");
      return res.json();
    },
    onMutate: async ({ leadId, stage }) => {
      await qc.cancelQueries({ queryKey: ["kanban-leads"] });
      const snapshot = qc.getQueryData<{ items: Lead[] }>(["kanban-leads"]);
      qc.setQueryData<{ items: Lead[] } | undefined>(["kanban-leads"], (prev) =>
        prev ? { ...prev, items: prev.items.map((l) => (l.id === leadId ? { ...l, ism_stage: stage } : l)) } : prev,
      );
      return { snapshot };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.snapshot) qc.setQueryData(["kanban-leads"], ctx.snapshot);
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ["kanban-leads"] }),
  });

  const updating = moveMutation.isPending ? moveMutation.variables?.leadId ?? null : null;

  function moveLeadToStage(leadId: number, stage: StageKey) {
    moveMutation.mutate({ leadId, stage });
  }

  function fetchLeads() {
    qc.invalidateQueries({ queryKey: ["kanban-leads"] });
  }

  function onDragStart(leadId: number, stage: string) {
    dragLeadId.current   = leadId;
    dragFromStage.current = stage;
  }

  function onDragOver(e: React.DragEvent, stageKey: string) {
    e.preventDefault();
    setDragOver(stageKey);
  }

  function onDrop(e: React.DragEvent, stageKey: StageKey) {
    e.preventDefault();
    setDragOver(null);
    const id = dragLeadId.current;
    if (id == null || dragFromStage.current === stageKey) return;
    moveLeadToStage(id, stageKey);
    dragLeadId.current   = null;
    dragFromStage.current = null;
  }

  function onDragLeave() {
    setDragOver(null);
  }

  const grouped = ISM_STAGES.reduce<Record<string, Lead[]>>((acc, s) => {
    acc[s.key] = leads.filter((l) => (l.ism_stage || "new") === s.key);
    return acc;
  }, {});

  return (
    <div className="space-y-4 pb-8">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <Link href="/leads" className="inline-flex items-center gap-1.5 text-sm font-semibold text-violet-600 dark:text-violet-300 mb-2">
            <ArrowLeft className="h-4 w-4" /> Back to list
          </Link>
          <h1 className="text-3xl font-bold tracking-tight text-slate-900 dark:text-white">
            Stage Board
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
            Drag leads across columns to update their sales-motion stage.
          </p>
        </div>
        <button
          onClick={fetchLeads}
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-600 hover:border-violet-400 hover:text-violet-700 dark:border-white/10 dark:text-slate-300 transition disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} /> Refresh
        </button>
      </div>

      {loading ? (
        <div className="flex justify-center py-20 text-slate-500">
          <Loader2 className="h-6 w-6 animate-spin" />
        </div>
      ) : (
        /* Board — horizontal scroll on small screens */
        <div className="flex gap-3 overflow-x-auto pb-4 min-h-[70vh]">
          {ISM_STAGES.map((stage) => {
            const col = grouped[stage.key] ?? [];
            const isOver = dragOver === stage.key;

            return (
              <div
                key={stage.key}
                onDragOver={(e) => onDragOver(e, stage.key)}
                onDrop={(e) => onDrop(e, stage.key as StageKey)}
                onDragLeave={onDragLeave}
                className={`flex flex-col rounded-2xl border-2 min-w-[240px] w-60 flex-shrink-0 transition-all duration-150 ${stage.cls} ${
                  isOver
                    ? "scale-[1.02] shadow-lg ring-2 ring-violet-400/50"
                    : "shadow-sm"
                }`}
              >
                {/* Column header */}
                <div className="flex items-center gap-2 px-4 pt-4 pb-3">
                  <span className={`h-2.5 w-2.5 rounded-full ${stage.dot}`} />
                  <span className="font-semibold text-sm text-slate-800 dark:text-slate-100">
                    {stage.label}
                  </span>
                  <span className="ml-auto rounded-full bg-white/70 dark:bg-slate-800/60 px-2 py-0.5 text-xs font-bold text-slate-600 dark:text-slate-300">
                    {col.length}
                  </span>
                </div>

                {/* Cards */}
                <div className="flex flex-col gap-2 px-2 pb-4 flex-1">
                  {col.length === 0 && (
                    <div className="rounded-xl border border-dashed border-slate-300/60 dark:border-white/10 p-4 text-center text-xs text-slate-400 dark:text-slate-500">
                      Drop leads here
                    </div>
                  )}
                  {col.map((lead) => (
                    <div
                      key={lead.id}
                      draggable
                      onDragStart={() => onDragStart(lead.id, stage.key)}
                      className={`rounded-xl border border-slate-200 bg-white p-3 shadow-sm cursor-grab active:cursor-grabbing dark:border-white/10 dark:bg-slate-900/60 transition ${
                        updating === lead.id ? "opacity-50 pointer-events-none" : "hover:shadow-md"
                      }`}
                    >
                      <div className="flex items-center gap-1.5 mb-1">
                        <ScoreDot score={lead.lead_score} />
                        <span className="font-semibold text-sm text-slate-900 dark:text-white truncate">
                          {lead.name}
                        </span>
                        {updating === lead.id && (
                          <Loader2 className="h-3 w-3 animate-spin ml-auto text-violet-500" />
                        )}
                      </div>
                      <div className="flex items-center gap-1 text-xs text-slate-500 dark:text-slate-400">
                        <Phone className="h-3 w-3 flex-shrink-0" />
                        <span className="truncate">{lead.normalized_phone}</span>
                      </div>
                      {lead.qualification_status && lead.qualification_status !== "unqualified" && (
                        <span className="mt-1.5 inline-block rounded-full bg-violet-100 px-2 py-0.5 text-xs font-medium text-violet-700 dark:bg-violet-500/10 dark:text-violet-300">
                          {lead.qualification_status.replace(/_/g, " ")}
                        </span>
                      )}
                      <Link
                        href={`/leads/${lead.id}`}
                        className="mt-2 block text-center text-xs font-semibold text-violet-600 hover:underline dark:text-violet-400"
                        onClick={(e) => e.stopPropagation()}
                      >
                        Open 360 →
                      </Link>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
