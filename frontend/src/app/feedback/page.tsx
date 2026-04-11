"use client";

import React, { useEffect, useMemo, useState } from "react";
import { CheckCircle, MessageSquare, RefreshCw, Send, Star, Trash2, X } from "lucide-react";
import clsx from "clsx";
import { useRouter } from "next/navigation";

import { useAuth } from "@/context/AuthContext";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:6060";

type FeedbackItem = {
  id: number;
  feedback_type: string;
  source: string;
  lead_id: number | null;
  lead_name: string;
  interaction_id: number | null;
  submitted_by_user_id: number | null;
  submitted_by_name: string;
  rating: number | null;
  comment: string | null;
  disposition: string | null;
  tags: Record<string, string> | null;
  status: string;
  assignee_user_id: number | null;
  assignee_name: string | null;
  close_loop_status: string;
  status_note: string | null;
  follow_up_task_id: number | null;
  follow_up_task_status: string | null;
  responded_at: string | null;
  created_at: string;
};

type Summary = {
  total: number;
  internal_avg_rating: number | null;
  internal_rating_distribution: Record<string, number>;
  csat_sent: number;
  csat_responded: number;
  csat_response_rate: number;
  csat_avg_rating: number | null;
  csat_rating_distribution: Record<string, number>;
  top_dispositions: { disposition: string; count: number }[];
};

type LeadOption = {
  id: number;
  name: string;
  company_name: string | null;
  normalized_phone: string | null;
};

type CompanyUser = {
  id: number;
  first_name: string | null;
  last_name: string | null;
  email: string;
};

const TYPE_LABELS: Record<string, string> = {
  call_review: "Call Review",
  csat: "CSAT",
  general: "General",
  bug_report: "Bug Report",
  feature_request: "Feature Request",
};

const TYPE_COLORS: Record<string, string> = {
  call_review: "bg-blue-500/15 text-blue-400",
  csat: "bg-violet-500/15 text-violet-400",
  general: "bg-slate-500/15 text-slate-400",
  bug_report: "bg-red-500/15 text-red-400",
  feature_request: "bg-amber-500/15 text-amber-400",
};

const DISPOSITION_COLORS: Record<string, string> = {
  interested: "text-emerald-400",
  not_interested: "text-red-400",
  callback: "text-blue-400",
  voicemail: "text-slate-400",
  no_answer: "text-slate-400",
  do_not_call: "text-red-500",
};

const STATUS_COLORS: Record<string, string> = {
  submitted: "bg-emerald-500/15 text-emerald-400",
  pending: "bg-amber-500/15 text-amber-400",
  expired: "bg-red-500/15 text-red-400",
};

function Stars({ rating, size = 4 }: { rating: number | null; size?: number }) {
  if (!rating) return <span className="text-slate-600 text-xs">-</span>;
  return (
    <div className="flex gap-0.5">
      {[1, 2, 3, 4, 5].map((i) => (
        <Star key={i} className={clsx(`h-${size} w-${size}`, i <= rating ? "text-amber-400 fill-amber-400" : "text-slate-700")} />
      ))}
    </div>
  );
}

function fmtDate(s: string | null) {
  if (!s) return "-";
  return new Date(s).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

function Distribution({
  title,
  distribution,
}: {
  title: string;
  distribution: Record<string, number>;
}) {
  const total = useMemo(() => Object.values(distribution).reduce((a, b) => a + b, 0), [distribution]);
  return (
    <div className="glass rounded-2xl border border-white/10 p-5">
      <p className="mb-4 text-[10px] font-semibold uppercase tracking-widest text-slate-500">{title}</p>
      {[5, 4, 3, 2, 1].map((n) => {
        const count = distribution[String(n)] || 0;
        const pct = total ? (count / total) * 100 : 0;
        const col = n >= 4 ? "#34d399" : n === 3 ? "#fbbf24" : "#f87171";
        return (
          <div key={n} className="mb-2 flex items-center gap-3">
            <div className="flex w-20 flex-shrink-0 gap-0.5">
              {[1, 2, 3, 4, 5].map((i) => (
                <Star key={i} className={clsx("h-3 w-3", i <= n ? "fill-amber-400 text-amber-400" : "text-slate-700")} />
              ))}
            </div>
            <div className="h-[5px] flex-1 overflow-hidden rounded-full bg-white/10">
              <div className="h-full rounded-full transition-all duration-700" style={{ width: `${pct}%`, background: col }} />
            </div>
            <span className="w-8 text-right font-mono text-xs" style={{ color: col }}>
              {count}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function LeadSearchSelect({
  token,
  value,
  onChange,
  required = false,
}: {
  token: string;
  value: LeadOption | null;
  onChange: (lead: LeadOption | null) => void;
  required?: boolean;
}) {
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<LeadOption[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!token) return;
    const q = query.trim();
    if (q.length < 2) {
      setItems([]);
      return;
    }
    const t = setTimeout(async () => {
      setLoading(true);
      try {
        const params = new URLSearchParams({ page: "1", limit: "8", search: q });
        const res = await fetch(`${API_BASE}/crm/leads?${params}`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (res.ok) {
          const data = await res.json();
          setItems((data.items || []) as LeadOption[]);
          setOpen(true);
        }
      } finally {
        setLoading(false);
      }
    }, 250);
    return () => clearTimeout(t);
  }, [query, token]);

  return (
    <div className="space-y-1">
      <label className="text-xs font-semibold uppercase text-slate-500">Lead {required ? "" : "(optional)"}</label>
      {value ? (
        <div className="flex items-center justify-between rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-200">
          <div>
            <p className="font-semibold">{value.name}</p>
            <p className="text-xs text-slate-400">
              #{value.id} {value.company_name ? `- ${value.company_name}` : ""}
            </p>
          </div>
          <button
            type="button"
            onClick={() => {
              onChange(null);
              setQuery("");
            }}
            className="rounded-lg p-1 text-slate-500 hover:bg-white/10 hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      ) : (
        <div className="relative">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={() => setOpen(true)}
            placeholder="Search by name, company, or phone"
            className="w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-violet-500"
          />
          {open && query.trim().length >= 2 && (
            <div className="absolute z-20 mt-1 max-h-56 w-full overflow-auto rounded-xl border border-white/10 bg-slate-900 p-1 shadow-xl">
              {loading && <p className="px-2 py-1 text-xs text-slate-400">Searching...</p>}
              {!loading && items.length === 0 && <p className="px-2 py-1 text-xs text-slate-400">No leads found.</p>}
              {!loading &&
                items.map((lead) => (
                  <button
                    key={lead.id}
                    type="button"
                    className="w-full rounded-lg px-2 py-2 text-left hover:bg-white/10"
                    onClick={() => {
                      onChange(lead);
                      setQuery("");
                      setOpen(false);
                    }}
                  >
                    <p className="text-sm font-medium text-slate-200">{lead.name}</p>
                    <p className="text-xs text-slate-400">
                      #{lead.id} {lead.company_name ? `- ${lead.company_name}` : ""}
                      {lead.normalized_phone ? ` - ${lead.normalized_phone}` : ""}
                    </p>
                  </button>
                ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function SendCsatModal({ token, onClose, onSent }: { token: string; onClose: () => void; onSent: () => void }) {
  const [selectedLead, setSelectedLead] = useState<LeadOption | null>(null);
  const [hours, setHours] = useState("72");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");

  async function handleSend() {
    if (!selectedLead) {
      setError("Lead selection is required");
      return;
    }
    setSending(true);
    setError("");
    try {
      const res = await fetch(`${API_BASE}/feedback/csat/send`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ lead_id: selectedLead.id, expires_hours: Number(hours) || 72 }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || "Failed to queue CSAT");
      }
      onSent();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/70 p-4 backdrop-blur-sm">
      <div className="glass w-full max-w-md space-y-4 rounded-2xl border border-white/20 p-6 shadow-2xl">
        <div className="flex items-center justify-between">
          <h3 className="flex items-center gap-2 font-bold text-slate-900 dark:text-white">
            <Send className="h-4 w-4 text-violet-400" /> Send CSAT Request
          </h3>
          <button onClick={onClose}>
            <X className="h-5 w-5 text-slate-400 hover:text-white" />
          </button>
        </div>
        <p className="text-sm text-slate-500">A CSAT email will be queued and retried in background until sent.</p>
        <LeadSearchSelect token={token} value={selectedLead} onChange={setSelectedLead} required />
        <div className="space-y-1">
          <label className="text-xs font-semibold uppercase text-slate-500">Expires in (hours)</label>
          <select
            value={hours}
            onChange={(e) => setHours(e.target.value)}
            className="w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-violet-500"
          >
            <option value="24">24 hours</option>
            <option value="48">48 hours</option>
            <option value="72">72 hours (3 days)</option>
            <option value="168">7 days</option>
          </select>
        </div>
        {error && <p className="text-xs text-red-400">{error}</p>}
        <div className="flex gap-2">
          <button onClick={onClose} className="flex-1 rounded-xl border border-white/10 py-2 text-sm text-slate-400 hover:text-white">
            Cancel
          </button>
          <button
            onClick={handleSend}
            disabled={sending}
            className="flex-1 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 py-2 text-sm font-semibold text-white disabled:opacity-50"
          >
            {sending ? "Queueing..." : "Queue CSAT"}
          </button>
        </div>
      </div>
    </div>
  );
}

function AddFeedbackModal({ token, onClose, onAdded }: { token: string; onClose: () => void; onAdded: () => void }) {
  const [selectedLead, setSelectedLead] = useState<LeadOption | null>(null);
  const [form, setForm] = useState({
    interaction_id: "",
    feedback_type: "call_review",
    rating: "0",
    comment: "",
    disposition: "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  async function handleSave() {
    setSaving(true);
    setError("");
    try {
      const body: Record<string, unknown> = {
        feedback_type: form.feedback_type,
        comment: form.comment || null,
        disposition: form.disposition || null,
        rating: form.rating && Number(form.rating) > 0 ? Number(form.rating) : null,
        lead_id: selectedLead ? selectedLead.id : null,
        interaction_id: form.interaction_id ? Number(form.interaction_id) : null,
      };
      const res = await fetch(`${API_BASE}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Failed");
      onAdded();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setSaving(false);
    }
  }

  const inputCls =
    "w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-violet-500";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/70 p-4 backdrop-blur-sm">
      <div className="glass w-full max-w-md space-y-4 rounded-2xl border border-white/20 p-6 shadow-2xl">
        <div className="flex items-center justify-between">
          <h3 className="flex items-center gap-2 font-bold text-slate-900 dark:text-white">
            <MessageSquare className="h-4 w-4 text-violet-400" /> Add Feedback
          </h3>
          <button onClick={onClose}>
            <X className="h-5 w-5 text-slate-400 hover:text-white" />
          </button>
        </div>

        <div className="space-y-3">
          <LeadSearchSelect token={token} value={selectedLead} onChange={setSelectedLead} />
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <label className="text-xs font-semibold uppercase text-slate-500">Type</label>
              <select value={form.feedback_type} onChange={set("feedback_type")} className={inputCls}>
                <option value="call_review">Call Review</option>
                <option value="general">General</option>
                <option value="bug_report">Bug Report</option>
                <option value="feature_request">Feature Request</option>
              </select>
            </div>
            <div className="space-y-1">
              <label className="text-xs font-semibold uppercase text-slate-500">Rating (1-5)</label>
              <select value={form.rating} onChange={set("rating")} className={inputCls}>
                <option value="0">- No rating -</option>
                {[1, 2, 3, 4, 5].map((n) => (
                  <option key={n} value={n}>
                    {n}/5
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <label className="text-xs font-semibold uppercase text-slate-500">Interaction ID</label>
              <input type="number" value={form.interaction_id} onChange={set("interaction_id")} className={inputCls} placeholder="optional" />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-semibold uppercase text-slate-500">Disposition</label>
              <select value={form.disposition} onChange={set("disposition")} className={inputCls}>
                <option value="">- None -</option>
                <option value="interested">Interested</option>
                <option value="not_interested">Not Interested</option>
                <option value="callback">Callback</option>
                <option value="voicemail">Voicemail</option>
                <option value="no_answer">No Answer</option>
                <option value="do_not_call">Do Not Call</option>
              </select>
            </div>
          </div>
          <div className="space-y-1">
            <label className="text-xs font-semibold uppercase text-slate-500">Comment</label>
            <textarea value={form.comment} onChange={set("comment")} rows={3} className={`${inputCls} resize-none`} placeholder="Notes about this interaction..." />
          </div>
          {error && <p className="text-xs text-red-400">{error}</p>}
        </div>
        <div className="flex gap-2">
          <button onClick={onClose} className="flex-1 rounded-xl border border-white/10 py-2 text-sm text-slate-400 hover:text-white">
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex-1 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 py-2 text-sm font-semibold text-white disabled:opacity-50"
          >
            {saving ? "Saving..." : "Save Feedback"}
          </button>
        </div>
      </div>
    </div>
  );
}

function CloseLoopEditor({
  token,
  feedback,
  users,
  onSaved,
}: {
  token: string;
  feedback: FeedbackItem;
  users: CompanyUser[];
  onSaved: () => void;
}) {
  const [assigneeUserId, setAssigneeUserId] = useState<string>(feedback.assignee_user_id ? String(feedback.assignee_user_id) : "");
  const [closeLoopStatus, setCloseLoopStatus] = useState<string>(feedback.close_loop_status || "none");
  const [statusNote, setStatusNote] = useState<string>(feedback.status_note || "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function saveCloseLoop(createFollowUpTask: boolean) {
    setSaving(true);
    setError("");
    try {
      const res = await fetch(`${API_BASE}/feedback/${feedback.id}/close-loop`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          assignee_user_id: assigneeUserId ? Number(assigneeUserId) : null,
          close_loop_status: closeLoopStatus,
          status_note: statusNote || null,
          create_follow_up_task: createFollowUpTask,
        }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || "Failed to update close-loop");
      }
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mt-3 space-y-3 rounded-xl border border-amber-500/20 bg-amber-500/5 p-3">
      <p className="text-xs font-semibold uppercase tracking-widest text-amber-400">Low CSAT Close Loop</p>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <div className="space-y-1">
          <label className="text-xs font-semibold uppercase text-slate-500">Assignee</label>
          <select
            value={assigneeUserId}
            onChange={(e) => setAssigneeUserId(e.target.value)}
            className="w-full rounded-lg border border-white/10 bg-white/5 px-2 py-2 text-sm text-slate-200"
          >
            <option value="">Unassigned</option>
            {users.map((u) => (
              <option key={u.id} value={u.id}>
                {(u.first_name || u.last_name) ? `${u.first_name || ""} ${u.last_name || ""}`.trim() : u.email}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1">
          <label className="text-xs font-semibold uppercase text-slate-500">Close-loop status</label>
          <select
            value={closeLoopStatus}
            onChange={(e) => setCloseLoopStatus(e.target.value)}
            className="w-full rounded-lg border border-white/10 bg-white/5 px-2 py-2 text-sm text-slate-200"
          >
            <option value="none">None</option>
            <option value="open">Open</option>
            <option value="in_progress">In progress</option>
            <option value="resolved">Resolved</option>
          </select>
        </div>
        <div className="space-y-1">
          <label className="text-xs font-semibold uppercase text-slate-500">Follow-up task</label>
          <div className="rounded-lg border border-white/10 bg-white/5 px-2 py-2 text-xs text-slate-300">
            {feedback.follow_up_task_id
              ? `#${feedback.follow_up_task_id} (${feedback.follow_up_task_status || "pending"})`
              : "Not created"}
          </div>
        </div>
      </div>
      <div className="space-y-1">
        <label className="text-xs font-semibold uppercase text-slate-500">Status note</label>
        <textarea
          value={statusNote}
          onChange={(e) => setStatusNote(e.target.value)}
          rows={2}
          className="w-full resize-none rounded-lg border border-white/10 bg-white/5 px-2 py-2 text-sm text-slate-200"
          placeholder="Follow-up context and resolution notes"
        />
      </div>
      {error && <p className="text-xs text-red-400">{error}</p>}
      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => void saveCloseLoop(false)}
          disabled={saving}
          className="rounded-lg border border-white/10 px-3 py-1.5 text-xs text-slate-200 hover:bg-white/10 disabled:opacity-50"
        >
          Save
        </button>
        {!feedback.follow_up_task_id && (
          <button
            onClick={() => void saveCloseLoop(true)}
            disabled={saving}
            className="rounded-lg bg-amber-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-amber-500 disabled:opacity-50"
          >
            Create follow-up task
          </button>
        )}
      </div>
    </div>
  );
}

const TABS = ["All", "Call Reviews", "CSAT", "General", "Bug Reports", "Feature Requests"] as const;
type Tab = (typeof TABS)[number];

const TAB_TYPE: Record<Tab, string | undefined> = {
  All: undefined,
  "Call Reviews": "call_review",
  CSAT: "csat",
  General: "general",
  "Bug Reports": "bug_report",
  "Feature Requests": "feature_request",
};

export default function FeedbackPage() {
  const { token, sessionTimeout } = useAuth();
  const router = useRouter();

  const [tab, setTab] = useState<Tab>("All");
  const [summary, setSummary] = useState<Summary | null>(null);
  const [items, setItems] = useState<FeedbackItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [showCsatModal, setShowCsatModal] = useState(false);
  const [showAddModal, setShowAddModal] = useState(false);
  const [deleting, setDeleting] = useState<number | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [users, setUsers] = useState<CompanyUser[]>([]);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    void (async () => {
      const res = await fetch(`${API_BASE}/feedback/summary`, {
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      });
      if (res.status === 401) {
        sessionTimeout();
        return;
      }
      if (!cancelled && res.ok) {
        setSummary(await res.json());
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token, sessionTimeout]);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    void (async () => {
      const res = await fetch(`${API_BASE}/admin/users`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.status === 401) {
        sessionTimeout();
        return;
      }
      if (!cancelled && res.ok) {
        setUsers((await res.json()) as CompanyUser[]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token, sessionTimeout]);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    void (async () => {
      setLoading(true);
      const type = TAB_TYPE[tab];
      const params = new URLSearchParams({ page: String(page), limit: "15" });
      if (type) params.set("feedback_type", type);
      const res = await fetch(`${API_BASE}/feedback?${params}`, {
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      });
      if (res.status === 401) {
        sessionTimeout();
        return;
      }
      if (!cancelled && res.ok) {
        const d = await res.json();
        setItems(d.items);
        setTotal(d.total);
      }
      if (!cancelled) setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [token, tab, page, sessionTimeout]);

  async function refreshData(targetPage: number = page) {
    if (!token) return;

    const [summaryRes, itemsRes] = await Promise.all([
      fetch(`${API_BASE}/feedback/summary`, {
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      }),
      (async () => {
        const type = TAB_TYPE[tab];
        const params = new URLSearchParams({ page: String(targetPage), limit: "15" });
        if (type) params.set("feedback_type", type);
        return fetch(`${API_BASE}/feedback?${params}`, {
          headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        });
      })(),
    ]);

    if (summaryRes.status === 401 || itemsRes.status === 401) {
      sessionTimeout();
      return;
    }
    if (summaryRes.ok) setSummary(await summaryRes.json());
    if (itemsRes.ok) {
      const d = await itemsRes.json();
      setItems(d.items);
      setTotal(d.total);
    }
  }

  async function handleDelete(id: number) {
    if (!confirm("Delete this feedback?")) return;
    setDeleting(id);
    const res = await fetch(`${API_BASE}/feedback/${id}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    });
    if (res.ok) {
      await refreshData(page);
    }
    setDeleting(null);
  }

  return (
    <div className="space-y-6 pb-12">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.2em] text-violet-400">Voice of Customer</p>
          <h1 className="text-4xl font-bold tracking-tight">
            <span className="gradient-text">Feedback</span>
          </h1>
          <p className="mt-1 text-sm font-medium text-slate-500">Call reviews, CSAT scores, and customer sentiment</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowAddModal(true)}
            className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-300 transition-colors hover:text-white"
          >
            <MessageSquare className="h-4 w-4" /> Add Feedback
          </button>
          <button
            onClick={() => setShowCsatModal(true)}
            className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-lg shadow-violet-500/30 transition-all hover:shadow-xl"
          >
            <Send className="h-4 w-4" /> Send CSAT
          </button>
        </div>
      </div>

      {summary && (
        <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
          {[
            { label: "Total Feedback", value: summary.total.toLocaleString(), icon: MessageSquare, color: "#818cf8" },
            {
              label: "Internal Avg",
              value: summary.internal_avg_rating ? `${summary.internal_avg_rating.toFixed(1)} / 5` : "-",
              icon: Star,
              color: "#f59e0b",
            },
            { label: "CSAT Sent", value: summary.csat_sent.toLocaleString(), icon: Send, color: "#60a5fa" },
            { label: "CSAT Response", value: `${summary.csat_response_rate.toFixed(0)}%`, icon: CheckCircle, color: "#34d399" },
            {
              label: "CSAT Avg",
              value: summary.csat_avg_rating ? `${summary.csat_avg_rating.toFixed(1)} / 5` : "-",
              icon: Star,
              color: "#22c55e",
            },
          ].map(({ label, value, icon: Icon, color }) => (
            <div key={label} className="glass rounded-2xl border border-white/10 p-5" style={{ borderLeftColor: color, borderLeftWidth: 3 }}>
              <div className="flex items-start justify-between">
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-500">{label}</p>
                  <p className="mt-2 text-2xl font-bold leading-none" style={{ color }}>
                    {value}
                  </p>
                </div>
                <div className="rounded-xl p-2" style={{ background: `${color}18` }}>
                  <Icon className="h-5 w-5" style={{ color }} />
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {summary && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <Distribution title="Internal Rating Distribution" distribution={summary.internal_rating_distribution} />
          <Distribution title="CSAT Rating Distribution" distribution={summary.csat_rating_distribution} />
          <div className="glass rounded-2xl border border-white/10 p-5">
            <p className="mb-4 text-[10px] font-semibold uppercase tracking-widest text-slate-500">Call Dispositions</p>
            {summary.top_dispositions.length === 0 && <p className="text-xs text-slate-600">No disposition data yet.</p>}
            {summary.top_dispositions.map(({ disposition, count }) => {
              const maxC = summary.top_dispositions[0]?.count || 1;
              const col = DISPOSITION_COLORS[disposition] || "text-slate-400";
              return (
                <div key={disposition} className="mb-3 flex items-center gap-3">
                  <span className={clsx("w-28 flex-shrink-0 text-xs font-semibold capitalize", col)}>{disposition.replace(/_/g, " ")}</span>
                  <div className="h-[5px] flex-1 overflow-hidden rounded-full bg-white/10">
                    <div className="h-full rounded-full bg-violet-500 transition-all duration-700" style={{ width: `${(count / maxC) * 100}%` }} />
                  </div>
                  <span className="w-6 text-right font-mono text-xs text-slate-400">{count}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <div className="flex gap-1 border-b border-white/10">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => {
              setTab(t);
              setPage(1);
            }}
            className={clsx(
              "rounded-t-xl border-b-2 px-5 py-3 text-sm font-semibold transition-all",
              tab === t ? "border-violet-500 bg-violet-500/10 text-violet-400" : "border-transparent text-slate-500 hover:text-white",
            )}
          >
            {t}
          </button>
        ))}
        <button onClick={() => { void refreshData(page); }} className="mb-1 ml-auto rounded-xl px-3 py-1 text-slate-500 transition-colors hover:text-white">
          <RefreshCw className="h-4 w-4" />
        </button>
      </div>

      <div className="glass overflow-hidden rounded-2xl border border-white/10">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-white/10 bg-white/5">
                {["Type", "Lead", "Rating", "Disposition", "Comment", "By", "Status", "Date", ""].map((h) => (
                  <th key={h} className="px-4 py-3 text-[10px] font-bold uppercase tracking-widest text-slate-500">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {loading ? (
                Array.from({ length: 6 }).map((_, i) => (
                  <tr key={i} className="animate-pulse">
                    {Array.from({ length: 9 }).map((__, j) => (
                      <td key={j} className="px-4 py-3">
                        <div className="h-4 rounded bg-white/5" />
                      </td>
                    ))}
                  </tr>
                ))
              ) : items.length === 0 ? (
                <tr>
                  <td colSpan={9} className="px-4 py-16 text-center text-slate-600">
                    No feedback yet.
                  </td>
                </tr>
              ) : (
                items.map((fb) => (
                  <React.Fragment key={fb.id}>
                    <tr className="cursor-pointer transition-colors hover:bg-white/5" onClick={() => setExpandedId(expandedId === fb.id ? null : fb.id)}>
                      <td className="px-4 py-3">
                        <span className={clsx("inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold", TYPE_COLORS[fb.feedback_type] ?? TYPE_COLORS.general)}>
                          {TYPE_LABELS[fb.feedback_type] ?? fb.feedback_type}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        {fb.lead_id ? (
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              router.push(`/leads/${fb.lead_id}`);
                            }}
                            className="font-medium text-violet-400 hover:underline"
                          >
                            {fb.lead_name}
                          </button>
                        ) : (
                          <span className="text-slate-600">-</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <Stars rating={fb.rating} />
                      </td>
                      <td className="px-4 py-3">
                        {fb.disposition ? (
                          <span className={clsx("text-xs font-semibold capitalize", DISPOSITION_COLORS[fb.disposition] || "text-slate-400")}>
                            {fb.disposition.replace(/_/g, " ")}
                          </span>
                        ) : (
                          <span className="text-slate-600">-</span>
                        )}
                      </td>
                      <td className="max-w-[180px] px-4 py-3">
                        <p className="truncate text-xs text-slate-400">{fb.comment || "-"}</p>
                      </td>
                      <td className="px-4 py-3 text-xs text-slate-500">{fb.source === "customer" ? <span className="text-blue-400">Customer</span> : fb.submitted_by_name || "-"}</td>
                      <td className="px-4 py-3">
                        <span className={clsx("inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold", STATUS_COLORS[fb.status] ?? STATUS_COLORS.submitted)}>{fb.status}</span>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-xs text-slate-500">{fmtDate(fb.created_at)}</td>
                      <td className="px-4 py-3 text-right" onClick={(e) => e.stopPropagation()}>
                        <button
                          onClick={() => handleDelete(fb.id)}
                          disabled={deleting === fb.id}
                          className="rounded-lg p-1.5 text-slate-600 transition-colors hover:bg-red-500/10 hover:text-red-400 disabled:opacity-40"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </td>
                    </tr>
                    {expandedId === fb.id && (
                      <tr className="bg-white/3">
                        <td colSpan={9} className="border-b border-white/5 px-6 py-3 text-sm text-slate-300">
                          <div className="space-y-2">
                            <div>
                              <span className="mr-2 text-[10px] uppercase tracking-widest text-slate-500">Comment:</span>
                              {fb.comment || "-"}
                            </div>
                            {fb.feedback_type === "csat" && (fb.rating || 0) <= 2 && (
                              <CloseLoopEditor token={token || ""} feedback={fb} users={users} onSaved={() => { void refreshData(page); }} />
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                ))
              )}
            </tbody>
          </table>
        </div>

        {total > 15 && (
          <div className="flex items-center justify-between border-t border-white/10 px-4 py-3 text-xs text-slate-500">
            <span>{total} total</span>
            <div className="flex gap-1">
              <button
                disabled={page === 1}
                onClick={() => {
                  setPage((p) => p - 1);
                }}
                className="rounded-lg border border-white/10 px-3 py-1 hover:bg-white/5 disabled:opacity-30"
              >
                Prev
              </button>
              <span className="px-3 py-1">
                Page {page} of {Math.ceil(total / 15)}
              </span>
              <button
                disabled={page >= Math.ceil(total / 15)}
                onClick={() => {
                  setPage((p) => p + 1);
                }}
                className="rounded-lg border border-white/10 px-3 py-1 hover:bg-white/5 disabled:opacity-30"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>

      {showCsatModal && token && (
        <SendCsatModal
          token={token}
          onClose={() => setShowCsatModal(false)}
          onSent={() => {
            setPage(1);
            void refreshData(1);
          }}
        />
      )}
      {showAddModal && token && (
        <AddFeedbackModal
          token={token}
          onClose={() => setShowAddModal(false)}
          onAdded={() => {
            setPage(1);
            void refreshData(1);
          }}
        />
      )}
    </div>
  );
}
