"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  BarChart2, ChevronDown, ChevronUp, GripVertical, List, Loader2,
  Mail, MessageCircle, Pause, Pencil, Phone, Play, Plus, Trash2, Users, X } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

import { apiFetch } from "@/utils/apiFetch";
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:6060";

// Types

type Campaign = {
  id: number;
  name: string;
  description?: string | null;
  status: string;
  created_at?: string;
};

type CampaignStep = {
  id: number;
  step_order: number;
  channel: string;
  template_id?: number | null;
  delay_hours: number;
  objective?: string | null;
};

type Lead = { id: number; name: string; normalized_phone: string };
type RecipientRow = {
  id: number; lead_id: number; status: string;
  current_step: number; next_run_at?: string | null; last_contact_at?: string | null;
};

// Helpers

function humanize(v?: string | null) {
  if (!v) return "—";
  return v.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function delayLabel(hours: number) {
  if (hours === 0) return "Immediately";
  if (hours < 24) return `Wait ${hours}h`;
  const days = Math.floor(hours / 24);
  const rem = hours % 24;
  return rem > 0 ? `Wait ${days}d ${rem}h` : `Wait ${days}d`;
}

const CHANNEL_META: Record<string, { label: string; Icon: React.ElementType; color: string }> = {
  call:      { label: "Call",      Icon: Phone,         color: "text-emerald-600 dark:text-emerald-400" },
  email:     { label: "Email",     Icon: Mail,          color: "text-blue-600 dark:text-blue-400" },
  whatsapp:  { label: "WhatsApp",  Icon: MessageCircle, color: "text-green-600 dark:text-green-400" } };

function ChannelIcon({ channel }: { channel: string }) {
  const meta = CHANNEL_META[channel] ?? { Icon: Phone, color: "text-slate-500" };
  return <meta.Icon className={`h-4 w-4 ${meta.color}`} />;
}

// Sequence Builder

interface SequenceBuilderProps {
  campaignId: number;
  steps: CampaignStep[];
  loading: boolean;
  onRefresh: () => void;
}

function SequenceBuilder({ campaignId, steps, loading, onRefresh }: SequenceBuilderProps) {
  const headers = {"Content-Type": "application/json" };

  // Drag state
  const dragSrcIdx = useRef<number | null>(null);
  const [dropTargetIdx, setDropTargetIdx] = useState<number | null>(null);

  // Inline edit state
  const [editId, setEditId] = useState<number | null>(null);
  const [editChannel, setEditChannel] = useState("call");
  const [editDelay, setEditDelay] = useState(0);
  const [editSaving, setEditSaving] = useState(false);

  // Add step state
  const [addSaving, setAddSaving] = useState<string | null>(null); // channel being added
  const [stepMsg, setStepMsg] = useState<string | null>(null);

  // AI sequence-suggest state
  const [suggestOpen, setSuggestOpen] = useState(false);
  const [suggestSegment, setSuggestSegment] = useState("");
  const [suggesting, setSuggesting] = useState(false);
  const [suggestResult, setSuggestResult] = useState<Array<{ channel: string; delay_hours: number; rationale: string }>>([]);
  const [suggestErr, setSuggestErr] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);

  async function runSuggest() {
    if (!suggestSegment.trim()) return;
    setSuggesting(true);
    setSuggestErr(null);
    setSuggestResult([]);
    try {
      const res = await apiFetch(`${API_BASE}/campaigns/${campaignId}/suggest-sequence`, {
        method: "POST",
        headers,
        body: JSON.stringify({ segment: suggestSegment.trim() }),
      });
      if (!res.ok) throw new Error((await res.json()).detail || `HTTP ${res.status}`);
      const data = await res.json();
      setSuggestResult(data.suggestion || []);
    } catch (e) {
      setSuggestErr(e instanceof Error ? e.message : "Suggest failed");
    } finally {
      setSuggesting(false);
    }
  }

  async function applySuggestion() {
    if (suggestResult.length === 0) return;
    setApplying(true);
    try {
      const startOrder = steps.length + 1;
      for (let i = 0; i < suggestResult.length; i++) {
        const s = suggestResult[i];
        const res = await apiFetch(`${API_BASE}/campaigns/${campaignId}/steps`, {
          method: "POST",
          headers,
          body: JSON.stringify({
            channel: s.channel,
            delay_hours: s.delay_hours,
            step_order: startOrder + i,
          }),
        });
        if (!res.ok) throw new Error(`Step ${i + 1} failed`);
      }
      setSuggestResult([]);
      setSuggestSegment("");
      setSuggestOpen(false);
      onRefresh();
    } catch (e) {
      setSuggestErr(e instanceof Error ? e.message : "Apply failed");
    } finally {
      setApplying(false);
    }
  }

  function openEdit(step: CampaignStep) {
    setEditId(step.id);
    setEditChannel(step.channel);
    setEditDelay(step.delay_hours);
  }

  async function handleDelete(stepId: number) {
    if (!confirm("Delete this step?")) return;
    const res = await apiFetch(`${API_BASE}/campaigns/${campaignId}/steps/${stepId}`, {
      method: "DELETE",
      headers });
    if (res.ok || res.status === 204) { onRefresh(); }
    else { setStepMsg("Delete failed"); }
  }

  async function handleSaveEdit() {
    if (editId == null) return;
    setEditSaving(true);
    try {
      const res = await apiFetch(`${API_BASE}/campaigns/${campaignId}/steps/${editId}`, {
        method: "PATCH",
        headers,
        body: JSON.stringify({ channel: editChannel, delay_hours: editDelay }) });
      if (!res.ok) throw new Error((await res.json()).detail || "Save failed");
      setEditId(null);
      onRefresh();
    } catch (e) {
      setStepMsg(e instanceof Error ? e.message : "Save failed");
    } finally {
      setEditSaving(false);
    }
  }

  async function handleAddStep(channel: string) {
    setAddSaving(channel);
    try {
      const nextOrder = steps.length + 1;
      const res = await apiFetch(`${API_BASE}/campaigns/${campaignId}/steps`, {
        method: "POST",
        headers,
        body: JSON.stringify({ channel, delay_hours: 24, step_order: nextOrder }) });
      if (!res.ok) throw new Error((await res.json()).detail || "Add failed");
      onRefresh();
    } catch (e) {
      setStepMsg(e instanceof Error ? e.message : "Add failed");
    } finally {
      setAddSaving(null);
    }
  }


  function onDragStart(idx: number) {
    dragSrcIdx.current = idx;
  }

  function onDragOver(e: React.DragEvent, idx: number) {
    e.preventDefault();
    setDropTargetIdx(idx);
  }

  function onDragLeave() {
    setDropTargetIdx(null);
  }

  async function onDrop(e: React.DragEvent, targetIdx: number) {
    e.preventDefault();
    setDropTargetIdx(null);
    const srcIdx = dragSrcIdx.current;
    dragSrcIdx.current = null;
    if (srcIdx == null || srcIdx === targetIdx) return;

    // Compute new order
    const reordered = [...steps];
    const [moved] = reordered.splice(srcIdx, 1);
    reordered.splice(targetIdx, 0, moved);
    const step_ids = reordered.map((s) => s.id);

    const res = await apiFetch(`${API_BASE}/campaigns/${campaignId}/steps/reorder`, {
      method: "PUT",
      headers,
      body: JSON.stringify({ step_ids }) });
    if (res.ok) { onRefresh(); }
    else { setStepMsg("Reorder failed"); }
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-slate-500 py-2">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading steps…
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {stepMsg && (
        <p className="text-xs text-red-500">{stepMsg}</p>
      )}

      {/* Step cards */}
      {steps.length === 0 && (
        <p className="text-sm text-slate-500 dark:text-slate-400">No steps yet. Add one below.</p>
      )}

      <div className="space-y-1.5">
        {steps.map((step, idx) => {
          const meta = CHANNEL_META[step.channel] ?? { label: step.channel, color: "text-slate-500" };
          const isEditing = editId === step.id;
          const isDragTarget = dropTargetIdx === idx;

          return (
            <div
              key={step.id}
              draggable
              onDragStart={() => onDragStart(idx)}
              onDragOver={(e) => onDragOver(e, idx)}
              onDragLeave={onDragLeave}
              onDrop={(e) => onDrop(e, idx)}
              className={`group flex items-center gap-3 rounded-xl border bg-white px-3 py-2.5 transition-all dark:bg-slate-900/40
                ${isDragTarget
                  ? "border-violet-400 shadow-md shadow-violet-200/40 dark:border-violet-500 dark:shadow-violet-500/20"
                  : "border-slate-200 dark:border-white/10"
                }`}
            >
              {/* Drag handle */}
              <GripVertical className="h-4 w-4 flex-shrink-0 cursor-grab text-slate-300 group-hover:text-slate-400 active:cursor-grabbing dark:text-slate-600 dark:group-hover:text-slate-500" />

              {/* Step number */}
              <span className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-violet-100 text-xs font-bold text-violet-700 dark:bg-violet-500/10 dark:text-violet-300">
                {step.step_order}
              </span>

              {isEditing ? (
                /* Inline edit row */
                <>
                  <select
                    value={editChannel}
                    onChange={(e) => setEditChannel(e.target.value)}
                    className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-sm dark:border-white/10 dark:bg-slate-800"
                  >
                    {Object.entries(CHANNEL_META).map(([key, m]) => (
                      <option key={key} value={key}>{m.label}</option>
                    ))}
                  </select>
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs text-slate-400">Wait</span>
                    <input
                      type="number"
                      value={editDelay}
                      min={0}
                      onChange={(e) => setEditDelay(Number(e.target.value))}
                      className="w-16 rounded-lg border border-slate-200 bg-white px-2 py-1 text-sm dark:border-white/10 dark:bg-slate-800"
                    />
                    <span className="text-xs text-slate-400">h</span>
                  </div>
                  <div className="ml-auto flex items-center gap-1.5">
                    <button
                      onClick={handleSaveEdit}
                      disabled={editSaving}
                      className="rounded-lg bg-violet-600 px-2.5 py-1 text-xs font-semibold text-white disabled:opacity-60"
                    >
                      {editSaving ? <Loader2 className="h-3 w-3 animate-spin" /> : "Save"}
                    </button>
                    <button
                      onClick={() => setEditId(null)}
                      className="rounded-lg border border-slate-200 px-2.5 py-1 text-xs text-slate-500 dark:border-white/10"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </div>
                </>
              ) : (
                /* Display row */
                <>
                  <ChannelIcon channel={step.channel} />
                  <span className={`font-medium text-sm ${meta.color}`}>{meta.label}</span>
                  <span className="text-xs text-slate-400 dark:text-slate-500">·</span>
                  <span className="text-xs text-slate-500 dark:text-slate-400">{delayLabel(step.delay_hours)}</span>
                  <div className="ml-auto flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                    <button
                      onClick={() => openEdit(step)}
                      title="Edit step"
                      className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-700 dark:hover:text-slate-200"
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                    <button
                      onClick={() => handleDelete(step.id)}
                      title="Delete step"
                      className="rounded-lg p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-900/20 dark:hover:text-red-400"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </>
              )}
            </div>
          );
        })}
      </div>

      {/* Add step buttons */}
      <div className="flex flex-wrap items-center gap-2 pt-1">
        <span className="text-xs text-slate-400">Add step:</span>
        {Object.entries(CHANNEL_META).map(([key, meta]) => (
          <button
            key={key}
            onClick={() => handleAddStep(key)}
            disabled={addSaving === key}
            className="inline-flex items-center gap-1.5 rounded-lg border border-dashed border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:border-violet-400 hover:text-violet-700 disabled:opacity-60 dark:border-white/10 dark:text-slate-400 dark:hover:border-violet-400 dark:hover:text-violet-300"
          >
            {addSaving === key ? <Loader2 className="h-3 w-3 animate-spin" /> : <Plus className="h-3 w-3" />}
            {meta.label}
          </button>
        ))}
        <button
          onClick={() => setSuggestOpen((v) => !v)}
          className="ml-auto inline-flex items-center gap-1.5 rounded-lg border border-violet-300 bg-violet-50 px-3 py-1.5 text-xs font-semibold text-violet-700 transition hover:bg-violet-100 dark:border-violet-500/30 dark:bg-violet-500/10 dark:text-violet-300 dark:hover:bg-violet-500/15"
        >
          ✨ AI suggest sequence
        </button>
      </div>

      {/* AI sequence-suggest panel */}
      {suggestOpen && (
        <div className="mt-2 rounded-xl border border-violet-200 bg-gradient-to-br from-violet-50 to-blue-50 p-4 dark:border-violet-500/20 dark:from-violet-500/5 dark:to-blue-500/5 space-y-3">
          <div>
            <p className="text-[11px] font-bold uppercase tracking-widest text-violet-700 dark:text-violet-300">
              Describe the lead segment
            </p>
            <p className="mt-0.5 text-[11px] text-slate-500 dark:text-slate-400">
              e.g. &ldquo;mid-market manufacturers in IN who downloaded our pricing PDF&rdquo;
            </p>
          </div>
          <div className="flex gap-2">
            <input
              value={suggestSegment}
              onChange={(e) => setSuggestSegment(e.target.value)}
              placeholder="enterprise SaaS leads who replied to a competitor mention..."
              className="flex-1 rounded-lg border border-violet-200 bg-white px-3 py-2 text-xs outline-none focus:border-violet-400 dark:border-violet-500/30 dark:bg-slate-900/40"
            />
            <button
              onClick={runSuggest}
              disabled={suggesting || !suggestSegment.trim()}
              className="inline-flex items-center gap-1.5 rounded-lg bg-gradient-to-r from-violet-600 to-blue-600 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50"
            >
              {suggesting ? <Loader2 className="h-3 w-3 animate-spin" /> : "Suggest"}
            </button>
          </div>
          {suggestErr && <p className="text-[11px] text-amber-600 dark:text-amber-300">{suggestErr}</p>}
          {suggestResult.length > 0 && (
            <>
              <ol className="space-y-1.5">
                {suggestResult.map((s, i) => {
                  const meta = CHANNEL_META[s.channel as keyof typeof CHANNEL_META];
                  return (
                    <li key={i} className="flex items-center gap-2 rounded-lg bg-white/80 px-3 py-2 text-xs dark:bg-slate-900/40">
                      <span className="font-mono text-slate-400">#{i + 1}</span>
                      <span className="font-semibold text-slate-900 dark:text-white">
                        {meta?.label ?? s.channel}
                      </span>
                      <span className="text-slate-500">·</span>
                      <span className="text-slate-600 dark:text-slate-300">
                        wait {s.delay_hours}h
                      </span>
                      <span className="ml-auto truncate text-slate-500 dark:text-slate-400">{s.rationale}</span>
                    </li>
                  );
                })}
              </ol>
              <button
                onClick={applySuggestion}
                disabled={applying}
                className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-2 text-xs font-semibold text-white hover:bg-emerald-700 disabled:opacity-50"
              >
                {applying ? <Loader2 className="h-3 w-3 animate-spin" /> : "✓"}
                Apply ({suggestResult.length} steps)
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}

// Main page

export default function CampaignsPage() {
  const { user, sessionTimeout } = useAuth();

  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [loading, setLoading] = useState(true);
  const [msg, setMsg] = useState<string | null>(null);

  const [expanded, setExpanded] = useState<number | null>(null);
  const [steps, setSteps] = useState<Record<number, CampaignStep[]>>({});
  const [stepsLoading, setStepsLoading] = useState<Record<number, boolean>>({});

  // create campaign form
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [createSaving, setCreateSaving] = useState(false);

  // enroll leads modal
  const [enrollFor, setEnrollFor] = useState<number | null>(null);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [selectedLeads, setSelectedLeads] = useState<number[]>([]);
  const [enrollSaving, setEnrollSaving] = useState(false);

  // action state
  const [actionLoading, setActionLoading] = useState<Record<number, boolean>>({});

  // email reports
  const [emailReports, setEmailReports] = useState<Record<number, {
    emails_sent: number; opens: number; clicks: number; unsubscribes: number;
    open_rate: number; click_rate: number; unsubscribe_rate: number;
  } | null>>({});
  const [reportLoading, setReportLoading] = useState<Record<number, boolean>>({});
  const [showReport, setShowReport] = useState<Record<number, boolean>>({});

  // recipients
  const [recipients, setRecipients] = useState<Record<number, RecipientRow[]>>({});
  const [recipientsLoading, setRecipientsLoading] = useState<Record<number, boolean>>({});
  const [showRecipients, setShowRecipients] = useState<Record<number, boolean>>({});

  const headers = {"Content-Type": "application/json" };

  // Data fetching

  const fetchCampaigns = useCallback(async () => {
    if (!user) return;
    setLoading(true);
    try {
      const res = await apiFetch(`${API_BASE}/campaigns`, { });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) throw new Error("Failed to load campaigns");
      const data = await res.json();
      setCampaigns(Array.isArray(data) ? data : data.items || []);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Could not load campaigns");
    } finally {
      setLoading(false);
    }
  }, [user, sessionTimeout]);

  useEffect(() => { fetchCampaigns(); }, [fetchCampaigns]);

  async function fetchSteps(campaignId: number) {
    setStepsLoading((s) => ({ ...s, [campaignId]: true }));
    try {
      const res = await apiFetch(`${API_BASE}/campaigns/${campaignId}/steps`, { });
      if (!res.ok) return;
      const data = await res.json();
      setSteps((s) => ({ ...s, [campaignId]: data }));
    } finally {
      setStepsLoading((s) => ({ ...s, [campaignId]: false }));
    }
  }

  function toggleExpand(id: number) {
    if (expanded === id) { setExpanded(null); return; }
    setExpanded(id);
    if (!steps[id]) fetchSteps(id);
  }

  async function fetchEmailReport(campaignId: number) {
    if (reportLoading[campaignId]) return;
    setReportLoading((r) => ({ ...r, [campaignId]: true }));
    try {
      const res = await apiFetch(`${API_BASE}/analytics/campaign/${campaignId}/email-report`, { });
      if (res.status === 401) { sessionTimeout(); return; }
      if (res.ok) { const data = await res.json(); setEmailReports((r) => ({ ...r, [campaignId]: data })); }
    } finally {
      setReportLoading((r) => ({ ...r, [campaignId]: false }));
    }
  }

  function toggleReport(id: number) {
    if (!showReport[id] && !emailReports[id]) fetchEmailReport(id);
    setShowReport((r) => ({ ...r, [id]: !r[id] }));
  }

  async function fetchRecipients(campaignId: number) {
    if (recipientsLoading[campaignId]) return;
    setRecipientsLoading((r) => ({ ...r, [campaignId]: true }));
    try {
      const res = await apiFetch(`${API_BASE}/campaigns/${campaignId}/recipients`, { });
      if (res.status === 401) { sessionTimeout(); return; }
      if (res.ok) { const data = await res.json(); setRecipients((r) => ({ ...r, [campaignId]: data })); }
    } finally {
      setRecipientsLoading((r) => ({ ...r, [campaignId]: false }));
    }
  }

  function toggleRecipients(id: number) {
    if (!showRecipients[id] && !recipients[id]) fetchRecipients(id);
    setShowRecipients((r) => ({ ...r, [id]: !r[id] }));
  }

  // Actions

  async function handleCreateCampaign() {
    if (!newName.trim()) return;
    setCreateSaving(true);
    setMsg(null);
    try {
      const res = await apiFetch(`${API_BASE}/campaigns`, {
        method: "POST",
        headers,
        body: JSON.stringify({ name: newName.trim(), description: newDesc.trim() || null }) });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) throw new Error((await res.json()).detail || "Failed to create");
      setNewName(""); setNewDesc(""); setCreating(false);
      setMsg("Campaign created.");
      fetchCampaigns();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Failed to create campaign");
    } finally {
      setCreateSaving(false);
    }
  }

  async function handleLaunch(id: number) {
    setActionLoading((a) => ({ ...a, [id]: true }));
    try {
      const res = await apiFetch(`${API_BASE}/campaigns/${id}/launch`, { method: "POST", headers });
      if (!res.ok) throw new Error((await res.json()).detail || "Failed to launch");
      setMsg("Campaign launched.");
      fetchCampaigns();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Launch failed");
    } finally {
      setActionLoading((a) => ({ ...a, [id]: false }));
    }
  }

  async function handlePause(id: number) {
    setActionLoading((a) => ({ ...a, [id]: true }));
    try {
      const res = await apiFetch(`${API_BASE}/campaigns/${id}/pause`, { method: "POST", headers });
      if (!res.ok) throw new Error((await res.json()).detail || "Failed to pause");
      setMsg("Campaign paused.");
      fetchCampaigns();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Pause failed");
    } finally {
      setActionLoading((a) => ({ ...a, [id]: false }));
    }
  }

  async function openEnroll(campaignId: number) {
    setEnrollFor(campaignId);
    setSelectedLeads([]);
    if (leads.length === 0) {
      const res = await apiFetch(`${API_BASE}/crm/leads?page=1&limit=200`, { });
      if (res.ok) { const d = await res.json(); setLeads(d.items || []); }
    }
  }

  async function handleEnroll() {
    if (!enrollFor || selectedLeads.length === 0) return;
    setEnrollSaving(true);
    try {
      const res = await apiFetch(`${API_BASE}/campaigns/${enrollFor}/enroll`, {
        method: "POST",
        headers,
        body: JSON.stringify({ lead_ids: selectedLeads }) });
      if (!res.ok) throw new Error((await res.json()).detail || "Enroll failed");
      setMsg(`${selectedLeads.length} lead(s) enrolled.`);
      setEnrollFor(null); setSelectedLeads([]);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Enroll failed");
    } finally {
      setEnrollSaving(false);
    }
  }

  // Styles

  const statusColor: Record<string, string> = {
    active:    "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300",
    paused:    "bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300",
    draft:     "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400",
    completed: "bg-blue-100 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300" };
  const recipientStatusColor: Record<string, string> = {
    active:    "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300",
    paused:    "bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300",
    completed: "bg-blue-100 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300",
    pending:   "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400",
    failed:    "bg-red-100 text-red-700 dark:bg-red-500/10 dark:text-red-300" };

  // Render

  return (
    <div className="space-y-6 pb-8">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.2em] text-violet-600 dark:text-violet-300">Automation</p>
          <h1 className="text-4xl font-bold tracking-tight text-slate-900 dark:text-white">
            <span className="gradient-text">Campaigns</span>
          </h1>
          <p className="mt-2 text-slate-600 dark:text-slate-400">Create multi-step outreach sequences and enroll leads.</p>
        </div>
        <button
          onClick={() => setCreating((v) => !v)}
          className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-violet-500/20 transition hover:scale-[1.01]"
        >
          <Plus className="h-4 w-4" /> New campaign
        </button>
      </div>

      {msg && (
        <div className="rounded-xl border border-violet-200 bg-violet-50 px-4 py-3 text-sm text-violet-700 dark:border-violet-500/20 dark:bg-violet-500/10 dark:text-violet-200">
          {msg}
        </div>
      )}

      {/* Create form */}
      {creating && (
        <div className="rounded-2xl glass border border-white/40 p-6 dark:border-white/10 space-y-4">
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white">New campaign</h2>
          <input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="Campaign name"
            className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
          />
          <textarea
            value={newDesc}
            onChange={(e) => setNewDesc(e.target.value)}
            placeholder="Description (optional)"
            rows={2}
            className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
          />
          <div className="flex gap-3">
            <button
              onClick={handleCreateCampaign}
              disabled={createSaving || !newName.trim()}
              className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-60"
            >
              {createSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />} Create
            </button>
            <button onClick={() => setCreating(false)} className="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-600 dark:border-white/10 dark:text-slate-300">
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Campaign list */}
      {loading ? (
        <div className="flex items-center justify-center py-16 text-slate-500">
          <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading…
        </div>
      ) : campaigns.length === 0 ? (
        <div className="rounded-2xl glass border border-dashed border-slate-300 px-6 py-16 text-center text-slate-500 dark:border-white/10">
          No campaigns yet. Create your first one above.
        </div>
      ) : (
        <div className="space-y-4">
          {campaigns.map((campaign) => (
            <div key={campaign.id} className="rounded-2xl glass border border-white/40 dark:border-white/10 overflow-hidden">
              {/* Header row */}
              <div className="flex flex-col gap-4 p-5 lg:flex-row lg:items-center lg:justify-between">
                <div className="space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-lg font-semibold text-slate-900 dark:text-white">{campaign.name}</h3>
                    <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${statusColor[campaign.status] || statusColor.draft}`}>
                      {humanize(campaign.status)}
                    </span>
                  </div>
                  {campaign.description && (
                    <p className="text-sm text-slate-500 dark:text-slate-400">{campaign.description}</p>
                  )}
                </div>

                <div className="flex flex-wrap gap-2">
                  {campaign.status !== "active" ? (
                    <button
                      onClick={() => handleLaunch(campaign.id)}
                      disabled={actionLoading[campaign.id]}
                      className="inline-flex items-center gap-1.5 rounded-xl bg-emerald-600 px-3 py-2 text-sm font-semibold text-white disabled:opacity-60"
                    >
                      {actionLoading[campaign.id] ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />} Launch
                    </button>
                  ) : (
                    <button
                      onClick={() => handlePause(campaign.id)}
                      disabled={actionLoading[campaign.id]}
                      className="inline-flex items-center gap-1.5 rounded-xl bg-amber-500 px-3 py-2 text-sm font-semibold text-white disabled:opacity-60"
                    >
                      {actionLoading[campaign.id] ? <Loader2 className="h-3 w-3 animate-spin" /> : <Pause className="h-3 w-3" />} Pause
                    </button>
                  )}
                  <button
                    onClick={() => openEnroll(campaign.id)}
                    className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-700 hover:border-violet-300 hover:text-violet-700 dark:border-white/10 dark:text-slate-200"
                  >
                    <Users className="h-3 w-3" /> Enroll
                  </button>
                  <button
                    onClick={() => toggleRecipients(campaign.id)}
                    className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-700 hover:border-blue-300 hover:text-blue-700 dark:border-white/10 dark:text-slate-200"
                  >
                    <List className="h-3 w-3" /> Recipients
                  </button>
                  <button
                    onClick={() => toggleReport(campaign.id)}
                    className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-700 hover:border-emerald-300 hover:text-emerald-700 dark:border-white/10 dark:text-slate-200"
                  >
                    <BarChart2 className="h-3 w-3" /> Report
                  </button>
                  <button
                    onClick={() => toggleExpand(campaign.id)}
                    className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-700 dark:border-white/10 dark:text-slate-200"
                  >
                    Sequence {expanded === campaign.id ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                  </button>
                </div>
              </div>

              {/* Sequence Builder panel */}
              {expanded === campaign.id && (
                <div className="border-t border-slate-200 bg-slate-50/50 p-5 dark:border-white/10 dark:bg-slate-900/30">
                  <p className="mb-3 text-xs font-bold uppercase tracking-widest text-slate-400">
                    Sequence — drag to reorder
                  </p>
                  <SequenceBuilder
                    campaignId={campaign.id}
                    steps={steps[campaign.id] || []}
                    loading={!!stepsLoading[campaign.id]}
                    onRefresh={() => fetchSteps(campaign.id)}
                  />
                </div>
              )}

              {/* Recipients panel */}
              {showRecipients[campaign.id] && (
                <div className="border-t border-slate-200 bg-blue-50/30 p-5 dark:border-white/10 dark:bg-blue-900/10">
                  <h4 className="mb-3 text-xs font-bold uppercase tracking-widest text-slate-400">Recipients</h4>
                  {recipientsLoading[campaign.id] ? (
                    <div className="flex items-center gap-2 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> Loading…</div>
                  ) : !recipients[campaign.id] || recipients[campaign.id].length === 0 ? (
                    <p className="text-sm text-slate-500">No recipients enrolled yet.</p>
                  ) : (
                    <div className="overflow-x-auto rounded-xl border border-slate-200 dark:border-white/10">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="bg-slate-50/80 dark:bg-slate-800/50">
                            <th className="px-4 py-2.5 text-left text-xs font-semibold text-slate-500">Lead ID</th>
                            <th className="px-4 py-2.5 text-left text-xs font-semibold text-slate-500">Status</th>
                            <th className="px-4 py-2.5 text-left text-xs font-semibold text-slate-500">Step</th>
                            <th className="px-4 py-2.5 text-left text-xs font-semibold text-slate-500">Next Run</th>
                            <th className="px-4 py-2.5 text-left text-xs font-semibold text-slate-500">Last Contact</th>
                          </tr>
                        </thead>
                        <tbody>
                          {recipients[campaign.id].map((r) => (
                            <tr key={r.id} className="border-t border-slate-100 dark:border-white/5">
                              <td className="px-4 py-2.5 font-mono text-xs text-violet-600 dark:text-violet-400">#{r.lead_id}</td>
                              <td className="px-4 py-2.5">
                                <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${recipientStatusColor[r.status] || recipientStatusColor.pending}`}>
                                  {r.status}
                                </span>
                              </td>
                              <td className="px-4 py-2.5 text-slate-600 dark:text-slate-300">{r.current_step}</td>
                              <td className="px-4 py-2.5 text-xs text-slate-500">{r.next_run_at ? new Date(r.next_run_at).toLocaleString() : "—"}</td>
                              <td className="px-4 py-2.5 text-xs text-slate-500">{r.last_contact_at ? new Date(r.last_contact_at).toLocaleString() : "—"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}

              {/* Email report panel */}
              {showReport[campaign.id] && (
                <div className="border-t border-slate-200 bg-emerald-50/30 p-5 dark:border-white/10 dark:bg-emerald-900/10">
                  <h4 className="mb-3 text-xs font-bold uppercase tracking-widest text-slate-400">Email Report</h4>
                  {reportLoading[campaign.id] ? (
                    <div className="flex items-center gap-2 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> Loading…</div>
                  ) : !emailReports[campaign.id] ? (
                    <p className="text-sm text-slate-500">No report data yet.</p>
                  ) : (
                    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                      {[
                        { label: "Emails Sent", value: emailReports[campaign.id]!.emails_sent, rate: null, color: "text-slate-700 dark:text-slate-200" },
                        { label: "Opens",        value: emailReports[campaign.id]!.opens,        rate: emailReports[campaign.id]!.open_rate,        color: "text-blue-600 dark:text-blue-400" },
                        { label: "Clicks",       value: emailReports[campaign.id]!.clicks,       rate: emailReports[campaign.id]!.click_rate,       color: "text-violet-600 dark:text-violet-400" },
                        { label: "Unsubscribes", value: emailReports[campaign.id]!.unsubscribes, rate: emailReports[campaign.id]!.unsubscribe_rate, color: "text-red-600 dark:text-red-400" },
                      ].map((stat) => (
                        <div key={stat.label} className="rounded-xl border border-slate-200 bg-white p-3 dark:border-white/10 dark:bg-slate-900/40">
                          <p className="text-xs text-slate-500">{stat.label}</p>
                          <p className={`text-2xl font-bold ${stat.color}`}>{stat.value}</p>
                          {stat.rate !== null && <p className="text-xs text-slate-400">{stat.rate}%</p>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Enroll leads modal */}
      {enrollFor !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 p-6 shadow-2xl space-y-4">
            <h3 className="text-lg font-bold text-slate-900 dark:text-white">Enroll leads</h3>
            <p className="text-sm text-slate-500 dark:text-slate-400">Select leads to enroll in this campaign.</p>
            <div className="max-h-64 overflow-y-auto space-y-2 rounded-xl border border-slate-200 p-2 dark:border-white/10">
              {leads.map((lead) => (
                <label key={lead.id} className="flex items-center gap-3 rounded-lg p-2 hover:bg-slate-50 dark:hover:bg-slate-800 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={selectedLeads.includes(lead.id)}
                    onChange={(e) =>
                      setSelectedLeads((s) => e.target.checked ? [...s, lead.id] : s.filter((id) => id !== lead.id))
                    }
                    className="h-4 w-4 rounded border-slate-300 text-violet-600"
                  />
                  <span className="text-sm text-slate-800 dark:text-slate-100">{lead.name}</span>
                  <span className="text-xs text-slate-400">{lead.normalized_phone}</span>
                </label>
              ))}
            </div>
            <div className="flex gap-3">
              <button
                onClick={handleEnroll}
                disabled={enrollSaving || selectedLeads.length === 0}
                className="inline-flex items-center gap-2 rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-60"
              >
                {enrollSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                Enroll {selectedLeads.length > 0 ? `(${selectedLeads.length})` : ""}
              </button>
              <button
                onClick={() => setEnrollFor(null)}
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
