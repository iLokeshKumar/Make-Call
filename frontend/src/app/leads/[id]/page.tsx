"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowLeft, Loader2 } from "lucide-react";

import InteractionTimeline from "@/components/leads/interaction_timeline";
import LeadHeader from "@/components/leads/lead_header";
import LeadProfileCard from "@/components/leads/lead_profile_card";
import NextActionCard from "@/components/leads/next_action_card";
import QualificationCard from "@/components/leads/qualification_card";
import TranscriptPanel from "@/components/leads/transcript_panel";
import { useAuth } from "@/context/AuthContext";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:6060";

type Lead = {
  id: number;
  name: string;
  normalized_phone?: string | null;
  email?: string | null;
  status: string;
  qualification_status?: string | null;
  next_action?: string | null;
  next_action_due_at?: string | null;
  notes?: string | null;
  source?: string | null;
  city?: string | null;
  state?: string | null;
  country?: string | null;
  industry?: string | null;
  website?: string | null;
  created_at?: string;
};

type Requirement = {
  use_case?: string | null;
  budget_range?: string | null;
  timeline?: string | null;
  decision_maker?: string | null;
  pain_points?: string | null;
  required_products?: string | null;
};

type Interaction = {
  id: number;
  type?: string | null;
  status?: string | null;
  content?: string | null;
  transcript?: string | null;
  started_at?: string | null;
  created_at?: string | null;
};

type CallTask = {
  id: number;
  lead_id: number;
  status: string;
  notes?: string | null;
  scheduled_at?: string | null;
  completed_at?: string | null;
};

export default function LeadDetailPage() {
  const params = useParams<{ id: string }>();
  const leadId = Number(params?.id);
  const { token, sessionTimeout } = useAuth();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lead, setLead] = useState<Lead | null>(null);
  const [requirement, setRequirement] = useState<Requirement | null>(null);
  const [interactions, setInteractions] = useState<Interaction[]>([]);
  const [tasks, setTasks] = useState<CallTask[]>([]);

  const [nextActionDraft, setNextActionDraft] = useState<string>("");
  const [qualificationDraft, setQualificationDraft] = useState<string>("");
  const [updateNoteDraft, setUpdateNoteDraft] = useState<string>("");
  const [updating, setUpdating] = useState(false);
  const [updateMessage, setUpdateMessage] = useState<string | null>(null);

  const [noteText, setNoteText] = useState<string>("");
  const [noteSaving, setNoteSaving] = useState(false);
  const [noteMessage, setNoteMessage] = useState<string | null>(null);

  const [callMessage, setCallMessage] = useState<string | null>(null);

  const [aiSummary, setAiSummary] = useState<string>("");
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchLeadDetail() {
      if (!token || !leadId) {
        setLoading(false);
        return;
      }

      try {
        const headers = { Authorization: `Bearer ${token}` };
        const [leadRes, requirementRes, interactionRes, taskRes] = await Promise.all([
          fetch(`${API_BASE}/crm/leads/${leadId}`, { headers }),
          fetch(`${API_BASE}/requirements/${leadId}`, { headers }),
          fetch(`${API_BASE}/crm/interactions?lead_id=${leadId}`, { headers }),
          fetch(`${API_BASE}/call-tasks`, { headers }),
        ]);

        if ([leadRes, requirementRes, interactionRes, taskRes].some((response) => response.status === 401)) {
          sessionTimeout();
          return;
        }

        if (!leadRes.ok) {
          throw new Error("Lead not found or you do not have access to it.");
        }

        const leadPayload = await leadRes.json();
        setLead(leadPayload);

        if (requirementRes.ok) {
          setRequirement(await requirementRes.json());
        }

        if (interactionRes.ok) {
          const interactionPayload = await interactionRes.json();
          setInteractions(Array.isArray(interactionPayload) ? interactionPayload : interactionPayload.items || []);
        }

        if (taskRes.ok) {
          const taskPayload = await taskRes.json();
          const allTasks = Array.isArray(taskPayload) ? taskPayload : [];
          setTasks(allTasks.filter((task: CallTask) => task.lead_id === leadId));
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load Lead 360.");
      } finally {
        setLoading(false);
      }
    }

    fetchLeadDetail();
  }, [leadId, token, sessionTimeout]);

  useEffect(() => {
    if (!lead) return;
    setNextActionDraft(lead.next_action || "");
    setQualificationDraft(lead.qualification_status || "");
    setUpdateNoteDraft(lead.notes || "");
  }, [lead]);

  const fetchAiSummary = useCallback(async () => {
    console.log("fetchAiSummary called - token:", !!token, "leadId:", leadId);
    if (!token || !leadId) {
      console.log("Missing token or leadId, aborting");
      return;
    }
    
    setAiLoading(true);
    setAiError(null);

    try {
      const url = `${API_BASE}/crm/ai-insights?lead_id=${leadId}`;
      console.log("Fetching AI summary from:", url);
      
      const response = await fetch(url, {
        headers: { Authorization: `Bearer ${token}` },
      });

      console.log("AI insights response status:", response.status);

      if (response.status === 401) {
        sessionTimeout();
        return;
      }

      if (!response.ok) {
        throw new Error(`API returned status ${response.status}`);
      }

      const payload = await response.json();
      console.log("AI insights payload:", payload);
      setAiSummary(payload.summary || "No AI insight is available yet.");
    } catch (err) {
      console.error("Error fetching AI summary:", err);
      setAiError(err instanceof Error ? err.message : "AI insights fetch failed.");
      setAiSummary("");
    } finally {
      setAiLoading(false);
    }
  }, [leadId, token, sessionTimeout]);

  async function handleAddManualNote() {
    if (!token || !leadId || !noteText.trim()) return;
    setNoteSaving(true);
    setNoteMessage(null);

    try {
      const response = await fetch(`${API_BASE}/crm/interactions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          lead_id: leadId,
          type: "note",
          content: noteText.trim(),
        }),
      });

      if (response.status === 401) {
        sessionTimeout();
        return;
      }

      if (!response.ok) {
        throw new Error("Failed to save note.");
      }

      const newNote = await response.json();
      setInteractions((current) => [...current, { ...newNote, type: "note", status: "logged" }]);
      setNoteText("");
      setNoteMessage("Note added successfully.");
    } catch (err) {
      setNoteMessage(err instanceof Error ? err.message : "Could not save note.");
    } finally {
      setNoteSaving(false);
    }
  }

  useEffect(() => {
    if (leadId && token) fetchAiSummary();
  }, [leadId, token, fetchAiSummary]);

  const transcript = useMemo(
    () => interactions.find((interaction) => interaction.transcript)?.transcript || "",
    [interactions]
  );

  const timelineItems = useMemo(() => {
    const items = [] as Array<{
      id: string;
      title: string;
      subtitle?: string | null;
      timestamp?: string | null;
      tone?: "violet" | "emerald" | "amber" | "blue";
    }>;

    if (lead) {
      items.push({
        id: `lead-${lead.id}`,
        title: "Lead added to CRM",
        subtitle: lead.notes || "Lead record created and ready for outreach.",
        timestamp: lead.created_at,
        tone: "violet",
      });
    }

    interactions.forEach((interaction) => {
      items.push({
        id: `interaction-${interaction.id}`,
        title: `${interaction.type || "Interaction"} ${interaction.status || "logged"}`,
        subtitle: interaction.content,
        timestamp: interaction.started_at || interaction.created_at,
        tone: interaction.status === "completed" ? "emerald" : "blue",
      });
    });

    tasks.forEach((task) => {
      items.push({
        id: `task-${task.id}`,
        title: `Call task ${task.status}`,
        subtitle: task.notes || `Task #${task.id} for this lead`,
        timestamp: task.completed_at || task.scheduled_at,
        tone: task.status === "failed" ? "amber" : task.status === "completed" ? "emerald" : "blue",
      });
    });

    return items.sort((a, b) => (b.timestamp || "").localeCompare(a.timestamp || ""));
  }, [interactions, lead, tasks]);

  const callHistory = useMemo(() => {
    const callsFromInteractions = interactions
      .filter((interaction) => (interaction.type || "").toLowerCase().includes("call"))
      .map((interaction) => ({
        id: `interaction-call-${interaction.id}`,
        title: `Call interaction ${interaction.status || "logged"}`,
        subtitle: interaction.content || "Call performed",
        timestamp: interaction.started_at || interaction.created_at,
        tone: interaction.status === "completed" ? "emerald" : interaction.status === "failed" ? "amber" : "blue",
      }));

    const callTasks = tasks.map((task) => ({
      id: `task-${task.id}`,
      title: `Call task ${task.status}`,
      subtitle: task.notes || `Scheduled ${task.scheduled_at || "unknown"}`,
      timestamp: task.completed_at || task.scheduled_at,
      tone: task.status === "completed" ? "emerald" : task.status === "failed" ? "amber" : "blue",
    }));

    return [...callsFromInteractions, ...callTasks].sort((a, b) => (b.timestamp || "").localeCompare(a.timestamp || ""));
  }, [interactions, tasks]);

  const manualNotes = useMemo(() => interactions.filter((interaction) => (interaction.type || "").toLowerCase() === "note"), [interactions]);

  async function handleUpdateLead() {
    if (!token || !lead) return;
    setUpdating(true);
    setUpdateMessage(null);

    try {
      const response = await fetch(`${API_BASE}/crm/leads/${leadId}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          qualification_status: qualificationDraft || null,
          next_action: nextActionDraft || null,
          notes: updateNoteDraft || null,
        }),
      });

      if (response.status === 401) {
        sessionTimeout();
        return;
      }

      if (!response.ok) {
        const payload = await response.json();
        throw new Error(payload?.detail || "Update failed");
      }

      const updated = await response.json();
      setLead((current) => (current ? { ...current, ...updated } : current));
      setUpdateMessage("Lead details updated successfully.");
    } catch (err) {
      setUpdateMessage(err instanceof Error ? err.message : "Failed to update, try again.");
    } finally {
      setUpdating(false);
    }
  }

  async function handleDeleteLead() {
    if (!token || !leadId || !lead) return;
    if (!window.confirm(`Are you sure you want to delete the lead "${lead.name}"? This action cannot be undone.`)) {
      return;
    }

    try {
      const response = await fetch(`${API_BASE}/crm/leads/${leadId}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });

      if (response.status === 401) {
        sessionTimeout();
        return;
      }

      if (!response.ok) {
        throw new Error("Failed to delete lead");
      }

      // Navigate back to leads list
      window.location.href = "/leads";
    } catch (err) {
      alert(err instanceof Error ? err.message : "Delete failed");
    }
  }

  async function handleCall() {
    if (!token || !lead?.normalized_phone) return;

    setCallMessage(null);
    try {
      const response = await fetch(
        `${API_BASE}/make-call?to=${encodeURIComponent(lead.normalized_phone)}&lead_id=${lead.id}`,
        {
          method: "POST",
          headers: { Authorization: `Bearer ${token}` },
        }
      );

      if (response.status === 401) {
        sessionTimeout();
        return;
      }

      if (!response.ok) throw new Error("Call could not be started");
      setCallMessage(`Calling ${lead.name} at ${lead.normalized_phone}...`);
    } catch (callError) {
      setCallMessage(callError instanceof Error ? callError.message : "Failed to start the call.");
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center text-slate-500 dark:text-slate-400">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading Lead 360...
      </div>
    );
  }

  if (error || !lead) {
    return (
      <div className="rounded-2xl glass border border-white/40 p-6 text-slate-700 dark:border-white/10 dark:text-slate-200">
        <p className="font-semibold">{error || "Lead not found."}</p>
        <Link href="/leads" className="mt-4 inline-flex items-center gap-2 text-sm font-semibold text-violet-600 dark:text-violet-300">
          <ArrowLeft className="h-4 w-4" /> Back to leads
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-6 pb-8">
      <Link href="/leads" className="inline-flex items-center gap-2 text-sm font-semibold text-violet-600 dark:text-violet-300">
        <ArrowLeft className="h-4 w-4" /> Back to leads
      </Link>

      <LeadHeader
        name={lead.name}
        phone={lead.normalized_phone}
        email={lead.email}
        status={lead.status}
        qualificationStatus={lead.qualification_status}
        source={lead.source}
        onCall={handleCall}
        onReviewAIInsights={fetchAiSummary}
        onDelete={handleDeleteLead}
      />

      {callMessage && (
        <div className="rounded-2xl border border-violet-200 bg-violet-50 px-4 py-3 text-sm text-violet-700 dark:border-violet-500/20 dark:bg-violet-500/10 dark:text-violet-200 animate-in fade-in slide-in-from-top-2">
          {callMessage}
        </div>
      )}

      <div className="rounded-3xl glass border border-white/40 p-6 dark:border-white/10">
        <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Quick Lead update</h2>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">Update qualification and next action without leaving Lead 360.</p>

        <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-3">
          <select
            value={qualificationDraft}
            onChange={(event) => setQualificationDraft(event.target.value)}
            className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
          >
            <option value="">Qualification status</option>
            <option value="new">New</option>
            <option value="contacted">Contacted</option>
            <option value="qualified">Qualified</option>
            <option value="proposal">Proposal</option>
            <option value="won">Won</option>
            <option value="lost">Lost</option>
          </select>

          <input
            value={nextActionDraft}
            onChange={(event) => setNextActionDraft(event.target.value)}
            placeholder="Next action"
            className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
          />

          <input
            value={updateNoteDraft}
            onChange={(event) => setUpdateNoteDraft(event.target.value)}
            placeholder="Quick note"
            className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
          />
        </div>

        <div className="mt-4 flex items-center gap-3">
          <button
            type="button"
            onClick={handleUpdateLead}
            disabled={updating}
            className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:scale-[1.01] disabled:opacity-60"
          >
            {updating ? "Saving..." : "Save updates"}
          </button>
          {updateMessage && <span className="text-sm text-slate-600 dark:text-slate-300">{updateMessage}</span>}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <div className="space-y-6 xl:col-span-1">
          <LeadProfileCard
            phone={lead.normalized_phone}
            email={lead.email}
            city={lead.city}
            state={lead.state}
            country={lead.country}
            industry={lead.industry}
            website={lead.website}
            notes={lead.notes}
          />
          <NextActionCard nextAction={lead.next_action} dueAt={lead.next_action_due_at} />
        </div>

        <div className="space-y-6 xl:col-span-2">
          <QualificationCard qualificationStatus={lead.qualification_status} requirement={requirement} />

          <div className="rounded-2xl glass border border-white/40 p-5 dark:border-white/10">
            <h3 className="text-lg font-semibold text-slate-900 dark:text-white">Add manual note</h3>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">Keep your team in sync by quickly logging insights.</p>
            <textarea
              value={noteText}
              onChange={(event) => setNoteText(event.target.value)}
              rows={3}
              placeholder="Write a note about this lead"
              className="mt-3 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
            />
            <div className="mt-3 flex items-center gap-3">
              <button
                type="button"
                onClick={handleAddManualNote}
                disabled={noteSaving}
                className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:scale-[1.01] disabled:opacity-60"
              >
                {noteSaving ? "Saving..." : "Save note"}
              </button>
              {noteMessage && <span className="text-sm text-slate-600 dark:text-slate-300">{noteMessage}</span>}
            </div>

            {manualNotes.length > 0 && (
              <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-3 dark:border-white/10 dark:bg-slate-900/30">
                <h4 className="text-sm font-semibold text-slate-800 dark:text-slate-100">Recent manual notes</h4>
                <ul className="mt-2 space-y-2 text-sm text-slate-600 dark:text-slate-300">
                  {manualNotes.slice(-3).reverse().map((note) => (
                    <li key={note.id}>
                      <div className="text-slate-800 dark:text-slate-100">{note.content}</div>
                      <div className="text-xs text-slate-500 dark:text-slate-400">{note.created_at ? new Date(note.created_at).toLocaleString() : "n/a"}</div>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          <div className="rounded-2xl glass border border-white/40 p-5 dark:border-white/10">
            <h3 className="text-lg font-semibold text-slate-900 dark:text-white">Call action history</h3>
            {callHistory.length === 0 ? (
              <p className="mt-3 text-sm text-slate-500 dark:text-slate-400">No call activities yet for this lead.</p>
            ) : (
              <ul className="mt-3 space-y-2">
                {callHistory.map((entry) => (
                  <li key={entry.id} className="rounded-xl border border-slate-200 bg-white/70 p-3 dark:border-white/10 dark:bg-slate-900/40">
                    <div className="flex items-center justify-between text-sm font-medium text-slate-800 dark:text-slate-100">
                      <span>{entry.title}</span>
                      <span className="text-xs text-slate-500 dark:text-slate-400">{entry.timestamp ? new Date(entry.timestamp).toLocaleString() : "unknown"}</span>
                    </div>
                    {entry.subtitle && <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{entry.subtitle}</p>}
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="rounded-2xl glass border border-white/40 p-5 dark:border-white/10">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold text-slate-900 dark:text-white">AI Insight summary</h3>
              <button
                type="button"
                onClick={fetchAiSummary}
                disabled={aiLoading}
                className="rounded-lg border border-slate-200 px-3 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-100 dark:border-white/10 dark:text-slate-200"
              >
                {aiLoading ? "Refreshing..." : "Refresh"}
              </button>
            </div>
            {aiError && <p className="mt-3 text-sm font-medium text-amber-600 dark:text-amber-300">{aiError}</p>}
            <p className="mt-3 text-sm text-slate-600 dark:text-slate-300">{aiSummary || "No summary available yet. Click refresh to fetch AI insights."}</p>
          </div>

          <InteractionTimeline items={timelineItems} />
          <TranscriptPanel transcript={transcript} />
        </div>
      </div>
    </div>
  );
}
