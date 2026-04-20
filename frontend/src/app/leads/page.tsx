"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowUpRight, Download, Loader2, Mail, Phone, Plus, Search, Sparkles } from "lucide-react";

import { useAuth } from "@/context/AuthContext";
import ImportLeadsModal from "@/components/leads/ImportLeadsModal";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:6060";

/** Strip system-appended log lines from lead notes before displaying. */
function cleanNotes(notes: string | null | undefined): string {
    if (!notes) return "";
    const cleaned = notes
        .split("\n")
        .filter(line => !/^\[20\d\d-\d\d-\d\dT/.test(line.trim()))
        .join("\n")
        .trim();
    return cleaned;
}

type Lead = {
  id: number;
  name: string;
  normalized_phone: string;
  email?: string | null;
  status: string;
  qualification_status?: string | null;
  next_action?: string | null;
  notes?: string | null;
  source?: string | null;
  created_at?: string;
  city?: string | null;
  state?: string | null;
  lead_score?: number | null;
  lead_score_reasons_json?: { reasons?: string[]; priority?: string } | string[] | null;
  product_interest?: string | null;
  last_outreach_at?: string | null;
};

const emptyLead = {
  name: "",
  normalized_phone: "",
  email: "",
  notes: "",
};

function humanize(value?: string | null) {
  if (!value) return "None";
  return value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function ScoreBadge({ score, reasons }: { score?: number | null; reasons?: string[] }) {
  if (score == null) return null;
  const pct = Math.round(score);
  const color =
    pct >= 70 ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300"
    : pct >= 40 ? "bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300"
    : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400";
  const tooltip = reasons && reasons.length > 0
    ? reasons.map((r) => r.replace(/_/g, " ")).join(" · ")
    : undefined;
  return (
    <span
      title={tooltip}
      className={`rounded-full px-2.5 py-1 text-xs font-semibold cursor-default ${color} ${tooltip ? "underline decoration-dotted underline-offset-2" : ""}`}
    >
      ICP {pct}
    </span>
  );
}

function parseScoreReasons(raw?: { reasons?: string[]; priority?: string } | string[] | null): string[] {
  if (!raw) return [];
  if (Array.isArray(raw)) return raw as string[];
  return Array.isArray(raw.reasons) ? raw.reasons : [];
}

export default function LeadsPage() {
  const { token, sessionTimeout } = useAuth();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [query, setQuery] = useState("");
  const [form, setForm] = useState(emptyLead);
  const [message, setMessage] = useState<string | null>(null);
  const [callInteractionId, setCallInteractionId] = useState<number | null>(null);
  const [callStatus, setCallStatus] = useState<string | null>(null);
  const [showImport, setShowImport] = useState(false);

  const fetchLeads = useCallback(async () => {
    if (!token) {
      setLoading(false);
      return;
    }

    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/crm/leads?page=1&limit=100`, {
        headers: { Authorization: `Bearer ${token}` },
      });

      if (res.status === 401) {
        sessionTimeout();
        return;
      }

      if (!res.ok) {
        throw new Error("Failed to load leads");
      }

      const payload = await res.json();
      setLeads(payload.items || []);
    } catch (error) {
      console.error(error);
      setMessage("Unable to load leads right now.");
    } finally {
      setLoading(false);
    }
  }, [token, sessionTimeout]);

  useEffect(() => {
    fetchLeads();
  }, [fetchLeads]);

  const filteredLeads = useMemo(
    () =>
      leads.filter((lead) => {
        const q = query.toLowerCase();
        return (
          lead.name.toLowerCase().includes(q) ||
          lead.normalized_phone.includes(query) ||
          (lead.email || "").toLowerCase().includes(q)
        );
      }),
    [leads, query]
  );

  async function handleCreateLead(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !form.name || !form.normalized_phone) return;

    setSaving(true);
    setMessage(null);

    try {
      const res = await fetch(`${API_BASE}/crm/leads`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(form),
      });

      if (res.status === 401) {
        sessionTimeout();
        return;
      }

      const payload = await res.json();
      if (!res.ok) {
        throw new Error(payload.detail || "Failed to create lead");
      }

      setForm(emptyLead);
      setMessage(`Lead ${payload.name} created successfully.`);
      fetchLeads();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to create lead.");
    } finally {
      setSaving(false);
    }
  }

  const CALL_STATUS_LABELS: Record<string, string> = {
    initiated:    "Calling...",
    ringing:      "Ringing...",
    "in-progress":"In conversation",
    completed:    "Call completed",
    "no-answer":  "No answer",
    busy:         "Line busy",
    failed:       "Call failed",
    canceled:     "Call canceled",
  };
  const TERMINAL_STATUSES = new Set(["completed", "no-answer", "busy", "failed", "canceled"]);

  useEffect(() => {
    if (!callInteractionId || !token) return;
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/call-status?interaction_id=${callInteractionId}`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) return;
        const data = await res.json();
        const label = CALL_STATUS_LABELS[data.call_status] ?? data.call_status;
        setCallStatus(data.call_status);
        setMessage(msg => {
          // preserve non-call messages
          if (!msg || CALL_STATUS_LABELS[callStatus ?? ""] || msg.startsWith("Calling")) return label;
          return msg;
        });
        if (data.is_terminal) {
          clearInterval(interval);
          setTimeout(() => { setCallInteractionId(null); setCallStatus(null); }, 4000);
        }
      } catch {  }
    }, 2000);
    return () => clearInterval(interval);
  }, [callInteractionId, token]);

  async function handleCall(lead: Lead) {
    if (!token) return;
    setCallInteractionId(null);
    setCallStatus(null);

    try {
      const res = await fetch(
        `${API_BASE}/make-call?to=${encodeURIComponent(lead.normalized_phone)}&lead_id=${lead.id}`,
        {
          method: "POST",
          headers: { Authorization: `Bearer ${token}` },
        }
      );

      if (res.status === 401) {
        sessionTimeout();
        return;
      }

      if (!res.ok) throw new Error("Call could not be started");
      const data = await res.json();
      setMessage(`Calling ${lead.name} at ${lead.normalized_phone}...`);
      if (data.interaction_id) setCallInteractionId(data.interaction_id);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to start the call.");
    }
  }

  return (
    <div className="space-y-6 pb-8">
      {showImport && token && (
        <ImportLeadsModal
          token={token}
          onClose={() => setShowImport(false)}
          onImported={() => { fetchLeads(); setShowImport(false); }}
        />
      )}

      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.2em] text-violet-600 dark:text-violet-300">Pipeline workspace</p>
          <h1 className="text-4xl font-bold tracking-tight text-slate-900 dark:text-white">
            <span className="gradient-text">Leads</span>
          </h1>
          <p className="mt-2 text-slate-600 dark:text-slate-400">
            Search, call, and manage your lead pipeline.
          </p>
        </div>
        <button
          onClick={() => setShowImport(true)}
          className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-5 py-2.5 font-semibold text-white shadow-lg shadow-violet-500/20 transition hover:scale-[1.02]"
        >
          <Download className="h-4 w-4" />
          Import Leads
        </button>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <form onSubmit={handleCreateLead} className="rounded-2xl glass border border-white/40 p-6 shadow-sm dark:border-white/10 xl:col-span-1">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className="rounded-xl bg-violet-100 p-3 text-violet-700 dark:bg-violet-500/10 dark:text-violet-300">
                <Plus className="h-5 w-5" />
              </div>
              <div>
                <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Quick capture</h2>
                <p className="text-sm text-slate-500 dark:text-slate-400">Single lead, fast.</p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => setShowImport(true)}
              className="text-xs font-medium text-violet-600 hover:underline dark:text-violet-400"
            >
              Bulk import →
            </button>
          </div>

          <div className="space-y-4">
            <input
              value={form.name}
              onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
              placeholder="Lead name"
              className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm outline-none ring-0 transition focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
            />
            <input
              value={form.normalized_phone}
              onChange={(event) => setForm((current) => ({ ...current, normalized_phone: event.target.value }))}
              placeholder="Phone number"
              className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm outline-none transition focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
            />
            <input
              value={form.email}
              onChange={(event) => setForm((current) => ({ ...current, email: event.target.value }))}
              placeholder="Email (optional)"
              className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm outline-none transition focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
            />
            <textarea
              value={form.notes}
              onChange={(event) => setForm((current) => ({ ...current, notes: event.target.value }))}
              placeholder="Notes or campaign context"
              rows={4}
              className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm outline-none transition focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
            />
            <button
              type="submit"
              disabled={saving}
              className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-3 font-semibold text-white shadow-lg shadow-violet-500/20 transition hover:scale-[1.01] disabled:opacity-60"
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              Create lead
            </button>
          </div>
        </form>

        <div className="rounded-2xl glass border border-white/40 p-6 dark:border-white/10 xl:col-span-2">
          <div className="mb-5 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Lead pipeline</h2>
              <p className="text-sm text-slate-500 dark:text-slate-400">Search, call, and open the new Lead 360 page.</p>
            </div>
            <div className="relative w-full md:max-w-xs">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search leads"
                className="w-full rounded-xl border border-slate-200 bg-white py-2.5 pl-9 pr-3 text-sm outline-none transition focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
              />
            </div>
          </div>

          {message && (
            <div className={`mb-4 rounded-xl border px-4 py-3 text-sm flex items-center gap-2 ${
              callStatus === "completed" ? "border-green-200 bg-green-50 text-green-700 dark:border-green-500/20 dark:bg-green-500/10 dark:text-green-300"
              : callStatus === "no-answer" || callStatus === "busy" || callStatus === "failed" ? "border-red-200 bg-red-50 text-red-700 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-300"
              : callStatus === "in-progress" ? "border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-500/20 dark:bg-blue-500/10 dark:text-blue-300"
              : "border-violet-200 bg-violet-50 text-violet-700 dark:border-violet-500/20 dark:bg-violet-500/10 dark:text-violet-200"
            }`}>
              {callInteractionId && !TERMINAL_STATUSES.has(callStatus ?? "") && (
                <span className="inline-block h-2 w-2 rounded-full bg-current animate-pulse flex-shrink-0" />
              )}
              {message}
            </div>
          )}

          <div className="space-y-3">
            {loading ? (
              <div className="flex items-center justify-center py-12 text-slate-500 dark:text-slate-400">
                <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading leads...
              </div>
            ) : filteredLeads.length === 0 ? (
              <div className="rounded-xl border border-dashed border-slate-300 px-6 py-12 text-center text-slate-500 dark:border-white/10 dark:text-slate-400">
                No leads matched your search yet.
              </div>
            ) : (
              filteredLeads.map((lead) => (
                <div key={lead.id} className="rounded-2xl border border-slate-200 bg-white/80 p-4 transition hover:shadow-md dark:border-white/10 dark:bg-slate-900/40">
                  <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                    <div className="space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="text-lg font-semibold text-slate-900 dark:text-white">{lead.name}</h3>
                        <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-200">
                          {humanize(lead.status)}
                        </span>
                        {lead.qualification_status && (
                          <span className="rounded-full bg-violet-100 px-2.5 py-1 text-xs font-medium text-violet-700 dark:bg-violet-500/10 dark:text-violet-200">
                            {humanize(lead.qualification_status)}
                          </span>
                        )}
                        <ScoreBadge score={lead.lead_score} reasons={parseScoreReasons(lead.lead_score_reasons_json)} />
                      </div>

                      <div className="flex flex-wrap items-center gap-4 text-sm text-slate-600 dark:text-slate-300">
                        <span className="inline-flex items-center gap-1"><Phone className="h-4 w-4" /> {lead.normalized_phone}</span>
                        {lead.email && <span className="inline-flex items-center gap-1"><Mail className="h-4 w-4" /> {lead.email}</span>}
                        <span className="inline-flex items-center gap-1"><Sparkles className="h-4 w-4" /> {humanize(lead.next_action || "none")}</span>
                      </div>

                      {cleanNotes(lead.notes) && (
                        <p className="text-sm text-slate-500 dark:text-slate-400 line-clamp-2">
                          {cleanNotes(lead.notes)}
                        </p>
                      )}
                    </div>

                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => handleCall(lead)}
                        className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white"
                      >
                        <Phone className="h-4 w-4" /> Call now
                      </button>
                      <Link
                        href={`/leads/${lead.id}`}
                        className="inline-flex items-center gap-2 rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-700 transition hover:border-violet-300 hover:text-violet-700 dark:border-white/10 dark:text-slate-200"
                      >
                        Open Lead 360 <ArrowUpRight className="h-4 w-4" />
                      </Link>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}