"use client";

import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, Ban, CheckCircle, Clock, Inbox, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { apiFetch } from "@/utils/apiFetch";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:6060";

type Approval = {
  approval_id: number;
  task_id: number;
  action_type: string;
  action_summary: string | null;
  action_payload: Record<string, unknown> | null;
  status: string;
  expires_at: string | null;
  created_at: string;
  task: { task_type: string | null; assigned_agent: string | null; lead_id: number | null; priority: number | null };
  presentation?: {
    title?: string;
    description?: string;
    preview?: Record<string, unknown> | string | null;
    warnings?: string[];
    raw?: Record<string, unknown>;
  };
};

function renderPreviewValue(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  if (Array.isArray(v)) return v.map(renderPreviewValue).join(", ");
  return JSON.stringify(v);
}

function formatTs(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export default function ApprovalsPage() {
  const { user, sessionTimeout } = useAuth();
  const qc = useQueryClient();
  const [selected, setSelected] = useState<Approval | null>(null);
  const [note, setNote] = useState("");
  const [action, setAction] = useState<"approve" | "reject" | null>(null);

  const query = useQuery<Approval[]>({
    queryKey: ["approvals"],
    enabled: !!user,
    queryFn: async () => {
      const res = await apiFetch(`${API_BASE}/crm/agent-tasks/approvals`);
      if (res.status === 401) { sessionTimeout(); throw new Error("unauthorized"); }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    },
    refetchInterval: 15_000,
  });

  const decide = useMutation({
    mutationFn: async ({ taskId, verdict, note }: { taskId: number; verdict: "approve" | "reject"; note: string }) => {
      const res = await apiFetch(`${API_BASE}/crm/agent-tasks/${taskId}/${verdict}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ note }),
      });
      if (res.status === 401) { sessionTimeout(); throw new Error("unauthorized"); }
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      return res.json();
    },
    onSuccess: (_data, vars) => {
      toast.success(vars.verdict === "approve" ? "Approved — queued for execution" : "Rejected");
      qc.invalidateQueries({ queryKey: ["approvals"] });
      setSelected(null);
      setAction(null);
      setNote("");
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "Decision failed");
    },
  });

  const approvals = query.data ?? [];

  return (
    <div className="space-y-6 pb-8">
      <div className="flex items-start justify-between gap-4">
        <div>
          <Link href="/agent-tasks" className="mb-2 inline-flex items-center gap-1.5 text-sm font-semibold text-violet-600 dark:text-violet-300">
            <ArrowLeft className="h-4 w-4" /> Back to agent tasks
          </Link>
          <h1 className="flex items-center gap-2 text-3xl font-bold tracking-tight text-slate-900 dark:text-white">
            <Inbox className="h-7 w-7 text-violet-500" /> Approvals Inbox
          </h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            Actions queued by agents that need human sign-off before execution.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => qc.invalidateQueries({ queryKey: ["approvals"] })}>
          Refresh
        </Button>
      </div>

      {query.isLoading && (
        <div className="flex justify-center py-20">
          <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
        </div>
      )}

      {query.error && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
          Could not load approvals: {String(query.error)}
        </div>
      )}

      {!query.isLoading && approvals.length === 0 && (
        <div className="rounded-2xl border border-dashed border-slate-300 p-12 text-center dark:border-white/10">
          <CheckCircle className="mx-auto h-10 w-10 text-emerald-400" />
          <p className="mt-3 text-sm font-medium text-slate-700 dark:text-slate-200">Inbox zero.</p>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">No agent actions waiting on approval.</p>
        </div>
      )}

      <div className="space-y-3">
        {approvals.map((a) => {
          const p = a.presentation || {};
          const title = p.title || a.action_summary || a.action_type;
          return (
            <div
              key={a.approval_id}
              className="rounded-2xl border border-slate-200 bg-white/70 p-4 shadow-sm dark:border-white/10 dark:bg-slate-900/40"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="truncate text-base font-semibold text-slate-900 dark:text-white">{title}</h2>
                    <Badge variant="secondary">{a.action_type}</Badge>
                    {a.task.assigned_agent && <Badge variant="outline">agent: {a.task.assigned_agent}</Badge>}
                    {a.task.lead_id && (
                      <Link
                        href={`/leads/${a.task.lead_id}`}
                        className="text-xs font-semibold text-violet-600 hover:underline dark:text-violet-300"
                      >
                        Lead #{a.task.lead_id} →
                      </Link>
                    )}
                  </div>
                  {p.description && <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">{p.description}</p>}
                  {typeof p.preview === "string" && p.preview && (
                    <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-50 p-3 text-xs text-slate-700 dark:bg-slate-800/60 dark:text-slate-300">
                      {p.preview}
                    </pre>
                  )}
                  {p.preview && typeof p.preview === "object" && (
                    <dl className="mt-2 grid grid-cols-1 gap-2 text-xs sm:grid-cols-2">
                      {Object.entries(p.preview).map(([key, value]) => {
                        if (value === null || value === undefined || value === "") return null;
                        const isLongText = typeof value === "string" && (value.length > 120 || value.includes("\n"));
                        return (
                          <div key={key} className={isLongText ? "sm:col-span-2" : undefined}>
                            <dt className="font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">{key.replace(/_/g, " ")}</dt>
                            <dd className={`text-slate-800 dark:text-slate-200 ${isLongText ? "whitespace-pre-wrap mt-0.5 rounded-md bg-slate-50 p-2 dark:bg-slate-800/60" : ""}`}>
                              {renderPreviewValue(value)}
                            </dd>
                          </div>
                        );
                      })}
                    </dl>
                  )}
                  {p.warnings && p.warnings.length > 0 && (
                    <div className="mt-3 space-y-1">
                      {p.warnings.map((w, i) => (
                        <p key={i} className="flex items-center gap-1 text-xs text-amber-700 dark:text-amber-300">
                          <AlertTriangle className="h-3 w-3" /> {w}
                        </p>
                      ))}
                    </div>
                  )}
                  <div className="mt-3 flex flex-wrap items-center gap-3 text-[11px] text-slate-500 dark:text-slate-400">
                    <span className="inline-flex items-center gap-1"><Clock className="h-3 w-3" /> Queued {formatTs(a.created_at)}</span>
                    {a.expires_at && <span>Expires {formatTs(a.expires_at)}</span>}
                  </div>
                </div>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    onClick={() => { setSelected(a); setAction("approve"); setNote(""); }}
                    className="bg-emerald-600 hover:bg-emerald-700"
                  >
                    <CheckCircle className="mr-1 h-3.5 w-3.5" /> Approve
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => { setSelected(a); setAction("reject"); setNote(""); }}
                    className="border-red-200 text-red-700 hover:bg-red-50"
                  >
                    <Ban className="mr-1 h-3.5 w-3.5" /> Reject
                  </Button>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <Dialog open={!!action && !!selected} onOpenChange={(open) => { if (!open) { setAction(null); setSelected(null); } }}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{action === "approve" ? "Approve action" : "Reject action"}</DialogTitle>
            <DialogDescription>
              {selected?.presentation?.title || selected?.action_summary || selected?.action_type}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="reviewer-note">Note {action === "reject" && <span className="text-red-500">(required)</span>}</Label>
            <Input
              id="reviewer-note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder={action === "reject" ? "Why rejecting?" : "Optional note"}
            />
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => { setAction(null); setSelected(null); }}>
              Cancel
            </Button>
            <Button
              disabled={action === "reject" && !note.trim()}
              onClick={() => {
                if (!selected || !action) return;
                decide.mutate({ taskId: selected.task_id, verdict: action, note: note.trim() });
              }}
              className={action === "approve" ? "bg-emerald-600 hover:bg-emerald-700" : "bg-red-600 hover:bg-red-700"}
            >
              {decide.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              {action === "approve" ? "Approve" : "Reject"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
