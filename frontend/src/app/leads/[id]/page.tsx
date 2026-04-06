"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowLeft, Brain, Edit3, Loader2, RefreshCw, Save, Target, TrendingUp, UserCheck, Zap } from "lucide-react";

import InteractionTimeline from "@/components/leads/interaction_timeline";
import LeadHeader from "@/components/leads/lead_header";
import LeadProfileCard from "@/components/leads/lead_profile_card";
import NextActionCard from "@/components/leads/next_action_card";
import QualificationCard from "@/components/leads/qualification_card";
import TranscriptPanel from "@/components/leads/transcript_panel";
import SentimentGauge from "@/components/SentimentGauge";
import WhatsAppThread from "@/components/leads/whatsapp_thread";
import EmailThread from "@/components/leads/email_thread";
import CompetitorBadges from "@/components/leads/competitor_badges";
import WaveformPlayer from "@/components/leads/waveform_player";
import EnrichmentTrace from "@/components/leads/enrichment_trace";
import SalesCoachPanel from "@/components/leads/sales_coach_panel";
import BestCallTimes from "@/components/leads/best_call_times";
import { useAuth } from "@/context/AuthContext";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:6060";

type Lead = {
  id: number;
  name: string;
  normalized_phone?: string | null;
  email?: string | null;
  status: string;
  preferred_language?: string | null;
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
  lead_score?: number | null;
  lead_score_reasons_json?: { reasons: string[]; priority: string } | string[] | null;
  product_interest?: string | null;
  last_outreach_at?: string | null;
  ism_stage?: string | null;
  budget_range?: string | null;
  timeline?: string | null;
  decision_maker?: string | null;
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
  recording_url?: string | null;
  recording_duration?: number | null;
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

// stage display config
const ISM_STAGE_CONFIG: Record<string, { label: string; cls: string }> = {
  new:          { label: "New",          cls: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300" },
  contacted:    { label: "Contacted",    cls: "bg-blue-100 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300" },
  engaged:      { label: "Engaged",      cls: "bg-violet-100 text-violet-700 dark:bg-violet-500/10 dark:text-violet-300" },
  quote_sent:   { label: "Quote Sent",   cls: "bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300" },
  negotiation:  { label: "Negotiation",  cls: "bg-orange-100 text-orange-700 dark:bg-orange-500/10 dark:text-orange-300" },
  closed_won:   { label: "Closed Won",   cls: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300" },
  closed_lost:  { label: "Closed Lost",  cls: "bg-red-100 text-red-700 dark:bg-red-500/10 dark:text-red-300" },
};

function IsmStagePill({ stage }: { stage: string }) {
  const config = ISM_STAGE_CONFIG[stage] ?? { label: stage, cls: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300" };
  return (
    <span className={`rounded-full px-3 py-1 text-xs font-semibold ${config.cls}`}>
      {config.label}
    </span>
  );
}

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
  const [languageDraft, setLanguageDraft] = useState<string>("en");
  const [updating, setUpdating] = useState(false);
  const [updateMessage, setUpdateMessage] = useState<string | null>(null);

  const [noteText, setNoteText] = useState<string>("");
  const [noteSaving, setNoteSaving] = useState(false);
  const [noteMessage, setNoteMessage] = useState<string | null>(null);

  const [callMessage, setCallMessage] = useState<string | null>(null);
  const [callInteractionId, setCallInteractionId] = useState<number | null>(null);
  const [callStatus, setCallStatus] = useState<string | null>(null);

  // Warm transfer state
  const [showTransferModal, setShowTransferModal] = useState(false);
  const [transferTo, setTransferTo] = useState("");
  const [isrName, setIsrName] = useState("");
  const [transferring, setTransferring] = useState(false);
  const [transferResult, setTransferResult] = useState<string | null>(null);

  const [aiSummary, setAiSummary] = useState<string>("");
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);

  // ICP Score actions
  const [rescoring, setRescoring] = useState(false);
  const [enriching, setEnriching] = useState(false);
  const [enrichToast, setEnrichToast] = useState<string | null>(null);

  // Requirements editor
  const [reqEditMode, setReqEditMode] = useState(false);
  const [reqDraft, setReqDraft] = useState<Requirement>({});
  const [reqSaving, setReqSaving] = useState(false);
  const [reqMessage, setReqMessage] = useState<string | null>(null);

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
          const reqPayload = await requirementRes.json();
          setRequirement(reqPayload);
          setReqDraft(reqPayload);
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
    setLanguageDraft(lead.preferred_language || "en");
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

  async function handleRescore() {
    if (!token || !leadId) return;
    setRescoring(true);
    try {
      const res = await fetch(`${API_BASE}/crm/leads/${leadId}/rescore`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) throw new Error("Re-score failed");
      const updated = await res.json();
      setLead((curr) => curr ? { ...curr, ...updated } : curr);
    } catch (err) {
      console.error("Rescore error:", err);
    } finally {
      setRescoring(false);
    }
  }

  async function handleEnrich() {
    if (!token || !leadId) return;
    setEnriching(true);
    setEnrichToast(null);
    try {
      const res = await fetch(`${API_BASE}/crm/leads/${leadId}/enrich`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) throw new Error("Enrichment failed");
      const payload = await res.json();
      setEnrichToast(payload?.message || "Enrichment complete.");
      // Refresh lead data
      const leadRes = await fetch(`${API_BASE}/crm/leads/${leadId}`, { headers: { Authorization: `Bearer ${token}` } });
      if (leadRes.ok) setLead(await leadRes.json());
    } catch (err) {
      setEnrichToast(err instanceof Error ? err.message : "Enrichment failed.");
    } finally {
      setEnriching(false);
      setTimeout(() => setEnrichToast(null), 4000);
    }
  }

  async function handleSaveRequirements() {
    if (!token || !leadId) return;
    setReqSaving(true);
    setReqMessage(null);
    try {
      const res = await fetch(`${API_BASE}/requirements/${leadId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify(reqDraft),
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) {
        const payload = await res.json();
        throw new Error(payload?.detail || "Save failed");
      }
      const saved = await res.json();
      setRequirement(saved);
      setReqDraft(saved);
      setReqEditMode(false);
      setReqMessage("Requirements saved successfully.");
    } catch (err) {
      setReqMessage(err instanceof Error ? err.message : "Could not save requirements.");
    } finally {
      setReqSaving(false);
    }
  }

  const transcript = useMemo(
    () => interactions.find((interaction) => interaction.transcript)?.transcript || "",
    [interactions]
  );

  const latestRecording = useMemo(
    () => interactions.find((i) => i.type === "call" && i.recording_url) ?? null,
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
          preferred_language: languageDraft || "en",
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

      window.location.href = "/leads";
    } catch (err) {
      alert(err instanceof Error ? err.message : "Delete failed");
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
        setCallStatus(data.call_status);
        setCallMessage(CALL_STATUS_LABELS[data.call_status] ?? data.call_status);
        if (data.is_terminal) {
          clearInterval(interval);
          setTimeout(() => { setCallInteractionId(null); setCallStatus(null); }, 4000);
        }
      } catch { /* ignore */ }
    }, 2000);
    return () => clearInterval(interval);
  }, [callInteractionId, token]);

  async function handleCall() {
    if (!token || !lead?.normalized_phone) return;

    setCallMessage(null);
    setCallInteractionId(null);
    setCallStatus(null);
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
      const data = await response.json();
      setCallMessage(`Calling ${lead.name} at ${lead.normalized_phone}...`);
      if (data.interaction_id) setCallInteractionId(data.interaction_id);
    } catch (callError) {
      setCallMessage(callError instanceof Error ? callError.message : "Failed to start the call.");
    }
  }

  async function handleWarmTransfer() {
    if (!token || !callInteractionId || !transferTo.trim()) return;
    setTransferring(true);
    setTransferResult(null);
    try {
      const params = new URLSearchParams({
        interaction_id: String(callInteractionId),
        transfer_to: transferTo.trim(),
      });
      if (isrName.trim()) params.set("isr_name", isrName.trim());
      const res = await fetch(`${API_BASE}/warm-transfer?${params}`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) {
        const e = await res.json();
        throw new Error(e.detail || "Transfer failed");
      }
      setTransferResult(`Transferred to ${transferTo.trim()} — ISR is joining the call.`);
      setShowTransferModal(false);
    } catch (err) {
      setTransferResult(err instanceof Error ? err.message : "Transfer failed");
    } finally {
      setTransferring(false);
    }
  }

  // Derive score reasons as a string array regardless of shape
  const scoreReasons: string[] = useMemo(() => {
    if (!lead?.lead_score_reasons_json) return [];
    if (Array.isArray(lead.lead_score_reasons_json)) return lead.lead_score_reasons_json as string[];
    const obj = lead.lead_score_reasons_json as { reasons?: string[] };
    return Array.isArray(obj.reasons) ? obj.reasons : [];
  }, [lead]);

  const scorePriority: string = useMemo(() => {
    if (!lead?.lead_score_reasons_json) return "";
    if (!Array.isArray(lead.lead_score_reasons_json)) {
      const obj = lead.lead_score_reasons_json as { priority?: string };
      return obj.priority || "";
    }
    return "";
  }, [lead]);

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
        <div className={`rounded-2xl border px-4 py-3 text-sm flex items-center gap-2 animate-in fade-in slide-in-from-top-2 ${
          callStatus === "completed" ? "border-green-200 bg-green-50 text-green-700 dark:border-green-500/20 dark:bg-green-500/10 dark:text-green-300"
          : callStatus === "no-answer" || callStatus === "busy" || callStatus === "failed" ? "border-red-200 bg-red-50 text-red-700 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-300"
          : callStatus === "in-progress" ? "border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-500/20 dark:bg-blue-500/10 dark:text-blue-300"
          : "border-violet-200 bg-violet-50 text-violet-700 dark:border-violet-500/20 dark:bg-violet-500/10 dark:text-violet-200"
        }`}>
          {callInteractionId && !TERMINAL_STATUSES.has(callStatus ?? "") && (
            <span className="inline-block h-2 w-2 rounded-full bg-current animate-pulse flex-shrink-0" />
          )}
          {callMessage}
        </div>
      )}

      {/* Real-time sentiment gauge + warm transfer — visible while call is active */}
      {callInteractionId && callStatus === "in-progress" && (
        <>
          <SentimentGauge
            interactionId={callInteractionId}
            onDisconnect={() => {/* gauge goes away when call ends */}}
          />
          <button
            onClick={() => { setShowTransferModal(true); setTransferResult(null); }}
            className="inline-flex items-center gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm font-semibold text-amber-700 hover:bg-amber-100 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-300 transition"
          >
            <UserCheck className="h-4 w-4" /> Transfer to Human ISR
          </button>
        </>
      )}

      {transferResult && (
        <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-300 animate-in fade-in slide-in-from-top-2">
          {transferResult}
        </div>
      )}

      {/* Warm Transfer */}
      {showTransferModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 backdrop-blur-sm p-4">
          <div className="w-full max-w-sm rounded-2xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 p-6 shadow-2xl space-y-4">
            <div className="flex items-center gap-2">
              <UserCheck className="h-5 w-5 text-amber-500" />
              <h3 className="text-lg font-bold text-slate-900 dark:text-white">Transfer to Human ISR</h3>
            </div>
            <p className="text-sm text-slate-500 dark:text-slate-400">
              The AI will be bridged into a conference. The ISR will join immediately.
            </p>
            <div className="space-y-3">
              <input
                value={transferTo}
                onChange={(e) => setTransferTo(e.target.value)}
                placeholder="ISR phone number (e.g. +919876543210)"
                className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm outline-none focus:border-amber-400 dark:border-white/10 dark:bg-slate-800/50"
              />
              <input
                value={isrName}
                onChange={(e) => setIsrName(e.target.value)}
                placeholder="ISR name (optional)"
                className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm outline-none focus:border-amber-400 dark:border-white/10 dark:bg-slate-800/50"
              />
            </div>
            <div className="flex gap-2 pt-1">
              <button
                onClick={() => setShowTransferModal(false)}
                className="flex-1 rounded-xl border border-slate-200 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-50 dark:border-white/10 dark:text-slate-300"
              >
                Cancel
              </button>
              <button
                onClick={handleWarmTransfer}
                disabled={!transferTo.trim() || transferring}
                className="flex-1 rounded-xl bg-amber-500 py-2 text-sm font-semibold text-white hover:bg-amber-600 disabled:opacity-50 flex items-center justify-center gap-2"
              >
                {transferring ? <Loader2 className="h-4 w-4 animate-spin" /> : <UserCheck className="h-4 w-4" />}
                Transfer Now
              </button>
            </div>
          </div>
        </div>
      )}

      {enrichToast && (
        <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-200 animate-in fade-in slide-in-from-top-2">
          {enrichToast}
        </div>
      )}

      {/* Stage Card */}
      {(lead.ism_stage || lead.next_action || lead.next_action_due_at) && (
        <div className="rounded-2xl glass border border-white/40 p-5 dark:border-white/10">
          <div className="flex flex-wrap items-center gap-3">
            <Zap className="h-5 w-5 text-violet-500" />
            <h3 className="text-lg font-semibold text-slate-900 dark:text-white">Automation Stage</h3>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-4">
            {lead.ism_stage && (
              <div className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
                <span className="font-medium text-slate-800 dark:text-slate-100">Stage:</span>
                <IsmStagePill stage={lead.ism_stage} />
              </div>
            )}
            {lead.last_outreach_at && (
              <div className="text-sm text-slate-600 dark:text-slate-300">
                <span className="font-medium text-slate-800 dark:text-slate-100">Last outreach: </span>
                {new Date(lead.last_outreach_at).toLocaleString()}
              </div>
            )}
          </div>
          {(lead.next_action || lead.next_action_due_at) && (
            <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50/80 px-4 py-3 text-sm dark:border-white/10 dark:bg-slate-900/30">
              {lead.next_action && (
                <div className="text-slate-700 dark:text-slate-200">
                  <span className="font-medium">Next action: </span>{lead.next_action}
                </div>
              )}
              {lead.next_action_due_at && (
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  Due: {new Date(lead.next_action_due_at).toLocaleString()}
                </div>
              )}
            </div>
          )}
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

        {/* Language selector — controls which language the AI voice agent speaks */}
        <div className="mt-3 flex items-center gap-3">
          <label className="text-xs font-semibold text-slate-600 dark:text-slate-300 whitespace-nowrap">
            Voice language:
          </label>
          <select
            value={languageDraft}
            onChange={(e) => setLanguageDraft(e.target.value)}
            className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
          >
            <option value="en">English</option>
            <option value="hi">Hindi (हिंदी)</option>
            <option value="ta">Tamil (தமிழ்)</option>
            <option value="te">Telugu (తెలుగు)</option>
            <option value="kn">Kannada (ಕನ್ನಡ)</option>
            <option value="mr">Marathi (मराठी)</option>
            <option value="gu">Gujarati (ગુજરાતી)</option>
            <option value="bn">Bengali (বাংলা)</option>
            <option value="pa">Punjabi (ਪੰਜਾਬੀ)</option>
            <option value="ml">Malayalam (മലയാളം)</option>
          </select>
          {(lead.preferred_language && lead.preferred_language !== "en") && (
            <span className="text-xs text-violet-600 dark:text-violet-400 font-semibold">
              Next call will use Sarvam AI in {languageDraft.toUpperCase()}
            </span>
          )}
        </div>

        <div className="mt-4 flex items-center gap-3">
          <button
            type="button"
            onClick={handleUpdateLead}
            disabled={updating}
            className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-violet-500/20 transition hover:scale-[1.01] disabled:opacity-60"
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

          {/* Waterfall enrichment pipeline */}
          <EnrichmentTrace
            leadId={leadId}
            token={token!}
            onSessionTimeout={sessionTimeout}
          />

          {/* Predictive call windows */}
          <BestCallTimes
            leadId={leadId}
            token={token!}
            onSessionTimeout={sessionTimeout}
          />

          {/* Sales Intelligence */}
          {(lead.budget_range || lead.timeline || lead.decision_maker) && (
            <div className="rounded-2xl glass border border-white/40 p-5 dark:border-white/10">
              <div className="flex items-center gap-2 mb-3">
                <TrendingUp className="h-5 w-5 text-violet-500" />
                <h3 className="text-lg font-semibold text-slate-900 dark:text-white">Sales Intelligence</h3>
              </div>
              <dl className="space-y-2 text-sm">
                {lead.budget_range && (
                  <div className="flex gap-2">
                    <dt className="font-medium text-slate-700 dark:text-slate-300 min-w-[110px]">Budget:</dt>
                    <dd className="text-slate-600 dark:text-slate-400">{lead.budget_range}</dd>
                  </div>
                )}
                {lead.timeline && (
                  <div className="flex gap-2">
                    <dt className="font-medium text-slate-700 dark:text-slate-300 min-w-[110px]">Timeline:</dt>
                    <dd className="text-slate-600 dark:text-slate-400">{lead.timeline}</dd>
                  </div>
                )}
                {lead.decision_maker && (
                  <div className="flex gap-2">
                    <dt className="font-medium text-slate-700 dark:text-slate-300 min-w-[110px]">Decision Maker:</dt>
                    <dd className="text-slate-600 dark:text-slate-400">{lead.decision_maker}</dd>
                  </div>
                )}
              </dl>
            </div>
          )}
        </div>

        <div className="space-y-6 xl:col-span-2">
          <QualificationCard qualificationStatus={lead.qualification_status} requirement={requirement} />

          {/* Enhanced ICP Score Card */}
          <div className="rounded-2xl glass border border-white/40 p-5 dark:border-white/10">
            <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
              <div className="flex items-center gap-2">
                <Target className="h-5 w-5 text-violet-500" />
                <h3 className="text-lg font-semibold text-slate-900 dark:text-white">ICP Score</h3>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={handleRescore}
                  disabled={rescoring}
                  className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-violet-500/20 disabled:opacity-60"
                >
                  <RefreshCw className={`h-3.5 w-3.5 ${rescoring ? "animate-spin" : ""}`} />
                  {rescoring ? "Scoring..." : "Re-score Lead"}
                </button>
                <button
                  type="button"
                  onClick={handleEnrich}
                  disabled={enriching}
                  className="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-600 dark:border-white/10 dark:text-slate-300 disabled:opacity-60 inline-flex items-center gap-2"
                >
                  <Brain className={`h-3.5 w-3.5 ${enriching ? "animate-pulse" : ""}`} />
                  {enriching ? "Enriching..." : "Trigger Enrichment"}
                </button>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-6">
              {/* Score circle */}
              {lead.lead_score != null && (
                <div className="flex flex-col items-center gap-1">
                  <div
                    className={`flex h-20 w-20 items-center justify-center rounded-full border-4 text-xl font-bold shadow-inner ${
                      lead.lead_score >= 70
                        ? "border-emerald-400 text-emerald-600 bg-emerald-50 dark:border-emerald-500 dark:text-emerald-300 dark:bg-emerald-500/10"
                        : lead.lead_score >= 40
                        ? "border-amber-400 text-amber-600 bg-amber-50 dark:border-amber-500 dark:text-amber-300 dark:bg-amber-500/10"
                        : "border-slate-300 text-slate-500 bg-slate-50 dark:border-slate-600 dark:text-slate-400 dark:bg-slate-800/40"
                    }`}
                  >
                    {Math.round(lead.lead_score)}
                  </div>
                  <span
                    className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                      lead.lead_score >= 70
                        ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300"
                        : lead.lead_score >= 40
                        ? "bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300"
                        : "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400"
                    }`}
                  >
                    {lead.lead_score >= 70 ? "High" : lead.lead_score >= 40 ? "Medium" : "Low"} Priority
                  </span>
                  {scorePriority && scorePriority !== (lead.lead_score >= 70 ? "high" : lead.lead_score >= 40 ? "medium" : "low") && (
                    <span className="text-xs text-slate-500 dark:text-slate-400">({scorePriority})</span>
                  )}
                </div>
              )}

              <div className="flex-1 space-y-2 text-sm text-slate-600 dark:text-slate-300 min-w-0">
                {lead.product_interest && (
                  <div>
                    <span className="font-medium text-slate-800 dark:text-slate-100">Product interest: </span>
                    {lead.product_interest}
                  </div>
                )}
                {lead.last_outreach_at && (
                  <div>
                    <span className="font-medium text-slate-800 dark:text-slate-100">Last outreach: </span>
                    {new Date(lead.last_outreach_at).toLocaleString()}
                  </div>
                )}
              </div>
            </div>

            {scoreReasons.length > 0 && (
              <div className="mt-4">
                <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">Score reasons</p>
                <div className="flex flex-wrap gap-2">
                  {scoreReasons.map((reason) => (
                    <span
                      key={reason}
                      className="rounded-lg bg-violet-100 px-2.5 py-1 text-xs font-medium text-violet-700 dark:bg-violet-500/10 dark:text-violet-300"
                    >
                      {reason.replace(/_/g, " ")}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {lead.lead_score == null && scoreReasons.length === 0 && !lead.product_interest && !lead.last_outreach_at && (
              <p className="text-sm text-slate-500 dark:text-slate-400">No ICP score yet. Click Re-score Lead to generate one.</p>
            )}
          </div>

          {/* Requirements Editor */}
          <div className="rounded-2xl glass border border-white/40 p-5 dark:border-white/10">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-slate-900 dark:text-white">Requirements</h3>
              {!reqEditMode ? (
                <button
                  type="button"
                  onClick={() => { setReqEditMode(true); setReqMessage(null); }}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-600 dark:border-white/10 dark:text-slate-300 hover:border-violet-400 hover:text-violet-600 transition"
                >
                  <Edit3 className="h-3.5 w-3.5" /> Edit
                </button>
              ) : (
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={handleSaveRequirements}
                    disabled={reqSaving}
                    className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-violet-500/20 disabled:opacity-60"
                  >
                    <Save className="h-3.5 w-3.5" />
                    {reqSaving ? "Saving..." : "Save Requirements"}
                  </button>
                  <button
                    type="button"
                    onClick={() => { setReqEditMode(false); setReqDraft(requirement || {}); setReqMessage(null); }}
                    className="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-semibold text-slate-600 dark:border-white/10 dark:text-slate-300"
                  >
                    Cancel
                  </button>
                </div>
              )}
            </div>

            {reqMessage && (
              <div className={`mb-3 rounded-xl px-4 py-2 text-sm ${
                reqMessage.includes("success") || reqMessage.includes("saved")
                  ? "bg-emerald-50 text-emerald-700 border border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-300 dark:border-emerald-500/20"
                  : "bg-red-50 text-red-700 border border-red-200 dark:bg-red-500/10 dark:text-red-300 dark:border-red-500/20"
              }`}>
                {reqMessage}
              </div>
            )}

            {reqEditMode ? (
              <div className="space-y-4">
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <div>
                    <label className="mb-1 block text-xs font-semibold text-slate-600 dark:text-slate-400">Budget Range</label>
                    <input
                      value={reqDraft.budget_range || ""}
                      onChange={(e) => setReqDraft((d) => ({ ...d, budget_range: e.target.value }))}
                      placeholder="e.g. $50k–$100k"
                      className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-semibold text-slate-600 dark:text-slate-400">Timeline</label>
                    <input
                      value={reqDraft.timeline || ""}
                      onChange={(e) => setReqDraft((d) => ({ ...d, timeline: e.target.value }))}
                      placeholder="e.g. Q2 2025"
                      className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-semibold text-slate-600 dark:text-slate-400">Decision Maker</label>
                    <input
                      value={reqDraft.decision_maker || ""}
                      onChange={(e) => setReqDraft((d) => ({ ...d, decision_maker: e.target.value }))}
                      placeholder="e.g. CTO, Procurement Head"
                      className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-semibold text-slate-600 dark:text-slate-400">Required Products</label>
                    <input
                      value={reqDraft.required_products || ""}
                      onChange={(e) => setReqDraft((d) => ({ ...d, required_products: e.target.value }))}
                      placeholder="e.g. Enterprise Plan, API Access"
                      className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
                    />
                  </div>
                </div>
                <div>
                  <label className="mb-1 block text-xs font-semibold text-slate-600 dark:text-slate-400">Use Case</label>
                  <textarea
                    value={reqDraft.use_case || ""}
                    onChange={(e) => setReqDraft((d) => ({ ...d, use_case: e.target.value }))}
                    rows={3}
                    placeholder="Describe the primary use case..."
                    className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-semibold text-slate-600 dark:text-slate-400">Pain Points</label>
                  <textarea
                    value={reqDraft.pain_points || ""}
                    onChange={(e) => setReqDraft((d) => ({ ...d, pain_points: e.target.value }))}
                    rows={3}
                    placeholder="Current challenges and pain points..."
                    className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
                  />
                </div>
              </div>
            ) : (
              <dl className="space-y-3 text-sm">
                {requirement?.use_case && (
                  <div>
                    <dt className="font-medium text-slate-700 dark:text-slate-300">Use Case</dt>
                    <dd className="mt-0.5 text-slate-600 dark:text-slate-400">{requirement.use_case}</dd>
                  </div>
                )}
                {requirement?.budget_range && (
                  <div>
                    <dt className="font-medium text-slate-700 dark:text-slate-300">Budget Range</dt>
                    <dd className="mt-0.5 text-slate-600 dark:text-slate-400">{requirement.budget_range}</dd>
                  </div>
                )}
                {requirement?.timeline && (
                  <div>
                    <dt className="font-medium text-slate-700 dark:text-slate-300">Timeline</dt>
                    <dd className="mt-0.5 text-slate-600 dark:text-slate-400">{requirement.timeline}</dd>
                  </div>
                )}
                {requirement?.decision_maker && (
                  <div>
                    <dt className="font-medium text-slate-700 dark:text-slate-300">Decision Maker</dt>
                    <dd className="mt-0.5 text-slate-600 dark:text-slate-400">{requirement.decision_maker}</dd>
                  </div>
                )}
                {requirement?.pain_points && (
                  <div>
                    <dt className="font-medium text-slate-700 dark:text-slate-300">Pain Points</dt>
                    <dd className="mt-0.5 text-slate-600 dark:text-slate-400">{requirement.pain_points}</dd>
                  </div>
                )}
                {requirement?.required_products && (
                  <div>
                    <dt className="font-medium text-slate-700 dark:text-slate-300">Required Products</dt>
                    <dd className="mt-0.5 text-slate-600 dark:text-slate-400">{requirement.required_products}</dd>
                  </div>
                )}
                {!requirement?.use_case && !requirement?.budget_range && !requirement?.timeline && !requirement?.decision_maker && !requirement?.pain_points && !requirement?.required_products && (
                  <p className="text-slate-400 dark:text-slate-500">No requirements recorded yet. Click Edit to add them.</p>
                )}
              </dl>
            )}
          </div>

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
                className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-violet-500/20 transition hover:scale-[1.01] disabled:opacity-60"
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

          {/* Call recording + waveform player */}
          {latestRecording?.recording_url && (
            <WaveformPlayer
              recordingUrl={latestRecording.recording_url}
              transcript={latestRecording.transcript}
              duration={latestRecording.recording_duration}
            />
          )}

          {/* AI Sales Coach — show score for most recent call interaction */}
          {latestRecording && (
            <SalesCoachPanel
              interactionId={latestRecording.id}
              token={token!}
              onSessionTimeout={sessionTimeout}
            />
          )}

          {/* Competitor signals detected on calls */}
          <CompetitorBadges
            leadId={leadId}
            token={token!}
            onSessionTimeout={sessionTimeout}
          />

          {/* WhatsApp conversation thread */}
          <WhatsAppThread
            leadId={leadId}
            token={token!}
            onSessionTimeout={sessionTimeout}
          />

          {/* Email thread */}
          <EmailThread
            leadId={leadId}
            token={token!}
            leadEmail={lead?.email}
            onSessionTimeout={sessionTimeout}
          />
        </div>
      </div>
    </div>
  );
}
