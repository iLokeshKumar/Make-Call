"use client";

import { useCallback, useEffect, useState } from "react";
import { BarChart2, ChevronDown, ChevronUp, List, Loader2, Play, Pause, Plus, Users } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:6060";

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
  message_body?: string | null;
};

type Lead = { id: number; name: string; normalized_phone: string };

function humanize(v?: string | null) {
  if (!v) return "—";
  return v.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export default function CampaignsPage() {
  const { token, sessionTimeout } = useAuth();

  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [loading, setLoading] = useState(true);
  const [msg, setMsg] = useState<string | null>(null);

  // expanded campaign state
  const [expanded, setExpanded] = useState<number | null>(null);
  const [steps, setSteps] = useState<Record<number, CampaignStep[]>>({});
  const [stepsLoading, setStepsLoading] = useState<Record<number, boolean>>({});

  // create campaign form
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [createSaving, setCreateSaving] = useState(false);

  // add step form (per campaign)
  const [addingStepFor, setAddingStepFor] = useState<number | null>(null);
  const [stepChannel, setStepChannel] = useState("call");
  const [stepBody, setStepBody] = useState("");
  const [stepDelay, setStepDelay] = useState(24);
  const [stepSaving, setStepSaving] = useState(false);

  // enroll leads modal
  const [enrollFor, setEnrollFor] = useState<number | null>(null);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [selectedLeads, setSelectedLeads] = useState<number[]>([]);
  const [enrollSaving, setEnrollSaving] = useState(false);

  // action state
  const [actionLoading, setActionLoading] = useState<Record<number, boolean>>({});

  // email reports
  const [emailReports, setEmailReports] = useState<Record<number, { emails_sent: number; opens: number; clicks: number; unsubscribes: number; open_rate: number; click_rate: number; unsubscribe_rate: number } | null>>({});
  const [reportLoading, setReportLoading] = useState<Record<number, boolean>>({});
  const [showReport, setShowReport] = useState<Record<number, boolean>>({});

  // recipients
  type RecipientRow = { id: number; lead_id: number; status: string; current_step: number; next_run_at?: string | null; last_contact_at?: string | null; };
  const [recipients, setRecipients] = useState<Record<number, RecipientRow[]>>({});
  const [recipientsLoading, setRecipientsLoading] = useState<Record<number, boolean>>({});
  const [showRecipients, setShowRecipients] = useState<Record<number, boolean>>({});

  async function fetchEmailReport(campaignId: number) {
    if (reportLoading[campaignId]) return;
    setReportLoading((r) => ({ ...r, [campaignId]: true }));
    try {
      const res = await fetch(`${API_BASE}/analytics/campaign/${campaignId}/email-report`, { headers: { Authorization: `Bearer ${token}` } });
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
      const res = await fetch(`${API_BASE}/campaigns/${campaignId}/recipients`, { headers: { Authorization: `Bearer ${token}` } });
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

  const recipientStatusColor: Record<string, string> = {
    active: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300",
    paused: "bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300",
    completed: "bg-blue-100 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300",
    pending: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400",
    failed: "bg-red-100 text-red-700 dark:bg-red-500/10 dark:text-red-300",
  };

  const headers = { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };

  const fetchCampaigns = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/campaigns`, { headers: { Authorization: `Bearer ${token}` } });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) throw new Error("Failed to load campaigns");
      const data = await res.json();
      setCampaigns(Array.isArray(data) ? data : data.items || []);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Could not load campaigns");
    } finally {
      setLoading(false);
    }
  }, [token, sessionTimeout]);

  useEffect(() => { fetchCampaigns(); }, [fetchCampaigns]);

  async function fetchSteps(campaignId: number) {
    setStepsLoading((s) => ({ ...s, [campaignId]: true }));
    try {
      const res = await fetch(`${API_BASE}/campaigns/${campaignId}/steps`, { headers: { Authorization: `Bearer ${token}` } });
      if (!res.ok) return;
      const data = await res.json(); setSteps((s) => ({ ...s, [campaignId]: data }));
    } finally {
      setStepsLoading((s) => ({ ...s, [campaignId]: false }));
    }
  }

  function toggleExpand(id: number) {
    if (expanded === id) { setExpanded(null); return; }
    setExpanded(id);
    if (!steps[id]) fetchSteps(id);
  }

  async function handleCreateCampaign() {
    if (!newName.trim()) return;
    setCreateSaving(true);
    setMsg(null);
    try {
      const res = await fetch(`${API_BASE}/campaigns`, {
        method: "POST",
        headers,
        body: JSON.stringify({ name: newName.trim(), description: newDesc.trim() || null }),
      });
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

  async function handleAddStep(campaignId: number) {
    setStepSaving(true);
    try {
      const res = await fetch(`${API_BASE}/campaigns/${campaignId}/steps`, {
        method: "POST",
        headers,
        body: JSON.stringify({ channel: stepChannel, message_body: stepBody.trim() || null, delay_hours: stepDelay }),
      });
      if (!res.ok) throw new Error((await res.json()).detail || "Failed to add step");
      setAddingStepFor(null); setStepChannel("call"); setStepBody(""); setStepDelay(24);
      fetchSteps(campaignId);
      setMsg("Step added.");
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Failed to add step");
    } finally {
      setStepSaving(false);
    }
  }

  async function handleLaunch(id: number) {
    setActionLoading((a) => ({ ...a, [id]: true }));
    try {
      const res = await fetch(`${API_BASE}/campaigns/${id}/launch`, { method: "POST", headers });
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
      const res = await fetch(`${API_BASE}/campaigns/${id}/pause`, { method: "POST", headers });
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
      const res = await fetch(`${API_BASE}/crm/leads?page=1&limit=200`, { headers: { Authorization: `Bearer ${token}` } });
      if (res.ok) { const d = await res.json(); setLeads(d.items || []); }
    }
  }

  async function handleEnroll() {
    if (!enrollFor || selectedLeads.length === 0) return;
    setEnrollSaving(true);
    try {
      const res = await fetch(`${API_BASE}/campaigns/${enrollFor}/enroll`, {
        method: "POST",
        headers,
        body: JSON.stringify({ lead_ids: selectedLeads }),
      });
      if (!res.ok) throw new Error((await res.json()).detail || "Enroll failed");
      setMsg(`${selectedLeads.length} lead(s) enrolled.`);
      setEnrollFor(null); setSelectedLeads([]);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Enroll failed");
    } finally {
      setEnrollSaving(false);
    }
  }

  const statusColor: Record<string, string> = {
    active: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300",
    paused: "bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300",
    draft: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400",
    completed: "bg-blue-100 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300",
  };

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
        <div className="flex items-center justify-center py-16 text-slate-500"><Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading...</div>
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
                  {campaign.description && <p className="text-sm text-slate-500 dark:text-slate-400">{campaign.description}</p>}
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
                    Steps {expanded === campaign.id ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                  </button>
                </div>
              </div>

              {/* Steps panel */}
              {expanded === campaign.id && (
                <div className="border-t border-slate-200 bg-slate-50/50 p-5 dark:border-white/10 dark:bg-slate-900/30 space-y-4">
                  {stepsLoading[campaign.id] ? (
                    <div className="flex items-center gap-2 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> Loading steps...</div>
                  ) : (steps[campaign.id] || []).length === 0 ? (
                    <p className="text-sm text-slate-500">No steps yet. Add one below.</p>
                  ) : (
                    <div className="space-y-2">
                      {(steps[campaign.id] || []).map((step) => (
                        <div key={step.id} className="flex items-center gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 dark:border-white/10 dark:bg-slate-900/40">
                          <span className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-violet-100 text-xs font-bold text-violet-700 dark:bg-violet-500/10 dark:text-violet-300">
                            {step.step_order}
                          </span>
                          <div className="flex-1 min-w-0">
                            <span className="font-medium text-slate-800 dark:text-slate-100 capitalize">{step.channel}</span>
                            {step.message_body && <span className="ml-2 text-sm text-slate-500 dark:text-slate-400 truncate">— {step.message_body}</span>}
                          </div>
                          <span className="text-xs text-slate-400 whitespace-nowrap">+{step.delay_hours}h delay</span>
                        </div>
                      ))}
                    </div>
                  )}

                  {addingStepFor === campaign.id ? (
                    <div className="space-y-3 rounded-xl border border-violet-200 bg-violet-50/60 p-4 dark:border-violet-500/20 dark:bg-violet-500/5">
                      <h4 className="text-sm font-semibold text-slate-800 dark:text-slate-100">Add step</h4>
                      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                        <select
                          value={stepChannel}
                          onChange={(e) => setStepChannel(e.target.value)}
                          className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
                        >
                          <option value="call">Call</option>
                          <option value="whatsapp">WhatsApp</option>
                          <option value="email">Email</option>
                        </select>
                        <input
                          type="number"
                          value={stepDelay}
                          onChange={(e) => setStepDelay(Number(e.target.value))}
                          placeholder="Delay (hours)"
                          min={0}
                          className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
                        />
                        <input
                          value={stepBody}
                          onChange={(e) => setStepBody(e.target.value)}
                          placeholder="Message (optional)"
                          className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
                        />
                      </div>
                      <div className="flex gap-2">
                        <button
                          onClick={() => handleAddStep(campaign.id)}
                          disabled={stepSaving}
                          className="inline-flex items-center gap-2 rounded-xl bg-violet-600 px-3 py-2 text-sm font-semibold text-white disabled:opacity-60"
                        >
                          {stepSaving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Plus className="h-3 w-3" />} Save step
                        </button>
                        <button onClick={() => setAddingStepFor(null)} className="rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-600 dark:border-white/10 dark:text-slate-300">
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <button
                      onClick={() => setAddingStepFor(campaign.id)}
                      className="inline-flex items-center gap-2 rounded-xl border border-dashed border-slate-300 px-3 py-2 text-sm text-slate-500 hover:border-violet-400 hover:text-violet-600 dark:border-white/10"
                    >
                      <Plus className="h-3 w-3" /> Add step
                    </button>
                  )}
                </div>
              )}
              {/* Recipients panel */}
              {showRecipients[campaign.id] && (
                <div className="border-t border-slate-200 bg-blue-50/30 p-5 dark:border-white/10 dark:bg-blue-900/10">
                  <h4 className="mb-3 text-xs font-bold uppercase tracking-widest text-slate-400">Recipients</h4>
                  {recipientsLoading[campaign.id] ? (
                    <div className="flex items-center gap-2 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> Loading...</div>
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
                              <td className="px-4 py-2.5"><span className={`rounded-full px-2 py-0.5 text-xs font-medium ${recipientStatusColor[r.status] || recipientStatusColor.pending}`}>{r.status}</span></td>
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
                    <div className="flex items-center gap-2 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> Loading...</div>
                  ) : !emailReports[campaign.id] ? (
                    <p className="text-sm text-slate-500">No report data yet.</p>
                  ) : (
                    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                      {[
                        { label: "Emails Sent", value: emailReports[campaign.id]!.emails_sent, rate: null, color: "text-slate-700 dark:text-slate-200" },
                        { label: "Opens", value: emailReports[campaign.id]!.opens, rate: emailReports[campaign.id]!.open_rate, color: "text-blue-600 dark:text-blue-400" },
                        { label: "Clicks", value: emailReports[campaign.id]!.clicks, rate: emailReports[campaign.id]!.click_rate, color: "text-violet-600 dark:text-violet-400" },
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
                    onChange={(e) => setSelectedLeads((s) => e.target.checked ? [...s, lead.id] : s.filter((id) => id !== lead.id))}
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
                {enrollSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : null} Enroll {selectedLeads.length > 0 ? `(${selectedLeads.length})` : ""}
              </button>
              <button onClick={() => setEnrollFor(null)} className="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-600 dark:border-white/10 dark:text-slate-300">
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
