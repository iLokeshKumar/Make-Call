"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Bot, CheckCircle, XCircle, Clock, AlertCircle, Loader2,
  ChevronDown, ChevronUp, RefreshCw, Plus, Ban, ExternalLink,
} from "lucide-react";
import Link from "next/link";
import { useAuth } from "@/context/AuthContext";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:6060";

// Types

type AgentTask = {
  id: number;
  task_type: string;
  assigned_agent: string;
  status: string;
  priority: number;
  lead_id: number | null;
  requires_approval: boolean;
  attempts: number;
  max_attempts: number;
  created_at: string;
  completed_at: string | null;
  output_json: Record<string, unknown> | null;
  error_json: Record<string, unknown> | null;
};

type Approval = {
  approval_id: number;
  task_id: number;
  action_type: string;
  action_summary: string;
  action_payload: Record<string, unknown>;
  status: string;
  expires_at: string | null;
  created_at: string;
  task: {
    task_type: string;
    assigned_agent: string;
    lead_id: number | null;
    priority: number;
  };
};

// Helpers

const STATUS_BADGE: Record<string, string> = {
  pending:            "bg-amber-500/15 text-amber-400 border border-amber-500/25",
  running:            "bg-blue-500/15 text-blue-400 border border-blue-500/25",
  awaiting_approval:  "bg-violet-500/15 text-violet-400 border border-violet-500/25",
  approved:           "bg-sky-500/15 text-sky-400 border border-sky-500/25",
  done:               "bg-emerald-500/15 text-emerald-400 border border-emerald-500/25",
  failed:             "bg-red-500/15 text-red-400 border border-red-500/25",
  rejected:           "bg-slate-500/15 text-slate-400 border border-slate-500/25",
};

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${STATUS_BADGE[status] ?? "bg-slate-500/15 text-slate-400"}`}>
      {status.replace("_", " ")}
    </span>
  );
}

function fmtDate(iso: string) {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });
}

function expiresIn(iso: string | null) {
  if (!iso) return null;
  const diff = new Date(iso).getTime() - Date.now();
  if (diff <= 0) return "Expired";
  const h = Math.floor(diff / 3600000);
  const m = Math.floor((diff % 3600000) / 60000);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

// Task Queue Tab

const STATUS_FILTERS = ["all", "pending", "running", "awaiting_approval", "done", "failed", "rejected"];

function TaskQueue({ token }: { token: string }) {
  const [tasks, setTasks] = useState<AgentTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState("all");
  const [cancelling, setCancelling] = useState<number | null>(null);

  const fetchTasks = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: "100" });
      if (statusFilter !== "all") params.set("status", statusFilter);
      const res = await fetch(`${API_BASE}/crm/agent-tasks?${params}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) setTasks(await res.json());
    } finally {
      setLoading(false);
    }
  }, [token, statusFilter]);

  useEffect(() => { fetchTasks(); }, [fetchTasks]);

  const cancelTask = async (taskId: number) => {
    setCancelling(taskId);
    try {
      await fetch(`${API_BASE}/crm/agent-tasks/${taskId}/cancel`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      fetchTasks();
    } finally {
      setCancelling(null);
    }
  };

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex items-center gap-2 flex-wrap">
        {STATUS_FILTERS.map(s => (
          <button
            key={s}
            onClick={() => setStatusFilter(s)}
            className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
              statusFilter === s
                ? "bg-indigo-600 text-white border-indigo-500"
                : "bg-white/5 text-slate-400 border-white/10 hover:border-white/20"
            }`}
          >
            {s === "all" ? "All" : s.replace("_", " ")}
          </button>
        ))}
        <button onClick={fetchTasks} className="ml-auto p-1.5 rounded hover:bg-white/5 text-slate-400 hover:text-slate-200 transition-colors">
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {/* Table */}
      {loading ? (
        <div className="flex justify-center py-12"><Loader2 className="w-6 h-6 animate-spin text-slate-500" /></div>
      ) : tasks.length === 0 ? (
        <div className="text-center py-16 text-slate-500">
          <Bot className="w-10 h-10 mx-auto mb-3 opacity-30" />
          <p>No tasks found</p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-white/8">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/8 bg-white/3">
                <th className="text-left px-4 py-3 text-slate-400 font-medium">ID</th>
                <th className="text-left px-4 py-3 text-slate-400 font-medium">Type</th>
                <th className="text-left px-4 py-3 text-slate-400 font-medium">Agent</th>
                <th className="text-left px-4 py-3 text-slate-400 font-medium">Status</th>
                <th className="text-left px-4 py-3 text-slate-400 font-medium">Lead</th>
                <th className="text-left px-4 py-3 text-slate-400 font-medium">Attempts</th>
                <th className="text-left px-4 py-3 text-slate-400 font-medium">Created</th>
                <th className="text-left px-4 py-3 text-slate-400 font-medium"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {tasks.map(task => (
                <tr key={task.id} className="hover:bg-white/3 transition-colors">
                  <td className="px-4 py-3 text-slate-500 font-mono text-xs">#{task.id}</td>
                  <td className="px-4 py-3 text-slate-200 font-medium">{task.task_type}</td>
                  <td className="px-4 py-3 text-slate-400">{task.assigned_agent}</td>
                  <td className="px-4 py-3"><StatusBadge status={task.status} /></td>
                  <td className="px-4 py-3">
                    {task.lead_id ? (
                      <Link href={`/leads/${task.lead_id}`} className="text-indigo-400 hover:text-indigo-300 flex items-center gap-1">
                        #{task.lead_id} <ExternalLink className="w-3 h-3" />
                      </Link>
                    ) : <span className="text-slate-600">—</span>}
                  </td>
                  <td className="px-4 py-3 text-slate-400">{task.attempts}/{task.max_attempts}</td>
                  <td className="px-4 py-3 text-slate-500 text-xs">{fmtDate(task.created_at)}</td>
                  <td className="px-4 py-3">
                    {(task.status === "pending" || task.status === "awaiting_approval") && (
                      <button
                        onClick={() => cancelTask(task.id)}
                        disabled={cancelling === task.id}
                        className="p-1.5 rounded hover:bg-red-500/15 text-slate-500 hover:text-red-400 transition-colors"
                        title="Cancel task"
                      >
                        {cancelling === task.id ? <Loader2 className="w-4 h-4 animate-spin" /> : <Ban className="w-4 h-4" />}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// Approval Card

function ApprovalCard({ appr, token, onRefresh }: { appr: Approval; token: string; onRefresh: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const [note, setNote] = useState("");
  const [loading, setLoading] = useState<"approve" | "reject" | null>(null);
  const [done, setDone] = useState<"approved" | "rejected" | null>(null);

  const act = async (action: "approve" | "reject") => {
    if (action === "reject" && !note.trim()) return;
    setLoading(action);
    try {
      const body = action === "approve" ? { note } : { note };
      await fetch(`${API_BASE}/crm/agent-tasks/${appr.task_id}/${action}`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      setDone(action === "approve" ? "approved" : "rejected");
      setTimeout(onRefresh, 800);
    } finally {
      setLoading(null);
    }
  };

  const exp = expiresIn(appr.expires_at);

  if (done) {
    return (
      <div className={`rounded-lg border p-4 flex items-center gap-3 ${done === "approved" ? "border-emerald-500/30 bg-emerald-500/5" : "border-red-500/30 bg-red-500/5"}`}>
        {done === "approved"
          ? <CheckCircle className="w-5 h-5 text-emerald-400 shrink-0" />
          : <XCircle className="w-5 h-5 text-red-400 shrink-0" />}
        <span className="text-slate-300 text-sm">{appr.action_summary} — {done}</span>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-white/10 bg-white/3 overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="px-2 py-0.5 rounded text-xs font-medium bg-violet-500/15 text-violet-400 border border-violet-500/25">
              {appr.action_type}
            </span>
            {exp && (
              <span className={`flex items-center gap-1 text-xs ${exp === "Expired" ? "text-red-400" : "text-amber-400"}`}>
                <Clock className="w-3 h-3" /> {exp}
              </span>
            )}
          </div>
          <p className="text-slate-200 text-sm mt-1 font-medium">{appr.action_summary}</p>
          <p className="text-slate-500 text-xs mt-0.5">
            Agent: {appr.task.assigned_agent} · Task #{appr.task_id}
            {appr.task.lead_id && (
              <> · <Link href={`/leads/${appr.task.lead_id}`} className="text-indigo-400 hover:underline">Lead #{appr.task.lead_id}</Link></>
            )}
          </p>
        </div>
        <button
          onClick={() => setExpanded(e => !e)}
          className="p-1.5 text-slate-400 hover:text-slate-200 transition-colors"
        >
          {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </button>
      </div>

      {/* Expanded payload + actions */}
      {expanded && (
        <div className="border-t border-white/8 px-4 py-3 space-y-3">
          {/* Payload preview */}
          <div>
            <p className="text-xs text-slate-500 mb-1 font-medium uppercase tracking-wide">Action payload</p>
            <pre className="text-xs text-slate-300 bg-black/30 rounded p-3 overflow-x-auto max-h-40">
              {JSON.stringify(appr.action_payload, null, 2)}
            </pre>
          </div>

          {/* Note */}
          <div>
            <label className="text-xs text-slate-500 mb-1 block font-medium">
              Note <span className="text-slate-600">(required for rejection)</span>
            </label>
            <textarea
              value={note}
              onChange={e => setNote(e.target.value)}
              rows={2}
              placeholder="Optional note for the agent log…"
              className="w-full bg-black/30 border border-white/10 rounded px-3 py-2 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-indigo-500 resize-none"
            />
          </div>

          {/* Buttons */}
          <div className="flex gap-2 justify-end">
            <button
              onClick={() => act("reject")}
              disabled={!!loading || !note.trim()}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded text-sm bg-red-500/10 text-red-400 border border-red-500/25 hover:bg-red-500/20 disabled:opacity-40 transition-colors"
            >
              {loading === "reject" ? <Loader2 className="w-4 h-4 animate-spin" /> : <XCircle className="w-4 h-4" />}
              Reject
            </button>
            <button
              onClick={() => act("approve")}
              disabled={!!loading}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded text-sm bg-emerald-500/10 text-emerald-400 border border-emerald-500/25 hover:bg-emerald-500/20 disabled:opacity-40 transition-colors"
            >
              {loading === "approve" ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle className="w-4 h-4" />}
              Approve
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// Review Queue Tab

function ReviewQueue({ token }: { token: string }) {
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchApprovals = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/crm/agent-tasks/approvals`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) setApprovals(await res.json());
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => { fetchApprovals(); }, [fetchApprovals]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-400">
          {approvals.length === 0 ? "No actions awaiting review" : `${approvals.length} action${approvals.length === 1 ? "" : "s"} awaiting review`}
        </p>
        <button onClick={fetchApprovals} className="p-1.5 rounded hover:bg-white/5 text-slate-400 hover:text-slate-200 transition-colors">
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {loading ? (
        <div className="flex justify-center py-12"><Loader2 className="w-6 h-6 animate-spin text-slate-500" /></div>
      ) : approvals.length === 0 ? (
        <div className="text-center py-16 text-slate-500">
          <CheckCircle className="w-10 h-10 mx-auto mb-3 opacity-30" />
          <p>All clear — no pending approvals</p>
        </div>
      ) : (
        <div className="space-y-3">
          {approvals.map(appr => (
            <ApprovalCard key={appr.approval_id} appr={appr} token={token} onRefresh={fetchApprovals} />
          ))}
        </div>
      )}
    </div>
  );
}

// Page

export default function AgentTasksPage() {
  const { token } = useAuth();
  const [tab, setTab] = useState<"queue" | "review">("queue");

  if (!token) return (
    <div className="flex items-center justify-center h-64 text-slate-500">
      <Loader2 className="w-6 h-6 animate-spin" />
    </div>
  );

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="p-2.5 rounded-lg bg-indigo-500/10 border border-indigo-500/20">
          <Bot className="w-6 h-6 text-indigo-400" />
        </div>
        <div>
          <h1 className="text-xl font-semibold text-slate-100">Agent Tasks</h1>
          <p className="text-sm text-slate-400">Orchestrator work queue and human approval gate</p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-white/5 border border-white/8 rounded-lg p-1 w-fit">
        {(["queue", "review"] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 rounded text-sm font-medium transition-colors ${
              tab === t
                ? "bg-indigo-600 text-white shadow-sm"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            {t === "queue" ? "Task Queue" : "Review Queue"}
          </button>
        ))}
      </div>

      {/* Content */}
      {tab === "queue"
        ? <TaskQueue token={token} />
        : <ReviewQueue token={token} />}
    </div>
  );
}
