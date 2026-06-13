"use client";

import React, { useCallback, useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle,
  Clock,
  Loader2,
  MessageSquare,
  Plus,
  Star,
  TicketIcon,
  X,
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

type Ticket = {
  id: number;
  ticket_number: string;
  lead_id?: number;
  account_id?: number;
  order_id?: number;
  assignee_user_id?: number;
  title: string;
  description?: string;
  status: string;
  priority: string;
  category: string;
  channel: string;
  sla_hours: number;
  sla_due_at?: string;
  first_response_at?: string;
  resolved_at?: string;
  closed_at?: string;
  csat_score?: number;
  created_at?: string;
};

type Comment = {
  id: number;
  body: string;
  is_internal: boolean;
  author_user_id?: number;
  created_at?: string;
};

type Lead = { id: number; name: string };

const STATUS_COLORS: Record<string, string> = {
  open: "bg-blue-100 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300",
  in_progress: "bg-violet-100 text-violet-700 dark:bg-violet-500/10 dark:text-violet-300",
  pending_customer: "bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300",
  pending_parts: "bg-orange-100 text-orange-700 dark:bg-orange-500/10 dark:text-orange-300",
  resolved: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300",
  closed: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400",
  escalated: "bg-red-100 text-red-700 dark:bg-red-500/10 dark:text-red-300",
};

const PRIORITY_COLORS: Record<string, string> = {
  low: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400",
  medium: "bg-blue-100 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300",
  high: "bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300",
  critical: "bg-red-100 text-red-700 dark:bg-red-500/10 dark:text-red-300",
};

const STATUS_TABS = [
  "All",
  "Open",
  "In Progress",
  "Pending Customer",
  "Escalated",
  "Resolved",
  "Closed",
];

const TAB_TO_STATUS: Record<string, string> = {
  "Open": "open",
  "In Progress": "in_progress",
  "Pending Customer": "pending_customer",
  "Escalated": "escalated",
  "Resolved": "resolved",
  "Closed": "closed",
};

const ALL_STATUSES = ["open", "in_progress", "pending_customer", "pending_parts", "resolved", "closed", "escalated"];
const PRIORITIES = ["low", "medium", "high", "critical"];
const CATEGORIES = ["installation", "maintenance", "billing", "general"];
const CHANNELS = ["manual", "call", "email", "whatsapp"];

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

function isSlaBreached(ticket: Ticket): boolean {
  if (!ticket.sla_due_at) return false;
  if (ticket.status === "resolved" || ticket.status === "closed") return false;
  return new Date(ticket.sla_due_at) < new Date();
}

function StarRating({ score }: { score?: number | null }) {
  if (!score) return null;
  return (
    <div className="flex items-center gap-0.5">
      {[1, 2, 3, 4, 5].map((s) => (
        <Star
          key={s}
          className={`h-3.5 w-3.5 ${s <= score ? "text-amber-400 fill-amber-400" : "text-slate-300 dark:text-slate-600"}`}
        />
      ))}
    </div>
  );
}

const inputClass =
  "w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40 dark:text-white";
const labelClass = "block text-xs font-semibold text-slate-500 dark:text-slate-400 mb-1";

export default function TicketsPage() {
  const { user, sessionTimeout } = useAuth();
  const qc = useQueryClient();

  const [toast, setToast] = useState<string | null>(null);
  const [toastError, setToastError] = useState(false);
  const [activeTab, setActiveTab] = useState("All");
  const [search, setSearch] = useState("");

  // Create panel
  const [creating, setCreating] = useState(false);
  const [createSaving, setCreateSaving] = useState(false);
  const [createTitle, setCreateTitle] = useState("");
  const [createDesc, setCreateDesc] = useState("");
  const [createPriority, setCreatePriority] = useState("medium");
  const [createCategory, setCreateCategory] = useState("general");
  const [createChannel, setCreateChannel] = useState("manual");
  const [createSlaHours, setCreateSlaHours] = useState(24);
  const [createOrderId, setCreateOrderId] = useState("");
  const [createLeadSearch, setCreateLeadSearch] = useState("");
  const [createLeadId, setCreateLeadId] = useState<number | null>(null);

  // Detail panel
  const [detailTicket, setDetailTicket] = useState<Ticket | null>(null);
  const [comments, setComments] = useState<Comment[]>([]);
  const [commentsLoading, setCommentsLoading] = useState(false);
  const [commentBody, setCommentBody] = useState("");
  const [commentInternal, setCommentInternal] = useState(false);
  const [commentSaving, setCommentSaving] = useState(false);

  // Status update loading
  const [statusLoading, setStatusLoading] = useState<Record<number, boolean>>({});

  function showToast(msg: string, error = false) {
    setToast(msg);
    setToastError(error);
    setTimeout(() => setToast(null), 3500);
  }

  // Queries
  const ticketsQuery = useQuery<Ticket[]>({
    queryKey: ["tickets"],
    enabled: !!user,
    refetchInterval: 30_000,
    queryFn: async () => {
      const res = await apiFetch(`${API_BASE}/crm/tickets`);
      if (res.status === 401) { sessionTimeout(); throw new Error("unauthorized"); }
      if (!res.ok) throw new Error("Failed to load tickets");
      const data = await res.json();
      return Array.isArray(data) ? data : data.items ?? [];
    },
  });

  const leadsQuery = useQuery<Lead[]>({
    queryKey: ["tickets-leads"],
    enabled: !!user,
    staleTime: 5 * 60_000,
    queryFn: async () => {
      const res = await apiFetch(`${API_BASE}/crm/leads?page=1&limit=200`);
      if (!res.ok) return [];
      const d = await res.json();
      return d.items ?? d ?? [];
    },
  });

  const tickets: Ticket[] = ticketsQuery.data ?? [];
  const leads: Lead[] = leadsQuery.data ?? [];
  const loading = ticketsQuery.isLoading;

  const leadMap = Object.fromEntries(leads.map((l) => [l.id, l.name]));

  const fetchTickets = useCallback(() => {
    void qc.invalidateQueries({ queryKey: ["tickets"] });
  }, [qc]);

  // Stats
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const resolvedToday = tickets.filter(
    (t) => t.resolved_at && new Date(t.resolved_at) >= today
  ).length;

  // Filtered
  const filtered = tickets.filter((t) => {
    const matchTab =
      activeTab === "All" || t.status === TAB_TO_STATUS[activeTab];
    const matchSearch =
      !search || t.title.toLowerCase().includes(search.toLowerCase()) ||
      t.ticket_number.toLowerCase().includes(search.toLowerCase());
    return matchTab && matchSearch;
  });

  const filteredLeadsForCreate = leads.filter((l) =>
    l.name.toLowerCase().includes(createLeadSearch.toLowerCase())
  );

  // Load comments when detail opens
  useEffect(() => {
    if (!detailTicket) { setComments([]); return; }
    setCommentsLoading(true);
    apiFetch(`${API_BASE}/crm/tickets/${detailTicket.id}/comments`)
      .then(async (res) => {
        if (!res.ok) return;
        const d = await res.json();
        setComments(Array.isArray(d) ? d : d.items ?? []);
      })
      .catch(() => {})
      .finally(() => setCommentsLoading(false));
  }, [detailTicket]);

  function resetCreate() {
    setCreateTitle("");
    setCreateDesc("");
    setCreatePriority("medium");
    setCreateCategory("general");
    setCreateChannel("manual");
    setCreateSlaHours(24);
    setCreateOrderId("");
    setCreateLeadSearch("");
    setCreateLeadId(null);
  }

  async function handleCreate() {
    if (!createTitle.trim()) { showToast("Title is required", true); return; }
    setCreateSaving(true);
    try {
      const body: Record<string, unknown> = {
        title: createTitle.trim(),
        description: createDesc.trim() || null,
        priority: createPriority,
        category: createCategory,
        channel: createChannel,
        sla_hours: createSlaHours,
        lead_id: createLeadId ?? null,
        order_id: createOrderId ? Number(createOrderId) : null,
      };
      const res = await apiFetch(`${API_BASE}/crm/tickets`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error((err as { detail?: string }).detail || "Failed to create ticket");
      }
      showToast("Ticket created");
      setCreating(false);
      resetCreate();
      fetchTickets();
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Failed to create ticket", true);
    } finally {
      setCreateSaving(false);
    }
  }

  async function handleStatusChange(id: number, status: string) {
    setStatusLoading((p) => ({ ...p, [id]: true }));
    try {
      const res = await apiFetch(`${API_BASE}/crm/tickets/${id}/status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) throw new Error("Failed to update status");
      showToast("Status updated");
      fetchTickets();
      if (detailTicket?.id === id) {
        setDetailTicket((prev) => prev ? { ...prev, status } : prev);
      }
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Status update failed", true);
    } finally {
      setStatusLoading((p) => ({ ...p, [id]: false }));
    }
  }

  async function handleAddComment() {
    if (!detailTicket || !commentBody.trim()) return;
    setCommentSaving(true);
    try {
      const res = await apiFetch(`${API_BASE}/crm/tickets/${detailTicket.id}/comments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body: commentBody.trim(), is_internal: commentInternal }),
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) throw new Error("Failed to add comment");
      const newComment = await res.json();
      setComments((prev) => [...prev, newComment]);
      setCommentBody("");
      setCommentInternal(false);
      showToast("Comment added");
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Failed to add comment", true);
    } finally {
      setCommentSaving(false);
    }
  }

  return (
    <div className="space-y-6 pb-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.2em] text-violet-600 dark:text-violet-300">
            Support
          </p>
          <h1 className="text-4xl font-bold tracking-tight text-slate-900 dark:text-white">
            <span className="gradient-text">Tickets</span>
          </h1>
          <p className="mt-2 text-slate-600 dark:text-slate-400">
            Manage customer support tickets and SLAs
          </p>
        </div>
        <button
          onClick={() => { setCreating((v) => !v); if (creating) resetCreate(); }}
          className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-violet-500/20 transition hover:scale-[1.01]"
        >
          <Plus className="h-4 w-4" /> New Ticket
        </button>
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
          { label: "Total", value: tickets.length, icon: TicketIcon, color: "text-violet-600 dark:text-violet-400", bg: "bg-violet-100 dark:bg-violet-500/10" },
          { label: "Open", value: tickets.filter((t) => t.status === "open").length, icon: Clock, color: "text-blue-600 dark:text-blue-400", bg: "bg-blue-100 dark:bg-blue-500/10" },
          { label: "Escalated", value: tickets.filter((t) => t.status === "escalated").length, icon: AlertTriangle, color: "text-red-600 dark:text-red-400", bg: "bg-red-100 dark:bg-red-500/10" },
          { label: "Resolved Today", value: resolvedToday, icon: CheckCircle, color: "text-emerald-600 dark:text-emerald-400", bg: "bg-emerald-100 dark:bg-emerald-500/10" },
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
            <h2 className="text-lg font-semibold text-slate-900 dark:text-white">New Ticket</h2>
            <button onClick={() => { setCreating(false); resetCreate(); }} className="rounded-lg p-1 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200">
              <X className="h-5 w-5" />
            </button>
          </div>

          {/* Title */}
          <div>
            <label className={labelClass}>Title <span className="text-red-500">*</span></label>
            <input
              value={createTitle}
              onChange={(e) => setCreateTitle(e.target.value)}
              placeholder="Describe the issue…"
              className={inputClass}
            />
          </div>

          {/* Description */}
          <div>
            <label className={labelClass}>Description</label>
            <textarea
              value={createDesc}
              onChange={(e) => setCreateDesc(e.target.value)}
              rows={3}
              placeholder="Additional details…"
              className={`${inputClass} resize-none`}
            />
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {/* Priority */}
            <div>
              <label className={labelClass}>Priority</label>
              <select value={createPriority} onChange={(e) => setCreatePriority(e.target.value)} className={inputClass}>
                {PRIORITIES.map((p) => <option key={p} value={p} className="capitalize">{p}</option>)}
              </select>
            </div>

            {/* Category */}
            <div>
              <label className={labelClass}>Category</label>
              <select value={createCategory} onChange={(e) => setCreateCategory(e.target.value)} className={inputClass}>
                {CATEGORIES.map((c) => <option key={c} value={c} className="capitalize">{c}</option>)}
              </select>
            </div>

            {/* Channel */}
            <div>
              <label className={labelClass}>Channel</label>
              <select value={createChannel} onChange={(e) => setCreateChannel(e.target.value)} className={inputClass}>
                {CHANNELS.map((c) => <option key={c} value={c} className="capitalize">{c}</option>)}
              </select>
            </div>

            {/* SLA Hours */}
            <div>
              <label className={labelClass}>SLA Hours</label>
              <input
                type="number"
                min={1}
                value={createSlaHours}
                onChange={(e) => setCreateSlaHours(Math.max(1, Number(e.target.value)))}
                className={inputClass}
              />
            </div>

            {/* Order ID */}
            <div>
              <label className={labelClass}>Order ID (optional)</label>
              <input
                type="number"
                value={createOrderId}
                onChange={(e) => setCreateOrderId(e.target.value)}
                placeholder="Order number"
                className={inputClass}
              />
            </div>

            {/* Lead selector */}
            <div className="relative">
              <label className={labelClass}>Lead (optional)</label>
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
          </div>

          <div className="flex gap-3 pt-1">
            <button
              onClick={handleCreate}
              disabled={createSaving}
              className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-violet-500/20 disabled:opacity-60"
            >
              {createSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              Create Ticket
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
            placeholder="Search tickets…"
            className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40 dark:text-white pl-9"
          />
          <TicketIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
        </div>
      </div>

      {/* Table */}
      {loading ? (
        <div className="flex items-center justify-center py-16 text-slate-500">
          <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading tickets…
        </div>
      ) : filtered.length === 0 ? (
        <div className="rounded-2xl glass border border-dashed border-slate-300 px-6 py-16 text-center text-slate-500 dark:border-white/10">
          {activeTab === "All" && !search
            ? "No tickets yet. Create your first ticket above."
            : `No tickets match the current filter.`}
        </div>
      ) : (
        <div className="rounded-2xl glass border border-white/40 dark:border-white/10 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50/80 dark:border-white/10 dark:bg-slate-800/40">
                  {["Ticket #", "Title", "Lead", "Priority", "Status", "Category", "SLA Due", "Assignee", "Created", "Actions"].map((col) => (
                    <th key={col} className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400 whitespace-nowrap">
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-white/5">
                {filtered.map((ticket) => (
                  <tr
                    key={ticket.id}
                    className="hover:bg-slate-50/60 dark:hover:bg-white/[0.02] transition-colors cursor-pointer"
                    onClick={() => setDetailTicket(ticket)}
                  >
                    <td className="px-4 py-3 whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                      <div className="flex items-center gap-1.5">
                        <span className="font-mono text-xs font-semibold text-violet-700 dark:text-violet-300">
                          {ticket.ticket_number}
                        </span>
                        {isSlaBreached(ticket) && (
                          <span className="rounded-full bg-red-100 px-1.5 py-0.5 text-[10px] font-bold text-red-700 dark:bg-red-500/20 dark:text-red-300 whitespace-nowrap">
                            SLA BREACHED
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3 max-w-[200px]">
                      <span className="truncate block text-slate-800 dark:text-slate-100">{ticket.title}</span>
                    </td>
                    <td className="px-4 py-3 text-slate-500 dark:text-slate-400 whitespace-nowrap">
                      {ticket.lead_id ? (leadMap[ticket.lead_id] ?? `#${ticket.lead_id}`) : "—"}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${PRIORITY_COLORS[ticket.priority] ?? PRIORITY_COLORS.medium}`}>
                        {ticket.priority}
                      </span>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                      <select
                        value={ticket.status}
                        onChange={(e) => handleStatusChange(ticket.id, e.target.value)}
                        disabled={statusLoading[ticket.id]}
                        className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40 dark:text-white capitalize"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {ALL_STATUSES.map((s) => (
                          <option key={s} value={s} className="capitalize">{s.replace(/_/g, " ")}</option>
                        ))}
                      </select>
                    </td>
                    <td className="px-4 py-3 text-slate-500 dark:text-slate-400 capitalize whitespace-nowrap">
                      {ticket.category}
                    </td>
                    <td className="px-4 py-3 text-slate-500 dark:text-slate-400 whitespace-nowrap">
                      {fmtDateTime(ticket.sla_due_at)}
                    </td>
                    <td className="px-4 py-3 text-slate-500 dark:text-slate-400 whitespace-nowrap">
                      {ticket.assignee_user_id ?? "—"}
                    </td>
                    <td className="px-4 py-3 text-slate-500 dark:text-slate-400 whitespace-nowrap">
                      {fmtDate(ticket.created_at)}
                    </td>
                    <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                      <button
                        onClick={() => setDetailTicket(ticket)}
                        title="View details & comments"
                        className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-violet-600 dark:hover:bg-white/10 dark:hover:text-violet-300"
                      >
                        <MessageSquare className="h-4 w-4" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Detail panel — right slide-in overlay */}
      {detailTicket && (
        <div className="fixed inset-0 z-50 flex">
          {/* Backdrop */}
          <div
            className="flex-1 bg-black/40 backdrop-blur-sm"
            onClick={() => setDetailTicket(null)}
          />
          {/* Panel */}
          <div className="w-full max-w-lg bg-white dark:bg-slate-900 shadow-2xl overflow-y-auto flex flex-col">
            {/* Panel header */}
            <div className="flex items-center justify-between border-b border-slate-200 dark:border-white/10 px-6 py-4 sticky top-0 bg-white dark:bg-slate-900 z-10">
              <div className="min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-mono text-xs font-semibold text-violet-700 dark:text-violet-300">
                    {detailTicket.ticket_number}
                  </span>
                  {isSlaBreached(detailTicket) && (
                    <span className="rounded-full bg-red-100 px-2 py-0.5 text-[10px] font-bold text-red-700 dark:bg-red-500/20 dark:text-red-300">
                      SLA BREACHED
                    </span>
                  )}
                  <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${STATUS_COLORS[detailTicket.status] ?? ""}`}>
                    {detailTicket.status.replace(/_/g, " ")}
                  </span>
                </div>
                <h3 className="mt-1 font-semibold text-slate-900 dark:text-white truncate">
                  {detailTicket.title}
                </h3>
              </div>
              <button
                onClick={() => setDetailTicket(null)}
                className="ml-4 rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 dark:hover:bg-white/10"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="flex-1 px-6 py-5 space-y-5">
              {/* Meta */}
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div>
                  <p className="text-xs text-slate-400 mb-0.5">Priority</p>
                  <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${PRIORITY_COLORS[detailTicket.priority] ?? ""}`}>
                    {detailTicket.priority}
                  </span>
                </div>
                <div>
                  <p className="text-xs text-slate-400 mb-0.5">Category</p>
                  <p className="text-slate-700 dark:text-slate-200 capitalize">{detailTicket.category}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-400 mb-0.5">Channel</p>
                  <p className="text-slate-700 dark:text-slate-200 capitalize">{detailTicket.channel}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-400 mb-0.5">SLA Hours</p>
                  <p className="text-slate-700 dark:text-slate-200">{detailTicket.sla_hours}h</p>
                </div>
                <div>
                  <p className="text-xs text-slate-400 mb-0.5">SLA Due</p>
                  <p className="text-slate-700 dark:text-slate-200">{fmtDateTime(detailTicket.sla_due_at)}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-400 mb-0.5">Lead</p>
                  <p className="text-slate-700 dark:text-slate-200">
                    {detailTicket.lead_id ? (leadMap[detailTicket.lead_id] ?? `#${detailTicket.lead_id}`) : "—"}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-slate-400 mb-0.5">Order ID</p>
                  <p className="text-slate-700 dark:text-slate-200">{detailTicket.order_id ?? "—"}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-400 mb-0.5">Assignee</p>
                  <p className="text-slate-700 dark:text-slate-200">{detailTicket.assignee_user_id ?? "—"}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-400 mb-0.5">Created</p>
                  <p className="text-slate-700 dark:text-slate-200">{fmtDate(detailTicket.created_at)}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-400 mb-0.5">First Response</p>
                  <p className="text-slate-700 dark:text-slate-200">{fmtDateTime(detailTicket.first_response_at)}</p>
                </div>
                {(detailTicket.status === "resolved" || detailTicket.status === "closed") && (
                  <div>
                    <p className="text-xs text-slate-400 mb-0.5">CSAT</p>
                    {detailTicket.csat_score ? (
                      <StarRating score={detailTicket.csat_score} />
                    ) : (
                      <p className="text-slate-400 text-xs">No rating</p>
                    )}
                  </div>
                )}
              </div>

              {/* Description */}
              {detailTicket.description && (
                <div>
                  <p className="text-xs font-semibold text-slate-400 mb-1">Description</p>
                  <p className="text-sm text-slate-700 dark:text-slate-200 leading-relaxed whitespace-pre-wrap">
                    {detailTicket.description}
                  </p>
                </div>
              )}

              {/* Status update */}
              <div>
                <p className="text-xs font-semibold text-slate-400 mb-1">Update Status</p>
                <select
                  value={detailTicket.status}
                  onChange={(e) => handleStatusChange(detailTicket.id, e.target.value)}
                  disabled={statusLoading[detailTicket.id]}
                  className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40 dark:text-white"
                >
                  {ALL_STATUSES.map((s) => (
                    <option key={s} value={s} className="capitalize">{s.replace(/_/g, " ")}</option>
                  ))}
                </select>
              </div>

              {/* Comments */}
              <div className="space-y-3">
                <p className="text-sm font-semibold text-slate-800 dark:text-slate-100">
                  Comments {comments.length > 0 && `(${comments.length})`}
                </p>

                {commentsLoading ? (
                  <div className="flex items-center gap-2 text-slate-400 text-sm">
                    <Loader2 className="h-4 w-4 animate-spin" /> Loading…
                  </div>
                ) : comments.length === 0 ? (
                  <p className="text-xs text-slate-400 italic">No comments yet.</p>
                ) : (
                  <div className="space-y-2">
                    {comments.map((c) => (
                      <div
                        key={c.id}
                        className={`rounded-xl px-4 py-3 text-sm ${
                          c.is_internal
                            ? "bg-amber-50 border border-amber-200 dark:bg-amber-500/10 dark:border-amber-500/20"
                            : "bg-slate-50 border border-slate-200 dark:bg-white/5 dark:border-white/10"
                        }`}
                      >
                        <div className="flex items-center justify-between gap-2 mb-1">
                          <span className="text-xs text-slate-400">
                            {c.author_user_id ? `User #${c.author_user_id}` : "System"}
                          </span>
                          <div className="flex items-center gap-2">
                            {c.is_internal && (
                              <span className="rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700 dark:bg-amber-500/20 dark:text-amber-300">
                                Internal
                              </span>
                            )}
                            <span className="text-xs text-slate-400">{fmtDateTime(c.created_at)}</span>
                          </div>
                        </div>
                        <p className="text-slate-700 dark:text-slate-200 whitespace-pre-wrap">{c.body}</p>
                      </div>
                    ))}
                  </div>
                )}

                {/* Add comment */}
                <div className="space-y-2 pt-2 border-t border-slate-100 dark:border-white/10">
                  <textarea
                    value={commentBody}
                    onChange={(e) => setCommentBody(e.target.value)}
                    rows={3}
                    placeholder="Add a comment…"
                    className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40 dark:text-white resize-none"
                  />
                  <div className="flex items-center justify-between">
                    <label className="flex items-center gap-2 cursor-pointer text-sm text-slate-600 dark:text-slate-300">
                      <input
                        type="checkbox"
                        checked={commentInternal}
                        onChange={(e) => setCommentInternal(e.target.checked)}
                        className="h-4 w-4 rounded accent-amber-500"
                      />
                      Internal note
                    </label>
                    <button
                      onClick={handleAddComment}
                      disabled={commentSaving || !commentBody.trim()}
                      className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-3 py-1.5 text-xs font-semibold text-white shadow shadow-violet-500/20 disabled:opacity-60"
                    >
                      {commentSaving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <MessageSquare className="h-3.5 w-3.5" />}
                      Add Comment
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
