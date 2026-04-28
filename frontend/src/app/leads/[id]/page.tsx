"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Brain, Calendar, CheckCircle2, ChevronDown, ChevronUp, Edit3, FileText, Loader2, MapPin, Phone, Plus, RefreshCw, Save, Send, Target, TrendingUp, UserCheck, X, XCircle, Zap } from "lucide-react";

import InteractionTimeline from "@/components/leads/interaction_timeline";
import LeadHeader from "@/components/leads/lead_header";
import LeadProfileCard from "@/components/leads/lead_profile_card";
import NextActionCard from "@/components/leads/next_action_card";
import QualificationCard from "@/components/leads/qualification_card";
import TranscriptPanel from "@/components/leads/transcript_panel";
import WaveformPlayer from "@/components/leads/waveform_player";
import SentimentGauge from "@/components/SentimentGauge";
import WhatsAppThread from "@/components/leads/whatsapp_thread";
import EmailThread from "@/components/leads/email_thread";
import CompetitorBadges from "@/components/leads/competitor_badges";
import EnrichmentTrace from "@/components/leads/enrichment_trace";
import SalesCoachPanel from "@/components/leads/sales_coach_panel";
import BestCallTimes from "@/components/leads/best_call_times";
import ExplainNextAction from "@/components/leads/explain_next_action";
import AgentActionsTimeline from "@/components/leads/agent_actions_timeline";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { useAuth } from "@/context/AuthContext";

import { apiFetch } from "@/utils/apiFetch";
import {
  extractLatestQualification,
  extractLatestRecommendation,
  formatInteractionSubtitle,
  formatNextActionLabel,
  humanizeInteractionTitle,
} from "@/utils/interaction_format";
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:6060";

function cleanNotes(notes: string | null | undefined): string {
    if (!notes) return "";
    return notes
        .split("\n")
        .filter(line => !/^\[20\d\d-\d\d-\d\dT/.test(line.trim()))
        .join("\n")
        .trim();
}

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
  // B2B billing
  billing_address?: string | null;
  pincode?: string | null;
  gst_number?: string | null;
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
  direction?: string | null;
  channel?: string | null;
  status?: string | null;
  content?: string | null;
  transcript?: string | null;
  recording_url?: string | null;
  recording_duration?: number | null;
  started_at?: string | null;
  ended_at?: string | null;
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

type DealEvent =
  | {
      kind: "appointment";
      id: number;
      date: string | null;
      status: string;
      demo_type: string;
      products: string | null;
      location: string | null;
      notes: string | null;
      meeting_link: string | null;
    }
  | {
      kind: "quote";
      id: number;
      quote_number: string;
      date: string | null;
      status: string;
      currency: string;
      total_amount: string | null;
      valid_until: string | null;
      sent_at: string | null;
      opened_at: string | null;
      accepted_at: string | null;
      rejected_at: string | null;
      notes: string | null;
      items: { product_name: string; sku: string | null; quantity: number; unit_price: string; discount_percent: string; line_total: string }[];
    };

// Collapsible section wrapper with built-in toggle and header styling

function CollapsibleSection({
  title, icon: Icon, defaultOpen = false, children, headerExtra }: {
  title: string;
  icon?: React.ElementType;
  defaultOpen?: boolean;
  children: React.ReactNode;
  headerExtra?: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-2xl glass border border-white/40 dark:border-white/10 overflow-hidden">
      {/* Use a div row so we can place non-button elements alongside the toggle */}
      <div className="flex items-center justify-between px-5 py-4">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-2 text-left flex-1 min-w-0"
        >
          {Icon && <Icon className="h-4 w-4 text-violet-500 flex-shrink-0" />}
          <span className="text-base font-semibold text-slate-900 dark:text-white">{title}</span>
        </button>
        <div className="flex items-center gap-2 flex-shrink-0">
          {headerExtra}
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 transition-colors"
          >
            {open ? (
              <ChevronUp className="h-4 w-4" />
            ) : (
              <ChevronDown className="h-4 w-4" />
            )}
          </button>
        </div>
      </div>
      {open && <div className="px-5 pb-5 pt-1">{children}</div>}
    </div>
  );
}

// stage display config
const ISM_STAGE_CONFIG: Record<string, { label: string; cls: string }> = {
  new:          { label: "New",          cls: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300" },
  contacted:    { label: "Contacted",    cls: "bg-blue-100 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300" },
  engaged:      { label: "Engaged",      cls: "bg-violet-100 text-violet-700 dark:bg-violet-500/10 dark:text-violet-300" },
  quote_sent:   { label: "Quote Sent",   cls: "bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300" },
  negotiation:  { label: "Negotiation",  cls: "bg-orange-100 text-orange-700 dark:bg-orange-500/10 dark:text-orange-300" },
  closed_won:   { label: "Closed Won",   cls: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300" },
  closed_lost:  { label: "Closed Lost",  cls: "bg-red-100 text-red-700 dark:bg-red-500/10 dark:text-red-300" } };

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
  const { user, sessionTimeout } = useAuth();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lead, setLead] = useState<Lead | null>(null);
  const [requirement, setRequirement] = useState<Requirement | null>(null);
  const [interactions, setInteractions] = useState<Interaction[]>([]);
  const [tasks, setTasks] = useState<CallTask[]>([]);
  const [feedbackItems, setFeedbackItems] = useState<Array<{ id: number; rating: number | null; comment: string | null; source: string; created_at: string }>>([]);

  const [nextActionDraft, setNextActionDraft] = useState<string>("");
  const [qualificationDraft, setQualificationDraft] = useState<string>("");
  const [statusDraft, setStatusDraft] = useState<string>("");
  const [ismStageDraft, setIsmStageDraft] = useState<string>("");
  const [updateNoteDraft, setUpdateNoteDraft] = useState<string>("");
  const [languageDraft, setLanguageDraft] = useState<string>("en");
  const [billingAddressDraft, setBillingAddressDraft] = useState<string>("");
  const [pincodeDraft, setPincodeDraft] = useState<string>("");
  const [gstNumberDraft, setGstNumberDraft] = useState<string>("");
  const [updating, setUpdating] = useState(false);
  const [updateMessage, setUpdateMessage] = useState<string | null>(null);
  const [profileSaving, setProfileSaving] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);

  const [dealTimeline, setDealTimeline] = useState<DealEvent[]>([]);

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
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  // Requirements editor
  const [reqEditMode, setReqEditMode] = useState(false);
  const [reqDraft, setReqDraft] = useState<Requirement>({});
  const [reqSaving, setReqSaving] = useState(false);
  const [reqMessage, setReqMessage] = useState<string | null>(null);

  // Call history — which call row is expanded
  const [expandedCallId, setExpandedCallId] = useState<number | null>(null);

  // Quick-send quote drawer
  const [showQuoteDrawer, setShowQuoteDrawer] = useState(false);
  const [quoteItems, setQuoteItems] = useState<{ product_name_snapshot: string; sku_snapshot: string; quantity: number; unit_price: string; discount_percent: string }[]>([{ product_name_snapshot: "", sku_snapshot: "", quantity: 1, unit_price: "", discount_percent: "0" }]);
  const [quoteCurrency, setQuoteCurrency] = useState("INR");
  const [quoteValidUntil, setQuoteValidUntil] = useState("");
  const [quoteNotes, setQuoteNotes] = useState("");
  const [quoteSaving, setQuoteSaving] = useState(false);
  const [quoteMsg, setQuoteMsg] = useState<string | null>(null);
  const [quoteMsgError, setQuoteMsgError] = useState(false);

  const queryClient = useQueryClient();
  const contextQuery = useQuery({
    queryKey: ["lead-context", leadId],
    enabled: !!user && !!leadId,
    queryFn: async () => {
      const res = await apiFetch(`${API_BASE}/crm/leads/${leadId}/context`);
      if (res.status === 401) { sessionTimeout(); throw new Error("unauthorized"); }
      if (!res.ok) throw new Error("Lead not found or you do not have access to it.");
      return res.json();
    },
  });

  useEffect(() => {
    if (!user || !leadId) { setLoading(false); return; }
    if (contextQuery.isLoading) return;
    if (contextQuery.error) {
      setError(contextQuery.error instanceof Error ? contextQuery.error.message : "Failed to load Lead 360.");
      setLoading(false);
      return;
    }
    const ctx = contextQuery.data;
    if (!ctx) return;
    setLead(ctx.lead);
    if (ctx.requirement) {
      setRequirement(ctx.requirement);
      setReqDraft(ctx.requirement);
    }
    setInteractions(Array.isArray(ctx.interactions) ? ctx.interactions : []);
    setTasks(Array.isArray(ctx.tasks) ? ctx.tasks : []);

    const dealEvents: DealEvent[] = [];
    for (const q of ctx.quotes ?? []) {
      dealEvents.push({ kind: "quote", ...q });
    }
    for (const a of ctx.appointments ?? []) {
      dealEvents.push({
        kind: "appointment", id: a.id,
        date: a.appointment_time, status: a.status,
        demo_type: "Demo", products: null, location: null,
        notes: a.notes, meeting_link: null });
    }
    dealEvents.sort((a, b) => (a.date || "").localeCompare(b.date || ""));
    setDealTimeline(dealEvents);
    setFeedbackItems(Array.isArray(ctx.feedback) ? ctx.feedback : []);
    setLoading(false);
  }, [user, leadId, contextQuery.data, contextQuery.isLoading, contextQuery.error, sessionTimeout]);

  useEffect(() => {
    if (!lead) return;
    setNextActionDraft(lead.next_action || "");
    setQualificationDraft(lead.qualification_status || "");
    setStatusDraft(lead.status || "");
    setIsmStageDraft(lead.ism_stage || "");
    setUpdateNoteDraft(lead.notes || "");
    setLanguageDraft(lead.preferred_language || "en");
    setBillingAddressDraft(lead.billing_address || "");
    setPincodeDraft(lead.pincode || "");
    setGstNumberDraft(lead.gst_number || "");
  }, [lead]);

  const aiQuery = useQuery<{ summary: string }>({
    queryKey: ["ai-insights", leadId],
    enabled: !!user && !!leadId,
    queryFn: async () => {
      const res = await apiFetch(`${API_BASE}/crm/ai-insights?lead_id=${leadId}`);
      if (res.status === 401) { sessionTimeout(); throw new Error("unauthorized"); }
      if (!res.ok) throw new Error(`API returned status ${res.status}`);
      return res.json();
    },
  });

  useEffect(() => {
    if (aiQuery.isLoading) setAiLoading(true);
    else setAiLoading(false);
    if (aiQuery.error) {
      setAiError(aiQuery.error instanceof Error ? aiQuery.error.message : "AI insights fetch failed.");
      setAiSummary("");
    } else {
      setAiError(null);
      if (aiQuery.data) setAiSummary(aiQuery.data.summary || "No AI insight is available yet.");
    }
  }, [aiQuery.data, aiQuery.isLoading, aiQuery.error]);

  const fetchAiSummary = useCallback(() => {
    aiQuery.refetch();
  }, [aiQuery]);

  async function handleAddManualNote() {
    if (!user || !leadId || !noteText.trim()) return;
    setNoteSaving(true);
    setNoteMessage(null);

    try {
      const response = await apiFetch(`${API_BASE}/crm/interactions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json" },
        body: JSON.stringify({
          lead_id: leadId,
          type: "note",
          content: noteText.trim() }) });

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

  async function handleRescore() {
    if (!user || !leadId) return;
    setRescoring(true);
    try {
      const res = await apiFetch(`${API_BASE}/crm/leads/${leadId}/rescore`, {
        method: "POST"
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
    if (!user || !leadId) return;
    setEnriching(true);
    try {
      const res = await apiFetch(`${API_BASE}/crm/leads/${leadId}/enrich`, { method: "POST" });
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) throw new Error("Enrichment failed");
      const payload = await res.json();
      toast.success(payload?.message || "Enrichment complete.");
      const leadRes = await apiFetch(`${API_BASE}/crm/leads/${leadId}`, {});
      if (leadRes.ok) setLead(await leadRes.json());
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Enrichment failed.");
    } finally {
      setEnriching(false);
    }
  }

  async function handleSaveRequirements() {
    if (!user || !leadId) return;
    setReqSaving(true);
    setReqMessage(null);
    try {
      const res = await apiFetch(`${API_BASE}/requirements/${leadId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(reqDraft) });
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
        subtitle: cleanNotes(lead.notes) || "Lead record created and ready for outreach.",
        timestamp: lead.created_at,
        tone: "violet" });
    }

    interactions.forEach((interaction) => {
      items.push({
        id: `interaction-${interaction.id}`,
        title: humanizeInteractionTitle(interaction.type, interaction.status),
        subtitle: formatInteractionSubtitle(interaction.type, interaction.content),
        timestamp: interaction.started_at || interaction.created_at,
        tone: interaction.status === "completed" ? "emerald" : "blue" });
    });

    tasks.forEach((task) => {
      items.push({
        id: `task-${task.id}`,
        title: `Call task ${task.status}`,
        subtitle: task.notes || `Task #${task.id} for this lead`,
        timestamp: task.completed_at || task.scheduled_at,
        tone: task.status === "failed" ? "amber" : task.status === "completed" ? "emerald" : "blue" });
    });

    feedbackItems.forEach((fb) => {
      const stars = fb.rating ? "★".repeat(fb.rating) + "☆".repeat(5 - fb.rating) : null;
      const ratingLabel = fb.rating ? `${fb.rating}/5  ${stars}` : null;
      const sourceLabel = fb.source === "customer" ? "Customer verbal rating" : "Feedback";
      items.push({
        id: `feedback-${fb.id}`,
        title: `${sourceLabel}${ratingLabel ? ` — ${ratingLabel}` : ""}`,
        subtitle: fb.comment || undefined,
        timestamp: fb.created_at,
        tone: fb.rating && fb.rating >= 4 ? "emerald" : fb.rating && fb.rating <= 2 ? "amber" : "blue" });
    });

    return items.sort((a, b) => (b.timestamp || "").localeCompare(a.timestamp || ""));
  }, [interactions, lead, tasks, feedbackItems]);

  const callHistory = useMemo(() => {
    const callsFromInteractions = interactions
      .filter((interaction) => (interaction.type || "").toLowerCase().includes("call"))
      .map((interaction) => ({
        id: `interaction-call-${interaction.id}`,
        title: `Call interaction ${interaction.status || "logged"}`,
        subtitle: interaction.content || "Call performed",
        timestamp: interaction.started_at || interaction.created_at,
        tone: interaction.status === "completed" ? "emerald" : interaction.status === "failed" ? "amber" : "blue" }));

    const callTasks = tasks.map((task) => ({
      id: `task-${task.id}`,
      title: `Call task ${task.status}`,
      subtitle: task.notes || `Scheduled ${task.scheduled_at || "unknown"}`,
      timestamp: task.completed_at || task.scheduled_at,
      tone: task.status === "completed" ? "emerald" : task.status === "failed" ? "amber" : "blue" }));

    return [...callsFromInteractions, ...callTasks].sort((a, b) => (b.timestamp || "").localeCompare(a.timestamp || ""));
  }, [interactions, tasks]);

  const effectiveNextAction = useMemo<{ label: string | null; dueAt: string | null }>(() => {
    if (lead?.next_action) {
      return { label: lead.next_action, dueAt: lead.next_action_due_at ?? null };
    }
    const rec = extractLatestRecommendation(interactions);
    if (!rec?.next_action) return { label: null, dueAt: null };
    let dueAt: string | null = null;
    if (rec.follow_up_days && rec.follow_up_days > 0) {
      const d = new Date();
      d.setDate(d.getDate() + rec.follow_up_days);
      dueAt = d.toISOString();
    }
    const label = rec.suggested_product
      ? `${formatNextActionLabel(rec.next_action)} — ${rec.suggested_product}`
      : formatNextActionLabel(rec.next_action);
    return { label, dueAt };
  }, [lead?.next_action, lead?.next_action_due_at, interactions]);

  const mergedRequirement = useMemo<Requirement | null>(() => {
    const fallback = extractLatestQualification(interactions);
    const painFromCall = fallback?.pain_points?.filter(Boolean).join(", ") || null;
    const productFromCall = fallback?.recommendations?.suggested_product || null;
    const bant = fallback?.bant;
    const hasReq = requirement && Object.values(requirement).some((v) => v);
    if (!hasReq && !fallback) return requirement;
    return {
      use_case: requirement?.use_case || bant?.need || null,
      budget_range: requirement?.budget_range || lead?.budget_range || bant?.budget || null,
      timeline: requirement?.timeline || lead?.timeline || bant?.timeline || null,
      decision_maker: requirement?.decision_maker || lead?.decision_maker || bant?.authority || null,
      pain_points: requirement?.pain_points || painFromCall,
      required_products: requirement?.required_products || lead?.product_interest || productFromCall,
    };
  }, [interactions, requirement, lead]);

  const manualNotes = useMemo(() => interactions.filter((interaction) => (interaction.type || "").toLowerCase() === "note"), [interactions]);

  async function handleSaveProfile(fields: { city?: string | null; state?: string | null; country?: string | null; pincode?: string | null; industry?: string | null; website?: string | null }) {
    if (!user || !lead) return;
    setProfileSaving(true);
    setProfileError(null);
    try {
      const response = await apiFetch(`${API_BASE}/crm/leads/${leadId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(fields),
      });
      if (response.status === 401) { sessionTimeout(); return; }
      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to save profile");
      }
      const updated = await response.json();
      setLead((prev) => (prev ? { ...prev, ...updated } : updated));
    } catch (err) {
      setProfileError(err instanceof Error ? err.message : "Save failed");
      throw err;
    } finally {
      setProfileSaving(false);
    }
  }

  async function handleUpdateLead() {
    if (!user || !lead) return;
    setUpdating(true);
    setUpdateMessage(null);

    try {
      const response = await apiFetch(`${API_BASE}/crm/leads/${leadId}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json" },
        body: JSON.stringify({
          qualification_status: qualificationDraft || null,
          status: statusDraft || null,
          ism_stage: ismStageDraft || null,
          next_action: nextActionDraft || null,
          notes: updateNoteDraft || null,
          preferred_language: languageDraft || "en",
          billing_address: billingAddressDraft || null,
          pincode: pincodeDraft || null,
          gst_number: gstNumberDraft || null }) });

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

  async function performDeleteLead() {
    if (!user || !leadId || !lead) return;
    try {
      const response = await apiFetch(`${API_BASE}/crm/leads/${leadId}`, {
        method: "DELETE"
      });
      if (response.status === 401) { sessionTimeout(); return; }
      if (!response.ok) throw new Error("Failed to delete lead");
      window.location.href = "/leads";
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Delete failed");
    }
  }

  function handleDeleteLead() {
    setShowDeleteConfirm(true);
  }

  const CALL_STATUS_LABELS: Record<string, string> = {
    initiated:    "Calling...",
    ringing:      "Ringing...",
    "in-progress":"In conversation",
    completed:    "Call completed",
    "no-answer":  "No answer",
    busy:         "Line busy",
    failed:       "Call failed",
    canceled:     "Call canceled" };
  const TERMINAL_STATUSES = new Set(["completed", "no-answer", "busy", "failed", "canceled"]);

  useEffect(() => {
    if (!callInteractionId ) return;
    const interval = setInterval(async () => {
      try {
        const res = await apiFetch(`${API_BASE}/call-status?interaction_id=${callInteractionId}`, {
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
  }, [callInteractionId, user]);

  function openQuoteDrawer() {
    // Pre-populate one item from requirement.required_products if available
    const products = requirement?.required_products;
    if (products && products.trim()) {
      const names = products.split(",").map(s => s.trim()).filter(Boolean);
      setQuoteItems(names.map(n => ({ product_name_snapshot: n, sku_snapshot: "", quantity: 1, unit_price: "", discount_percent: "0" })));
    } else {
      setQuoteItems([{ product_name_snapshot: "", sku_snapshot: "", quantity: 1, unit_price: "", discount_percent: "0" }]);
    }
    const d = new Date(); d.setDate(d.getDate() + 15);
    setQuoteValidUntil(d.toISOString().split("T")[0]);
    setQuoteNotes("");
    setQuoteMsg(null);
    setShowQuoteDrawer(true);
  }

  async function handleQuickSendQuote(send: boolean) {
    if (!user || !lead) return;
    const validItems = quoteItems.filter(i => i.product_name_snapshot.trim() && i.unit_price);
    if (!validItems.length) { setQuoteMsg("Add at least one item with a name and price."); setQuoteMsgError(true); return; }
    setQuoteSaving(true); setQuoteMsg(null);
    try {
      const h = { "Content-Type": "application/json" };
      const createRes = await apiFetch(`${API_BASE}/quotes`, {
        method: "POST",        body: JSON.stringify({
          lead_id: lead.id, currency: quoteCurrency,
          valid_until: quoteValidUntil || null,
          notes: quoteNotes || null,
          items: validItems.map(i => ({ ...i, quantity: Number(i.quantity), unit_price: parseFloat(i.unit_price) || 0, discount_percent: parseFloat(i.discount_percent) || 0 })) }) });
      if (createRes.status === 401) { sessionTimeout(); return; }
      if (!createRes.ok) throw new Error((await createRes.json().catch(() => ({}))).detail || "Failed to create quote");
      const quote = await createRes.json();
      if (send) {
        const sendRes = await apiFetch(`${API_BASE}/quotes/${quote.id}/send`, {
          method: "POST",          body: JSON.stringify({ channels: ["email"], subject: `Quote for ${lead.name}`, message: "" }) });
        if (!sendRes.ok) throw new Error("Quote created but failed to send");
        setQuoteMsg(`Quote ${quote.quote_number} sent to ${lead.email || lead.name}`);
      } else {
        setQuoteMsg(`Quote ${quote.quote_number} saved as draft`);
      }
      setQuoteMsgError(false);
      setTimeout(() => setShowQuoteDrawer(false), 2000);
    } catch (e) { setQuoteMsg(e instanceof Error ? e.message : "Failed"); setQuoteMsgError(true); }
    finally { setQuoteSaving(false); }
  }

  async function handleCall() {
    if (!user || !lead?.normalized_phone) return;

    setCallMessage(null);
    setCallInteractionId(null);
    setCallStatus(null);
    try {
      const response = await apiFetch(
        `${API_BASE}/make-call?to=${encodeURIComponent(lead.normalized_phone)}&lead_id=${lead.id}`,
        {
          method: "POST"
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
    if (!user || !callInteractionId || !transferTo.trim()) return;
    setTransferring(true);
    setTransferResult(null);
    try {
      const params = new URLSearchParams({
        interaction_id: String(callInteractionId),
        transfer_to: transferTo.trim() });
      if (isrName.trim()) params.set("isr_name", isrName.trim());
      const res = await apiFetch(`${API_BASE}/warm-transfer?${params}`, {
        method: "POST"
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

      {/* Quick Quote button */}
      <div className="flex justify-end">
        <button
          onClick={openQuoteDrawer}
          className="inline-flex items-center gap-2 rounded-xl bg-violet-600 hover:bg-violet-700 px-4 py-2.5 text-sm font-semibold text-white transition-colors shadow-sm"
        >
          <FileText className="h-4 w-4" /> Send Quote
        </button>
      </div>

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
      <Dialog open={showTransferModal} onOpenChange={setShowTransferModal}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <UserCheck className="h-5 w-5 text-amber-500" />
              Transfer to Human ISR
            </DialogTitle>
            <DialogDescription>
              The AI will be bridged into a conference. The ISR will join immediately.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1">
              <Label htmlFor="isr-phone">ISR phone</Label>
              <Input
                id="isr-phone"
                value={transferTo}
                onChange={(e) => setTransferTo(e.target.value)}
                placeholder="+919876543210"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="isr-name">ISR name (optional)</Label>
              <Input
                id="isr-name"
                value={isrName}
                onChange={(e) => setIsrName(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowTransferModal(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleWarmTransfer}
              disabled={!transferTo.trim() || transferring}
              className="bg-amber-500 hover:bg-amber-600"
            >
              {transferring ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <UserCheck className="mr-2 h-4 w-4" />}
              Transfer Now
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog open={showDeleteConfirm} onOpenChange={setShowDeleteConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete lead?</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete &quot;{lead.name}&quot;? This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={performDeleteLead} className="bg-red-600 hover:bg-red-700">
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

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

      {/* Journey */}
      {dealTimeline.length > 0 && (
        <div className="rounded-2xl border border-white/40 dark:border-white/10 glass overflow-hidden">
          <div className="flex items-center gap-2 px-5 py-4 border-b border-slate-100 dark:border-white/10">
            <TrendingUp className="h-4 w-4 text-violet-500 flex-shrink-0" />
            <span className="text-base font-semibold text-slate-900 dark:text-white">Journey</span>
            <span className="ml-auto rounded-full bg-violet-100 dark:bg-violet-500/10 px-2.5 py-0.5 text-xs font-bold text-violet-700 dark:text-violet-300">
              {dealTimeline.length} event{dealTimeline.length !== 1 ? "s" : ""}
            </span>
          </div>
          <div className="px-5 py-4 space-y-4">
            {dealTimeline.map((ev, i) => (
              <div key={`${ev.kind}-${ev.id}`} className="flex gap-3">
                {/* Timeline spine */}
                <div className="flex flex-col items-center">
                  <div className={`flex h-8 w-8 items-center justify-center rounded-full flex-shrink-0 ${
                    ev.kind === "appointment"
                      ? "bg-blue-100 dark:bg-blue-500/15"
                      : ev.status === "accepted"
                      ? "bg-emerald-100 dark:bg-emerald-500/15"
                      : ev.status === "rejected"
                      ? "bg-red-100 dark:bg-red-500/15"
                      : ev.status === "sent" || ev.status === "negotiation"
                      ? "bg-amber-100 dark:bg-amber-500/15"
                      : "bg-slate-100 dark:bg-slate-800"
                  }`}>
                    {ev.kind === "appointment" ? (
                      <Calendar className="h-4 w-4 text-blue-500" />
                    ) : ev.status === "accepted" ? (
                      <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                    ) : ev.status === "rejected" ? (
                      <XCircle className="h-4 w-4 text-red-400" />
                    ) : (
                      <FileText className="h-4 w-4 text-amber-500" />
                    )}
                  </div>
                  {i < dealTimeline.length - 1 && (
                    <div className="w-px flex-1 bg-slate-200 dark:bg-white/10 mt-1" />
                  )}
                </div>

                {/* Card */}
                <div className="flex-1 pb-2">
                  {ev.kind === "appointment" ? (
                    <div className="rounded-xl border border-slate-200 dark:border-white/10 bg-white/70 dark:bg-slate-900/40 p-3 space-y-1.5">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-semibold text-slate-900 dark:text-white">
                          {ev.demo_type && ev.demo_type.toLowerCase() !== "demo"
                            ? `${ev.demo_type} Demo Scheduled`
                            : "Demo Scheduled"}
                        </span>
                        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                          ev.status === "completed"
                            ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300"
                            : ev.status === "cancelled"
                            ? "bg-red-100 text-red-600 dark:bg-red-500/10 dark:text-red-300"
                            : "bg-blue-100 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300"
                        }`}>
                          {ev.status}
                        </span>
                      </div>
                      {ev.products && (
                        <div className="flex items-center gap-1.5 text-xs text-slate-600 dark:text-slate-400">
                          <span className="font-medium text-slate-700 dark:text-slate-300">Products:</span>
                          <span>{ev.products}</span>
                        </div>
                      )}
                      {ev.location && (
                        <div className="flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400">
                          <MapPin className="h-3 w-3 flex-shrink-0" />
                          {ev.location}
                        </div>
                      )}
                      {ev.meeting_link && (
                        <a href={ev.meeting_link} target="_blank" rel="noreferrer"
                          className="inline-block text-xs text-violet-600 hover:underline dark:text-violet-400">
                          Join meeting →
                        </a>
                      )}
                      {ev.date && (
                        <div className="text-xs text-slate-400 dark:text-slate-500">
                          {new Date(ev.date).toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" })}
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="rounded-xl border border-slate-200 dark:border-white/10 bg-white/70 dark:bg-slate-900/40 p-3 space-y-2">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-semibold text-slate-900 dark:text-white">
                          {ev.quote_number}
                        </span>
                        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                          ev.status === "accepted"   ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300" :
                          ev.status === "rejected"   ? "bg-red-100 text-red-600 dark:bg-red-500/10 dark:text-red-300" :
                          ev.status === "sent"       ? "bg-blue-100 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300" :
                          ev.status === "negotiation"? "bg-violet-100 text-violet-700 dark:bg-violet-500/10 dark:text-violet-300" :
                                                       "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400"
                        }`}>
                          {ev.status}
                        </span>
                      </div>

                      {/* Line items */}
                      {ev.items.length > 0 && (
                        <div className="space-y-1">
                          {ev.items.map((item, j) => (
                            <div key={j} className="flex items-center justify-between text-xs text-slate-600 dark:text-slate-400">
                              <span className="font-medium text-slate-700 dark:text-slate-300 truncate max-w-[60%]">
                                {item.product_name}
                                {item.sku ? <span className="text-slate-400 ml-1">({item.sku})</span> : null}
                              </span>
                              <span className="text-right tabular-nums whitespace-nowrap">
                                {item.quantity} ×{" "}
                                {new Intl.NumberFormat("en-IN", { style: "currency", currency: ev.currency, maximumFractionDigits: 0 }).format(Number(item.unit_price))}
                                {Number(item.discount_percent) > 0 && (
                                  <span className="text-emerald-600 dark:text-emerald-400 ml-1">−{item.discount_percent}%</span>
                                )}
                                {" = "}
                                <span className="font-semibold text-slate-800 dark:text-slate-100">
                                  {new Intl.NumberFormat("en-IN", { style: "currency", currency: ev.currency, maximumFractionDigits: 0 }).format(Number(item.line_total))}
                                </span>
                              </span>
                            </div>
                          ))}
                          <div className="flex justify-between text-xs font-bold text-slate-800 dark:text-slate-100 border-t border-slate-100 dark:border-white/10 pt-1 mt-1">
                            <span>Total</span>
                            <span>{new Intl.NumberFormat("en-IN", { style: "currency", currency: ev.currency, maximumFractionDigits: 0 }).format(Number(ev.total_amount ?? 0))}</span>
                          </div>
                        </div>
                      )}

                      {/* Key timestamps */}
                      <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-slate-400 dark:text-slate-500">
                        {ev.sent_at && <span>Sent: {new Date(ev.sent_at).toLocaleDateString("en-IN", { day: "2-digit", month: "short" })}</span>}
                        {ev.opened_at && <span>Opened: {new Date(ev.opened_at).toLocaleDateString("en-IN", { day: "2-digit", month: "short" })}</span>}
                        {ev.accepted_at && <span className="text-emerald-500">Accepted: {new Date(ev.accepted_at).toLocaleDateString("en-IN", { day: "2-digit", month: "short" })}</span>}
                        {ev.rejected_at && <span className="text-red-400">Rejected: {new Date(ev.rejected_at).toLocaleDateString("en-IN", { day: "2-digit", month: "short" })}</span>}
                        {ev.valid_until && !ev.accepted_at && !ev.rejected_at && (
                          <span>Valid until: {new Date(ev.valid_until).toLocaleDateString("en-IN", { day: "2-digit", month: "short" })}</span>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
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
            <option value="unqualified">Unqualified</option>
            <option value="contacted">Contacted</option>
            <option value="qualified">Qualified</option>
            <option value="follow_up">Follow up</option>
            <option value="proposal">Proposal</option>
            <option value="won">Won</option>
            <option value="lost">Lost</option>
            <option value="not_interested">Not interested</option>
            <option value="disqualified">Disqualified</option>
          </select>

          <select
            value={statusDraft}
            onChange={(event) => setStatusDraft(event.target.value)}
            className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
            title="Lead lifecycle status — gates call-now (closed_* blocks calls)"
          >
            <option value="">Lead status</option>
            <option value="new">New</option>
            <option value="contacted">Contacted</option>
            <option value="engaged">Engaged</option>
            <option value="closed_won">Closed won</option>
            <option value="closed_lost">Closed lost</option>
            <option value="do_not_call">Do not call</option>
          </select>

          <select
            value={ismStageDraft}
            onChange={(event) => setIsmStageDraft(event.target.value)}
            className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40"
            title="ISM automation stage — drives outreach channel picks"
          >
            <option value="">ISM stage</option>
            <option value="new">New</option>
            <option value="contacted">Contacted</option>
            <option value="engaged">Engaged</option>
            <option value="quoted">Quoted</option>
            <option value="negotiation">Negotiation</option>
            <option value="closed_won">Closed won</option>
            <option value="closed_lost">Closed lost</option>
            <option value="nurture_pause">Nurture pause</option>
          </select>
        </div>

        <div className="mt-3 grid grid-cols-1 gap-4 md:grid-cols-2">
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

        {/* B2B billing details */}
        <div className="mt-4 border-t border-slate-200 dark:border-white/10 pt-4">
          <p className="text-xs font-semibold uppercase tracking-widest text-slate-400 mb-3">B2B Billing — shown on quotes</p>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            <input value={billingAddressDraft} onChange={(e) => setBillingAddressDraft(e.target.value)}
              placeholder="Billing address"
              className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40" />
            <input value={pincodeDraft} onChange={(e) => setPincodeDraft(e.target.value)}
              placeholder="Pincode / ZIP"
              className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40" />
            <input value={gstNumberDraft} onChange={(e) => setGstNumberDraft(e.target.value)}
              placeholder="GST / Tax number"
              className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-violet-400 dark:border-white/10 dark:bg-slate-900/40" />
          </div>
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
            pincode={lead.pincode}
            industry={lead.industry}
            website={lead.website}
            notes={cleanNotes(lead.notes)}
            saving={profileSaving}
            saveError={profileError}
            onSave={handleSaveProfile}
          />
          <NextActionCard nextAction={effectiveNextAction.label} dueAt={effectiveNextAction.dueAt} />

          <CollapsibleSection title="Explain Next Action" icon={Zap}>
            <ExplainNextAction
              leadId={leadId}
              fallbackRecommendation={extractLatestRecommendation(interactions)}
              onSessionTimeout={sessionTimeout}
            />
          </CollapsibleSection>

          <CollapsibleSection title="Agent Actions Timeline" icon={Brain}>
            <AgentActionsTimeline leadId={leadId} onSessionTimeout={sessionTimeout} />
          </CollapsibleSection>

          {/* Waterfall enrichment pipeline */}
          <CollapsibleSection title="Enrichment Trace" icon={Zap}>
            <EnrichmentTrace
              leadId={leadId}
              onSessionTimeout={sessionTimeout}
            />
          </CollapsibleSection>

          {/* Predictive call windows */}
          <CollapsibleSection title="Best Call Times" icon={RefreshCw}>
            <BestCallTimes
              leadId={leadId}
              onSessionTimeout={sessionTimeout}
            />
          </CollapsibleSection>

          {/* Sales Intelligence */}
          {(lead.budget_range || lead.timeline || lead.decision_maker) && (
            <CollapsibleSection title="Sales Intelligence" icon={TrendingUp}>
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
            </CollapsibleSection>
          )}
        </div>

        <div className="space-y-6 xl:col-span-2">
          <CollapsibleSection title="Qualification" icon={UserCheck}>
            <QualificationCard qualificationStatus={lead.qualification_status} requirement={mergedRequirement} />
          </CollapsibleSection>

          {/* Enhanced ICP Score Card */}
          <CollapsibleSection title="ICP Score" icon={Target}>
            <div className="flex flex-wrap gap-2 mb-4">
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
          </CollapsibleSection>

          {/* Requirements Editor */}
          <CollapsibleSection title="Requirements" icon={Edit3}>
            <div className="flex items-center justify-end mb-4">
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
          </CollapsibleSection>

          <CollapsibleSection title="Add Manual Note" icon={Edit3}>
            <p className="mb-3 text-sm text-slate-500 dark:text-slate-400">Keep your team in sync by quickly logging insights.</p>
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
          </CollapsibleSection>

          <CollapsibleSection title="Call Action History" icon={Zap}>
            {callHistory.length === 0 ? (
              <p className="text-sm text-slate-500 dark:text-slate-400">No call activities yet for this lead.</p>
            ) : (
              <ul className="space-y-2">
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
          </CollapsibleSection>

          <CollapsibleSection
            title="AI Insight Summary"
            icon={Brain}
            headerExtra={
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); fetchAiSummary(); }}
                disabled={aiLoading}
                className="ml-2 rounded-lg border border-slate-200 px-2.5 py-0.5 text-xs font-semibold text-slate-600 hover:bg-slate-100 dark:border-white/10 dark:text-slate-300 disabled:opacity-50"
              >
                {aiLoading ? "Refreshing..." : "Refresh"}
              </button>
            }
          >
            {aiError && <p className="mb-2 text-sm font-medium text-amber-600 dark:text-amber-300">{aiError}</p>}
            <p className="text-sm text-slate-600 dark:text-slate-300">{aiSummary || "No summary available yet. Click Refresh to fetch AI insights."}</p>
          </CollapsibleSection>

          <CollapsibleSection title="Interaction Timeline" icon={TrendingUp}>
            <InteractionTimeline items={timelineItems} />
          </CollapsibleSection>

          {/* Per-call expandable history with transcript + coach score */}
          {(() => {
            // Only show actual call rows. Sibling events (call_completed, call_summary) get merged in below so each call renders once.
            const callInteractions = interactions.filter(
              i => (i.type || "").toLowerCase() === "call"
            );
            // Build a lookup of summaries keyed by their nearest preceding call. call_summary rows share a timestamp with (or come right after) the call they describe, so matching by lead_id + closest-earlier started_at is good enough for a display hint.
            const summaryByCallId = new Map<number, string>();
            const callSummaries = interactions
              .filter(i => (i.type || "").toLowerCase() === "call_summary" && i.content)
              .slice()
              .sort((a, b) => {
                const at = new Date(a.started_at || a.created_at || 0).getTime();
                const bt = new Date(b.started_at || b.created_at || 0).getTime();
                return at - bt;
              });
            for (const summary of callSummaries) {
              const sTime = new Date(summary.started_at || summary.created_at || 0).getTime();
              // Find the most recent call whose started_at is <= summary time.
              let best: Interaction | null = null;
              let bestTime = -Infinity;
              for (const call of callInteractions) {
                const cTime = new Date(call.started_at || call.created_at || 0).getTime();
                if (cTime <= sTime && cTime > bestTime) {
                  best = call;
                  bestTime = cTime;
                }
              }
              if (best && best.id != null && !summaryByCallId.has(best.id)) {
                const formatted = formatInteractionSubtitle(summary.type, summary.content);
                summaryByCallId.set(best.id, formatted || summary.content!);
              }
            }
            if (!callInteractions.length) return null;
            return (
              <CollapsibleSection title={`Call History (${callInteractions.length})`} icon={Phone} defaultOpen={callInteractions.length <= 3}>
                <div className="space-y-2">
                  {callInteractions.slice().reverse().map(ci => {
                    const isOpen = expandedCallId === ci.id;
                    const hasTranscript = ci.transcript && ci.transcript.trim().length > 10;
                    const dateLabel = ci.started_at || ci.created_at
                      ? new Date(ci.started_at || ci.created_at || "").toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" })
                      : "Unknown date";
                    const durLabel = ci.recording_duration ? `${Math.floor(ci.recording_duration / 60)}m ${ci.recording_duration % 60}s` : null;
                    const dirLabel = ci.direction === "inbound" ? "Inbound" : ci.direction === "outbound" ? "Outbound" : null;
                    const statusColor = ci.status === "completed" ? "text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-500/10" : ci.status === "failed" ? "text-red-500 bg-red-50 dark:bg-red-500/10" : "text-slate-500 bg-slate-100 dark:bg-white/5";
                    const summary = summaryByCallId.get(ci.id);
                    return (
                      <div key={ci.id} className="rounded-xl border border-white/10 bg-white/5 overflow-hidden">
                        <button
                          type="button"
                          onClick={() => setExpandedCallId(isOpen ? null : ci.id)}
                          className="w-full flex items-center justify-between px-4 py-3 text-sm hover:bg-white/5 transition-colors"
                        >
                          <div className="flex items-center gap-3 min-w-0">
                            <Phone className="h-3.5 w-3.5 text-violet-400 flex-shrink-0" />
                            {dirLabel && <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider flex-shrink-0">{dirLabel}</span>}
                            <span className="text-slate-300 truncate">{dateLabel}</span>
                            {durLabel && <span className="text-slate-500 text-xs flex-shrink-0">{durLabel}</span>}
                            {hasTranscript && <span className="text-[10px] text-violet-400 font-medium flex-shrink-0">transcript</span>}
                            {ci.recording_url && <span className="text-[10px] text-blue-400 font-medium flex-shrink-0">audio</span>}
                          </div>
                          <div className="flex items-center gap-2 flex-shrink-0">
                            {ci.status && <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${statusColor}`}>{ci.status}</span>}
                            {isOpen ? <ChevronUp className="h-3.5 w-3.5 text-slate-500" /> : <ChevronDown className="h-3.5 w-3.5 text-slate-500" />}
                          </div>
                        </button>
                        {isOpen && (
                          <div className="px-4 pb-4 space-y-4 border-t border-white/10 pt-4">
                            {summary && (
                              <div className="rounded-lg border border-violet-500/20 bg-violet-500/5 p-3">
                                <p className="text-[10px] font-bold uppercase tracking-widest text-violet-400 mb-1.5">AI Summary</p>
                                <p className="text-xs text-slate-300 leading-relaxed whitespace-pre-wrap">{summary}</p>
                              </div>
                            )}
                            {ci.recording_url ? (
                              <WaveformPlayer
                                interactionId={ci.id}
                                transcript={ci.transcript}
                                duration={ci.recording_duration}
                              />
                            ) : hasTranscript
                              ? <TranscriptPanel transcript={ci.transcript} />
                              : <p className="text-xs text-slate-500 italic">No transcript recorded for this call.</p>
                            }
                            <SalesCoachPanel
                              interactionId={ci.id}
                              onSessionTimeout={sessionTimeout}
                            />
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </CollapsibleSection>
            );
          })()}

          {/* Competitor signals detected on calls */}
          <CollapsibleSection title="Competitor Signals" icon={Target}>
            <CompetitorBadges
              leadId={leadId}
              onSessionTimeout={sessionTimeout}
            />
          </CollapsibleSection>

          {/* WhatsApp conversation thread */}
          <CollapsibleSection title="WhatsApp Thread" icon={UserCheck}>
            <WhatsAppThread
              leadId={leadId}
              onSessionTimeout={sessionTimeout}
            />
          </CollapsibleSection>

          {/* Email thread */}
          <CollapsibleSection title="Email Thread" icon={UserCheck}>
            <EmailThread
              leadId={leadId}
              leadEmail={lead?.email}
              onSessionTimeout={sessionTimeout}
            />
          </CollapsibleSection>
        </div>
      </div>

      {/* Quick-send Quote drawer (slide-over) */}
      {showQuoteDrawer && (
        <div className="fixed inset-0 z-50 flex">
          {/* Backdrop */}
          <div className="flex-1 bg-slate-950/60 backdrop-blur-sm" onClick={() => !quoteSaving && setShowQuoteDrawer(false)} />
          {/* Panel */}
          <div className="w-full max-w-lg bg-slate-900 border-l border-white/10 flex flex-col overflow-hidden">
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-white/10">
              <div>
                <h2 className="text-lg font-bold text-white">Send Quote</h2>
                <p className="text-xs text-slate-400">{lead.name}{lead.email ? ` · ${lead.email}` : ""}</p>
              </div>
              <button onClick={() => setShowQuoteDrawer(false)} disabled={quoteSaving} className="text-slate-400 hover:text-white transition-colors">
                <X className="h-5 w-5" />
              </button>
            </div>

            {/* Body */}
            <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
              {/* Currency + Valid Until */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-slate-400 mb-1">Currency</label>
                  <select
                    value={quoteCurrency}
                    onChange={e => setQuoteCurrency(e.target.value)}
                    className="w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-violet-500"
                  >
                    {["INR", "USD", "EUR", "GBP", "AED", "SGD"].map(c => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-400 mb-1">Valid Until</label>
                  <input
                    type="date"
                    value={quoteValidUntil}
                    onChange={e => setQuoteValidUntil(e.target.value)}
                    className="w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-violet-500"
                  />
                </div>
              </div>

              {/* Line items */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <label className="text-xs font-semibold text-slate-400">Line Items</label>
                  <button
                    type="button"
                    onClick={() => setQuoteItems(prev => [...prev, { product_name_snapshot: "", sku_snapshot: "", quantity: 1, unit_price: "", discount_percent: "0" }])}
                    className="flex items-center gap-1 text-xs text-violet-400 hover:text-violet-300 transition-colors"
                  >
                    <Plus className="h-3.5 w-3.5" /> Add item
                  </button>
                </div>
                <div className="space-y-2">
                  {quoteItems.map((item, idx) => (
                    <div key={idx} className="grid grid-cols-[1fr_80px_90px_80px_28px] gap-1.5 items-center">
                      <input
                        placeholder="Product name"
                        value={item.product_name_snapshot}
                        onChange={e => setQuoteItems(prev => prev.map((it, i) => i === idx ? { ...it, product_name_snapshot: e.target.value } : it))}
                        className="rounded-lg border border-white/10 bg-white/5 px-2.5 py-1.5 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:ring-1 focus:ring-violet-500"
                      />
                      <input
                        type="number" min="1" placeholder="Qty"
                        value={item.quantity}
                        onChange={e => setQuoteItems(prev => prev.map((it, i) => i === idx ? { ...it, quantity: Number(e.target.value) } : it))}
                        className="rounded-lg border border-white/10 bg-white/5 px-2.5 py-1.5 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:ring-1 focus:ring-violet-500"
                      />
                      <input
                        type="number" min="0" step="0.01" placeholder="Unit price"
                        value={item.unit_price}
                        onChange={e => setQuoteItems(prev => prev.map((it, i) => i === idx ? { ...it, unit_price: e.target.value } : it))}
                        className="rounded-lg border border-white/10 bg-white/5 px-2.5 py-1.5 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:ring-1 focus:ring-violet-500"
                      />
                      <input
                        type="number" min="0" max="100" placeholder="Disc%"
                        value={item.discount_percent}
                        onChange={e => setQuoteItems(prev => prev.map((it, i) => i === idx ? { ...it, discount_percent: e.target.value } : it))}
                        className="rounded-lg border border-white/10 bg-white/5 px-2.5 py-1.5 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:ring-1 focus:ring-violet-500"
                      />
                      <button
                        type="button"
                        onClick={() => setQuoteItems(prev => prev.length > 1 ? prev.filter((_, i) => i !== idx) : prev)}
                        className="text-slate-600 hover:text-red-400 transition-colors"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  ))}
                  <div className="grid grid-cols-[1fr_80px_90px_80px_28px] gap-1.5 px-0.5">
                    <span className="text-[10px] text-slate-600">Name</span>
                    <span className="text-[10px] text-slate-600">Qty</span>
                    <span className="text-[10px] text-slate-600">Unit price</span>
                    <span className="text-[10px] text-slate-600">Disc %</span>
                    <span />
                  </div>
                </div>
              </div>

              {/* Live total */}
              {(() => {
                const total = quoteItems.reduce((sum, it) => {
                  const price = parseFloat(it.unit_price) || 0;
                  const disc  = parseFloat(it.discount_percent) || 0;
                  return sum + (price * it.quantity * (1 - disc / 100));
                }, 0);
                return total > 0 ? (
                  <div className="flex justify-end">
                    <span className="text-sm font-bold text-violet-400">{quoteCurrency} {total.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                  </div>
                ) : null;
              })()}

              {/* Notes */}
              <div>
                <label className="block text-xs font-semibold text-slate-400 mb-1">Notes / Terms</label>
                <textarea
                  rows={3}
                  value={quoteNotes}
                  onChange={e => setQuoteNotes(e.target.value)}
                  placeholder="Payment terms, delivery notes..."
                  className="w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:ring-2 focus:ring-violet-500 resize-none"
                />
              </div>

              {/* Status message */}
              {quoteMsg && (
                <p className={`text-sm font-medium ${quoteMsgError ? "text-red-400" : "text-emerald-400"}`}>{quoteMsg}</p>
              )}
            </div>

            {/* Footer actions */}
            <div className="px-6 py-4 border-t border-white/10 flex gap-2">
              <button
                onClick={() => handleQuickSendQuote(false)}
                disabled={quoteSaving}
                className="flex-1 rounded-xl border border-white/10 bg-white/5 py-2.5 text-sm font-semibold text-slate-300 hover:text-white hover:bg-white/10 transition-colors disabled:opacity-40"
              >
                {quoteSaving ? <Loader2 className="h-4 w-4 animate-spin inline mr-1" /> : null}
                Save Draft
              </button>
              <button
                onClick={() => handleQuickSendQuote(true)}
                disabled={quoteSaving || !lead.email}
                title={!lead.email ? "Lead has no email address" : undefined}
                className="flex-1 rounded-xl bg-violet-600 hover:bg-violet-700 py-2.5 text-sm font-semibold text-white transition-colors disabled:opacity-40 flex items-center justify-center gap-2"
              >
                {quoteSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                Send via Email
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
