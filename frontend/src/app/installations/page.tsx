"use client";

import React, { useCallback, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import UserChip from "@/components/UserChip";
import {
  AlertCircle,
  CheckCircle2,
  ClipboardCheck,
  Loader2,
  Plus,
  Wrench,
  X,
  XCircle,
} from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { apiFetch } from "@/utils/apiFetch";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  (typeof window !== "undefined"
    ? window.location.hostname.includes("ngrok-free.dev")
      ? `${window.location.protocol}//${window.location.host}`
      : `${window.location.protocol}//127.0.0.1:6060`
    : "http://127.0.0.1:6060");

type Job = {
  id: number;
  job_number: string;
  order_id: number;
  lead_id: number;
  ticket_id?: number;
  assigned_user_id?: number;
  status: string;
  scheduled_at?: string;
  started_at?: string;
  completed_at?: string;
  installation_address?: string;
  prerequisites_met: boolean;
  completion_notes?: string;
  csat_score?: number;
  created_at?: string;
};

type Lead = { id: number; name: string };

type PrereqResult = {
  met: string[];
  unmet: string[];
  all_met: boolean;
};

const STATUS_COLORS: Record<string, string> = {
  scheduled: "bg-blue-100 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300",
  prerequisite_check: "bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300",
  assigned: "bg-violet-100 text-violet-700 dark:bg-violet-500/10 dark:text-violet-300",
  in_progress: "bg-indigo-100 text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300",
  completed: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300",
  failed: "bg-red-100 text-red-700 dark:bg-red-500/10 dark:text-red-300",
};

const STATUS_TABS = [
  "All",
  "Scheduled",
  "Prerequisite Check",
  "Assigned",
  "In Progress",
  "Completed",
  "Failed",
];

const TAB_TO_STATUS: Record<string, string> = {
  Scheduled: "scheduled",
  "Prerequisite Check": "prerequisite_check",
  Assigned: "assigned",
  "In Progress": "in_progress",
  Completed: "completed",
  Failed: "failed",
};

const ALL_STATUSES = ["scheduled", "prerequisite_check", "assigned", "in_progress", "completed", "failed"];

function fmtDate(v?: string | null) {
  if (!v) return "—";
  return new Date(v).toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function fmtDateTime(v?: string | null) {
  if (!v) return "—";
  return new Date(v).toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const inputClass =
  "w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40 dark:text-white";
const labelClass = "block text-xs font-semibold text-slate-500 dark:text-slate-400 mb-1";

export default function InstallationsPage() {
  const { user, sessionTimeout } = useAuth();
  const qc = useQueryClient();

  const [toast, setToast] = useState<string | null>(null);
  const [toastError, setToastError] = useState(false);
  const [activeTab, setActiveTab] = useState("All");
  const [search, setSearch] = useState("");

  // Create panel
  const [creating, setCreating] = useState(false);
  const [createSaving, setCreateSaving] = useState(false);
  const [createOrderId, setCreateOrderId] = useState("");
  const [createTicketId, setCreateTicketId] = useState("");
  const [createScheduledAt, setCreateScheduledAt] = useState("");
  const [createAddress, setCreateAddress] = useState("");
  const [createLeadSearch, setCreateLeadSearch] = useState("");
  const [createLeadId, setCreateLeadId] = useState<number | null>(null);

  // Assign modal
  const [assignJobId, setAssignJobId] = useState<number | null>(null);
  const [assignUserId, setAssignUserId] = useState("");
  const [assignSaving, setAssignSaving] = useState(false);

  // Prerequisites modal
  const [prereqJobId, setPrereqJobId] = useState<number | null>(null);
  const [prereqResult, setPrereqResult] = useState<PrereqResult | null>(null);
  const [prereqLoading, setPrereqLoading] = useState(false);

  // Complete modal
  const [completeJob, setCompleteJob] = useState<Job | null>(null);
  const [completeNotes, setCompleteNotes] = useState("");
  const [completeCsat, setCompleteCsat] = useState("");
  const [completeSaving, setCompleteSaving] = useState(false);

  // Status loading
  const [statusLoading, setStatusLoading] = useState<Record<number, boolean>>({});

  function showToast(msg: string, error = false) {
    setToast(msg);
    setToastError(error);
    setTimeout(() => setToast(null), 3500);
  }

  const jobsQuery = useQuery<Job[]>({
    queryKey: ["installations"],
    enabled: !!user,
    refetchInterval: 30_000,
    queryFn: async () => {
      const res = await apiFetch(`${API_BASE}/crm/installations`);
      if (res.status === 401) { sessionTimeout(); throw new Error("unauthorized"); }
      if (!res.ok) throw new Error("Failed to load installation jobs");
      const data = await res.json();
      return Array.isArray(data) ? data : data.items ?? [];
    },
  });

  const leadsQuery = useQuery<Lead[]>({
    queryKey: ["installations-leads"],
    enabled: !!user,
    staleTime: 5 * 60_000,
    queryFn: async () => {
      const res = await apiFetch(`${API_BASE}/crm/leads?page=1&limit=200`);
      if (!res.ok) return [];
      const d = await res.json();
      return d.items ?? d ?? [];
    },
  });

  const jobs: Job[] = jobsQuery.data ?? [];
  const leads: Lead[] = leadsQuery.data ?? [];
  const loading = jobsQuery.isLoading;

  const leadMap = Object.fromEntries(leads.map((l) => [l.id, l.name]));

  const fetchJobs = useCallback(() => {
    void qc.invalidateQueries({ queryKey: ["installations"] });
  }, [qc]);

  const filteredLeadsForCreate = leads.filter((l) =>
    l.name.toLowerCase().includes(createLeadSearch.toLowerCase())
  );

  const filtered = jobs.filter((j) => {
    const matchTab = activeTab === "All" || j.status === TAB_TO_STATUS[activeTab];
    const matchSearch =
      !search ||
      j.job_number.toLowerCase().includes(search.toLowerCase()) ||
      (j.installation_address ?? "").toLowerCase().includes(search.toLowerCase());
    return matchTab && matchSearch;
  });

  function resetCreate() {
    setCreateOrderId("");
    setCreateTicketId("");
    setCreateScheduledAt("");
    setCreateAddress("");
    setCreateLeadSearch("");
    setCreateLeadId(null);
  }

  async function handleCreate() {
    if (!createOrderId) { showToast("Order ID is required", true); return; }
    if (!createLeadId) { showToast("Please select a lead", true); return; }
    setCreateSaving(true);
    try {
      const body: Record<string, unknown> = {
        order_id: Number(createOrderId),
        lead_id: createLeadId,
        ticket_id: createTicketId ? Number(createTicketId) : null,
        scheduled_at: createScheduledAt || null,
        installation_address: createAddress.trim() || null,
      };
      const res = await apiFetch(`${API_BASE}/crm/installations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error((err as { detail?: string }).detail || "Failed to create job");
      }
      showToast("Installation job created");
      setCreating(false);
      resetCreate();
      fetchJobs();
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Failed to create job", true);
    } finally {
      setCreateSaving(false);
    }
  }

  async function handleStatusChange(id: number, status: string) {
    setStatusLoading((p) => ({ ...p, [id]: true }));
    try {
      const res = await apiFetch(`${API_BASE}/crm/installations/${id}/status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) throw new Error("Failed to update status");
      showToast("Status updated");
      fetchJobs();
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Status update failed", true);
    } finally {
      setStatusLoading((p) => ({ ...p, [id]: false }));
    }
  }

  async function handleAssign() {
    if (!assignJobId || !assignUserId) return;
    setAssignSaving(true);
    try {
      const res = await apiFetch(`${API_BASE}/crm/installations/${assignJobId}/assign`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: Number(assignUserId) }),
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) throw new Error("Failed to assign job");
      showToast("Job assigned");
      setAssignJobId(null);
      setAssignUserId("");
      fetchJobs();
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Assign failed", true);
    } finally {
      setAssignSaving(false);
    }
  }

  async function handleCheckPrerequisites(id: number) {
    setPrereqJobId(id);
    setPrereqResult(null);
    setPrereqLoading(true);
    try {
      const res = await apiFetch(`${API_BASE}/crm/installations/${id}/prerequisites`);
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) throw new Error("Failed to check prerequisites");
      const data = await res.json();
      setPrereqResult(data);
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Prerequisites check failed", true);
      setPrereqJobId(null);
    } finally {
      setPrereqLoading(false);
    }
  }

  async function handleComplete() {
    if (!completeJob) return;
    setCompleteSaving(true);
    try {
      const body: Record<string, unknown> = {
        completion_notes: completeNotes.trim() || null,
        csat_score: completeCsat ? Number(completeCsat) : null,
      };
      const res = await apiFetch(`${API_BASE}/crm/installations/${completeJob.id}/complete`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) throw new Error("Failed to complete job");
      showToast("Job marked complete");
      setCompleteJob(null);
      setCompleteNotes("");
      setCompleteCsat("");
      fetchJobs();
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Complete failed", true);
    } finally {
      setCompleteSaving(false);
    }
  }

  return (
    <div className="space-y-6 pb-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.2em] text-violet-600 dark:text-violet-300">
            Field Ops
          </p>
          <h1 className="text-4xl font-bold tracking-tight text-slate-900 dark:text-white">
            <span className="gradient-text">Installations</span>
          </h1>
          <p className="mt-2 text-slate-600 dark:text-slate-400">
            Schedule and track field installation jobs
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => { setCreating((v) => !v); if (creating) resetCreate(); }}
            className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-violet-500/20 transition hover:scale-[1.01]"
          >
            <Plus className="h-4 w-4" /> New Job
          </button>
          <UserChip />
        </div>
      </div>

      {/* Toast */}
      {toast && (
        <div
          className={`rounded-xl border px-4 py-3 text-sm transition-all ${
            toastError
              ? "border-red-200 bg-red-50 text-red-700 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-300"
              : "border-violet-200 bg-violet-50 text-violet-700 dark:border-violet-500/20 dark:bg-violet-500/10 dark:text-violet-200"
          }`}
        >
          {toast}
        </div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {[
          { label: "Total Jobs", value: jobs.length, icon: Wrench, color: "text-violet-600 dark:text-violet-400", bg: "bg-violet-100 dark:bg-violet-500/10" },
          { label: "Scheduled", value: jobs.filter((j) => j.status === "scheduled").length, icon: ClipboardCheck, color: "text-blue-600 dark:text-blue-400", bg: "bg-blue-100 dark:bg-blue-500/10" },
          { label: "In Progress", value: jobs.filter((j) => j.status === "in_progress").length, icon: AlertCircle, color: "text-indigo-600 dark:text-indigo-400", bg: "bg-indigo-100 dark:bg-indigo-500/10" },
          { label: "Completed", value: jobs.filter((j) => j.status === "completed").length, icon: CheckCircle2, color: "text-emerald-600 dark:text-emerald-400", bg: "bg-emerald-100 dark:bg-emerald-500/10" },
        ].map(({ label, value, icon: Icon, color, bg }) => (
          <div key={label} className="rounded-2xl glass border border-white/40 dark:border-white/10 p-6 flex items-center gap-4">
            <div className={`flex h-11 w-11 items-center justify-center rounded-xl ${bg}`}>
              <Icon className={`h-5 w-5 ${color}`} />
            </div>
            <div>
              <p className="text-2xl font-bold text-slate-900 dark:text-white">{value}</p>
              <p className="text-xs text-slate-500 dark:text-slate-400">{label}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Create panel */}
      {creating && (
        <div className="rounded-2xl glass border border-violet-200 dark:border-violet-500/20 p-6 shadow-lg space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-slate-900 dark:text-white">New Installation Job</h2>
            <button onClick={() => { setCreating(false); resetCreate(); }} className="rounded-lg p-1 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200">
              <X className="h-5 w-5" />
            </button>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {/* Order ID */}
            <div>
              <label className={labelClass}>Order ID <span className="text-red-500">*</span></label>
              <input
                type="number"
                value={createOrderId}
                onChange={(e) => setCreateOrderId(e.target.value)}
                placeholder="Order number"
                className={inputClass}
              />
            </div>

            {/* Lead */}
            <div className="relative">
              <label className={labelClass}>Lead <span className="text-red-500">*</span></label>
              <input
                value={createLeadSearch}
                onChange={(e) => { setCreateLeadSearch(e.target.value); setCreateLeadId(null); }}
                placeholder="Search lead name…"
                className={inputClass}
              />
              {createLeadSearch && !createLeadId && filteredLeadsForCreate.length > 0 && (
                <div className="absolute z-20 mt-1 w-full rounded-xl border border-slate-200 bg-white shadow-lg dark:border-white/10 dark:bg-slate-900 max-h-40 overflow-y-auto">
                  {filteredLeadsForCreate.slice(0, 10).map((l) => (
                    <button
                      key={l.id}
                      onClick={() => { setCreateLeadId(l.id); setCreateLeadSearch(l.name); }}
                      className="w-full px-3 py-2 text-left text-sm hover:bg-violet-50 dark:hover:bg-violet-500/10 text-slate-800 dark:text-slate-100"
                    >
                      {l.name}
                    </button>
                  ))}
                </div>
              )}
              {createLeadId && (
                <p className="mt-1 text-xs text-emerald-600 dark:text-emerald-400">Lead selected (ID {createLeadId})</p>
              )}
            </div>

            {/* Ticket ID */}
            <div>
              <label className={labelClass}>Ticket ID (optional)</label>
              <input
                type="number"
                value={createTicketId}
                onChange={(e) => setCreateTicketId(e.target.value)}
                placeholder="Linked ticket ID"
                className={inputClass}
              />
            </div>

            {/* Scheduled At */}
            <div>
              <label className={labelClass}>Scheduled At</label>
              <input
                type="datetime-local"
                value={createScheduledAt}
                onChange={(e) => setCreateScheduledAt(e.target.value)}
                className={inputClass}
              />
            </div>
          </div>

          {/* Address */}
          <div>
            <label className={labelClass}>Installation Address</label>
            <textarea
              value={createAddress}
              onChange={(e) => setCreateAddress(e.target.value)}
              rows={2}
              placeholder="Full installation address…"
              className={`${inputClass} resize-none`}
            />
          </div>

          <div className="flex gap-3 pt-1">
            <button
              onClick={handleCreate}
              disabled={createSaving}
              className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-violet-500/20 disabled:opacity-60"
            >
              {createSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              Create Job
            </button>
            <button
              onClick={() => { setCreating(false); resetCreate(); }}
              className="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-600 dark:border-white/10 dark:text-slate-300"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Filter row */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex gap-1 rounded-xl bg-slate-100 p-1 dark:bg-slate-800/50 w-fit overflow-x-auto">
          {STATUS_TABS.map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-all whitespace-nowrap ${
                activeTab === tab
                  ? "bg-white text-slate-900 shadow-sm dark:bg-slate-700 dark:text-white"
                  : "text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
              }`}
            >
              {tab}
            </button>
          ))}
        </div>
        <div className="relative max-w-xs w-full">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search jobs…"
            className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40 dark:text-white pl-9"
          />
          <Wrench className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
        </div>
      </div>

      {/* Table */}
      {loading ? (
        <div className="flex items-center justify-center py-16 text-slate-500">
          <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading jobs…
        </div>
      ) : filtered.length === 0 ? (
        <div className="rounded-2xl glass border border-dashed border-slate-300 px-6 py-16 text-center text-slate-500 dark:border-white/10">
          {activeTab === "All" && !search
            ? "No installation jobs yet. Create one above."
            : "No jobs match the current filter."}
        </div>
      ) : (
        <div className="rounded-2xl glass border border-white/40 dark:border-white/10 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50/80 dark:border-white/10 dark:bg-slate-800/40">
                  {["Job #", "Lead", "Order ID", "Status", "Scheduled At", "Assigned User", "Prerequisites", "Completed At", "Actions"].map((col) => (
                    <th key={col} className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400 whitespace-nowrap">
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-white/5">
                {filtered.map((job) => (
                  <tr key={job.id} className="hover:bg-slate-50/60 dark:hover:bg-white/[0.02] transition-colors">
                    <td className="px-4 py-3 font-mono text-xs font-semibold text-violet-700 dark:text-violet-300 whitespace-nowrap">
                      {job.job_number}
                    </td>
                    <td className="px-4 py-3 text-slate-800 dark:text-slate-100 whitespace-nowrap">
                      {leadMap[job.lead_id] ?? `#${job.lead_id}`}
                    </td>
                    <td className="px-4 py-3 text-slate-500 dark:text-slate-400">
                      {job.order_id}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <select
                        value={job.status}
                        onChange={(e) => handleStatusChange(job.id, e.target.value)}
                        disabled={statusLoading[job.id]}
                        className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40 dark:text-white"
                      >
                        {ALL_STATUSES.map((s) => (
                          <option key={s} value={s} className="capitalize">{s.replace(/_/g, " ")}</option>
                        ))}
                      </select>
                    </td>
                    <td className="px-4 py-3 text-slate-500 dark:text-slate-400 whitespace-nowrap">
                      {fmtDateTime(job.scheduled_at)}
                    </td>
                    <td className="px-4 py-3 text-slate-500 dark:text-slate-400">
                      {job.assigned_user_id ?? "—"}
                    </td>
                    <td className="px-4 py-3">
                      {job.prerequisites_met ? (
                        <span className="inline-flex items-center gap-1 text-emerald-600 dark:text-emerald-400 text-xs font-semibold">
                          <CheckCircle2 className="h-3.5 w-3.5" /> Met
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-red-500 dark:text-red-400 text-xs font-semibold">
                          <XCircle className="h-3.5 w-3.5" /> Unmet
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-slate-500 dark:text-slate-400 whitespace-nowrap">
                      {fmtDate(job.completed_at)}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1">
                        {/* Assign */}
                        <button
                          onClick={() => { setAssignJobId(job.id); setAssignUserId(job.assigned_user_id?.toString() ?? ""); }}
                          title="Assign user"
                          className="rounded-lg px-2 py-1 text-xs font-medium text-violet-600 hover:bg-violet-50 dark:text-violet-300 dark:hover:bg-violet-500/10 whitespace-nowrap"
                        >
                          Assign
                        </button>
                        {/* Check Prerequisites */}
                        <button
                          onClick={() => handleCheckPrerequisites(job.id)}
                          title="Check prerequisites"
                          className="rounded-lg px-2 py-1 text-xs font-medium text-amber-600 hover:bg-amber-50 dark:text-amber-300 dark:hover:bg-amber-500/10 whitespace-nowrap"
                        >
                          Prereqs
                        </button>
                        {/* Complete */}
                        {job.status === "in_progress" && (
                          <button
                            onClick={() => { setCompleteJob(job); setCompleteNotes(""); setCompleteCsat(""); }}
                            title="Complete job"
                            className="rounded-lg px-2 py-1 text-xs font-medium text-emerald-600 hover:bg-emerald-50 dark:text-emerald-300 dark:hover:bg-emerald-500/10 whitespace-nowrap"
                          >
                            Complete
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Assign modal */}
      {assignJobId !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setAssignJobId(null)} />
          <div className="relative w-full max-w-sm rounded-2xl bg-white dark:bg-slate-900 shadow-2xl p-6 space-y-4 mx-4">
            <div className="flex items-center justify-between">
              <h3 className="text-base font-semibold text-slate-900 dark:text-white">Assign Job</h3>
              <button onClick={() => setAssignJobId(null)} className="rounded-lg p-1 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200">
                <X className="h-5 w-5" />
              </button>
            </div>
            <div>
              <label className={labelClass}>User ID</label>
              <input
                type="number"
                value={assignUserId}
                onChange={(e) => setAssignUserId(e.target.value)}
                placeholder="Enter user ID"
                className={inputClass}
              />
            </div>
            <div className="flex gap-3">
              <button
                onClick={handleAssign}
                disabled={assignSaving || !assignUserId}
                className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-violet-500/20 disabled:opacity-60"
              >
                {assignSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                Assign
              </button>
              <button
                onClick={() => setAssignJobId(null)}
                className="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-600 dark:border-white/10 dark:text-slate-300"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Prerequisites modal */}
      {prereqJobId !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={() => { setPrereqJobId(null); setPrereqResult(null); }} />
          <div className="relative w-full max-w-md rounded-2xl bg-white dark:bg-slate-900 shadow-2xl p-6 space-y-4 mx-4">
            <div className="flex items-center justify-between">
              <h3 className="text-base font-semibold text-slate-900 dark:text-white">Prerequisites Check</h3>
              <button onClick={() => { setPrereqJobId(null); setPrereqResult(null); }} className="rounded-lg p-1 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200">
                <X className="h-5 w-5" />
              </button>
            </div>
            {prereqLoading ? (
              <div className="flex items-center gap-2 text-slate-500 py-4 justify-center">
                <Loader2 className="h-5 w-5 animate-spin" /> Checking…
              </div>
            ) : prereqResult ? (
              <div className="space-y-3">
                <div className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-sm font-semibold ${prereqResult.all_met ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300" : "bg-red-100 text-red-700 dark:bg-red-500/10 dark:text-red-300"}`}>
                  {prereqResult.all_met ? <CheckCircle2 className="h-4 w-4" /> : <XCircle className="h-4 w-4" />}
                  {prereqResult.all_met ? "All prerequisites met" : "Some prerequisites unmet"}
                </div>
                {prereqResult.met.length > 0 && (
                  <div>
                    <p className="text-xs font-semibold text-emerald-600 dark:text-emerald-400 mb-1">Met</p>
                    <ul className="space-y-1">
                      {prereqResult.met.map((item, i) => (
                        <li key={i} className="flex items-start gap-2 text-sm text-slate-700 dark:text-slate-200">
                          <CheckCircle2 className="h-4 w-4 text-emerald-500 mt-0.5 shrink-0" />
                          {item}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {prereqResult.unmet.length > 0 && (
                  <div>
                    <p className="text-xs font-semibold text-red-600 dark:text-red-400 mb-1">Unmet</p>
                    <ul className="space-y-1">
                      {prereqResult.unmet.map((item, i) => (
                        <li key={i} className="flex items-start gap-2 text-sm text-slate-700 dark:text-slate-200">
                          <XCircle className="h-4 w-4 text-red-500 mt-0.5 shrink-0" />
                          {item}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            ) : null}
            <button
              onClick={() => { setPrereqJobId(null); setPrereqResult(null); }}
              className="w-full rounded-xl border border-slate-200 py-2 text-sm font-semibold text-slate-600 dark:border-white/10 dark:text-slate-300"
            >
              Close
            </button>
          </div>
        </div>
      )}

      {/* Complete modal */}
      {completeJob && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setCompleteJob(null)} />
          <div className="relative w-full max-w-md rounded-2xl bg-white dark:bg-slate-900 shadow-2xl p-6 space-y-4 mx-4">
            <div className="flex items-center justify-between">
              <h3 className="text-base font-semibold text-slate-900 dark:text-white">
                Complete Job — {completeJob.job_number}
              </h3>
              <button onClick={() => setCompleteJob(null)} className="rounded-lg p-1 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200">
                <X className="h-5 w-5" />
              </button>
            </div>
            <div>
              <label className={labelClass}>Completion Notes</label>
              <textarea
                value={completeNotes}
                onChange={(e) => setCompleteNotes(e.target.value)}
                rows={3}
                placeholder="Describe what was done…"
                className={`${inputClass} resize-none`}
              />
            </div>
            <div>
              <label className={labelClass}>CSAT Score (1–5)</label>
              <select value={completeCsat} onChange={(e) => setCompleteCsat(e.target.value)} className={inputClass}>
                <option value="">No rating</option>
                {[1, 2, 3, 4, 5].map((n) => (
                  <option key={n} value={n}>{n} star{n !== 1 ? "s" : ""}</option>
                ))}
              </select>
            </div>
            <div className="flex gap-3">
              <button
                onClick={handleComplete}
                disabled={completeSaving}
                className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-500 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-emerald-500/20 disabled:opacity-60"
              >
                {completeSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                Mark Complete
              </button>
              <button
                onClick={() => setCompleteJob(null)}
                className="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-600 dark:border-white/10 dark:text-slate-300"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
