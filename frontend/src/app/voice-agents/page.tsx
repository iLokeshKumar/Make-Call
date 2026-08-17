"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import UserChip from "@/components/UserChip";
import type { ElementType } from "react";
import {
  Activity,
  AlertCircle,
  BarChart2,
  Bot,
  Braces,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock,
  GitBranch,
  Layers,
  Loader2,
  MessageSquare,
  Phone,
  PhoneCall,
  PhoneForwarded,
  Plug,
  Plus,
  Save,
  Settings2,
  Shield,
  Sliders,
  Sparkles,
  TerminalSquare,
  Trash2,
  Wrench,
  X,
  XCircle,
  Zap,
} from "lucide-react";
import clsx from "clsx";
import { useAuth } from "@/context/AuthContext";
import { apiFetch } from "@/utils/apiFetch";
import GraphEditor from "@/components/voice-agents/graph-editor/GraphEditor";
import CallFeaturesEditor, {
  type CallFeaturesConfig,
} from "@/components/voice-agents/CallFeaturesEditor";
import AgentChatPanel from "@/components/voice-agents/AgentChatPanel";
// Shared capabilities payload types / provider labels / chip styles — the same
// truth the Settings → Connectors 'Effective capabilities' card renders.
import {
  PROVIDER_LABELS,
  providerChipCls,
  type CapabilitiesSummary,
  type SummaryCapability,
} from "@/components/settings/MCPConnectionsTab";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  (typeof window !== "undefined"
    ? window.location.hostname.includes("ngrok-free.dev")
      ? `${window.location.protocol}//${window.location.host}`
      : `${window.location.protocol}//127.0.0.1:6060`
    : "http://127.0.0.1:6060");

type Runtime = {
  id?: number;
  stt_provider?: string | null;
  llm_provider?: string | null;
  tts_provider?: string | null;
  telephony_engine?: string | null;
  ai_verbosity?: string | null;
  language?: string | null;
  max_call_duration_seconds?: number | null;
  silence_reengage_seconds?: number | null;
  runtime_json?: Record<string, unknown>;
};

type PromptVersion = {
  id: number;
  version: number;
  name: string;
  system_prompt: string;
  instructions?: string | null;
  is_active: boolean;
  traffic_split?: number | null;
  created_at?: string;
};

type Agent = {
  id: number;
  name: string;
  description?: string | null;
  status: string;
  is_default: boolean;
  agent_type: string;
};

type AgentPayload = {
  agent: Agent;
  runtime: Runtime;
  active_prompt: PromptVersion;
};

type ExecutionEvent = {
  id: number;
  event_type: string;
  provider?: string | null;
  summary?: string | null;
  payload: Record<string, unknown>;
  created_at: string;
};

type ToolConfig = {
  id: number;
  name: string;
  description?: string | null;
  tool_type: string;
  http_method?: string | null;
  url?: string | null;
  is_active: boolean;
};

type ExtractionTemplate = {
  id: number;
  name: string;
  instructions?: string | null;
  extraction_schema: Record<string, unknown>;
  is_active: boolean;
};

type EvalStats = {
  total: number;
  evaluated: number;
  pass_rate: number | null;
  avg_overall: number | null;
  axis_averages: Record<string, number | null>;
};

type ExtractionResult = {
  id: number;
  template_id: number | null;
  template_name: string;
  interaction_id: number | null;
  output_json: Record<string, unknown>;
  status: string;
  created_at: string;
};

const tabs = [
  { id: "overview", label: "Overview", Icon: Bot },
  { id: "prompts", label: "Prompts", Icon: Sparkles },
  { id: "runtime", label: "Voice & Runtime", Icon: Settings2 },
  { id: "chat", label: "Chat with Agent", Icon: MessageSquare },
  { id: "web_call", label: "Web Call", Icon: PhoneCall },
  { id: "call", label: "Call Features", Icon: PhoneCall },
  { id: "ivr", label: "IVR", Icon: Phone },
  { id: "tools", label: "Tools", Icon: Wrench },
  { id: "extractions", label: "Extractions", Icon: Braces },
  { id: "dispositions", label: "Dispositions", Icon: CheckCircle2 },
  { id: "graph", label: "Graph", Icon: GitBranch },
  { id: "executions", label: "Executions", Icon: Activity },
] as const;

type TabId = (typeof tabs)[number]["id"];

// ─── Call readiness — what connected integrations unlock for calls ─────────────
//
// Compact form of the Settings → Connectors 'Effective capabilities' card: the
// bare-account banner, the gated-Zoom note, and one row per capability with
// 'Unlock:' suggestions. Types / labels / chip styles are imported from
// MCPConnectionsTab so both pages share one truth (same summary payload).
// This page has no connector cards, so every action deep-links to
// Settings → Connectors instead of auto-connecting.

// One capability per row: status dot + label + provider chips + unlock hints.
function ReadinessRow({ cap }: { cap: SummaryCapability }) {
  const dot =
    cap.status === "available"
      ? "bg-green-500"
      : cap.status === "degraded"
        ? "bg-amber-500"
        : "bg-slate-300 dark:bg-slate-600";
  const statusText =
    cap.status === "available" ? "Available" : cap.status === "degraded" ? "Needs attention" : "Not connected";
  const statusCls =
    cap.status === "available"
      ? "text-green-600 dark:text-green-400"
      : cap.status === "degraded"
        ? "text-amber-600 dark:text-amber-400"
        : "text-slate-400 dark:text-slate-500";

  return (
    <div className="flex items-start gap-2.5">
      <span className={`mt-1 h-2 w-2 rounded-full flex-shrink-0 ${dot}`} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs font-semibold text-slate-700 dark:text-slate-300">{cap.label}</span>
          <span className={`text-[10px] font-semibold uppercase tracking-wide ${statusCls}`}>{statusText}</span>
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          {cap.providers.map((p) => (
            <span
              key={p.provider}
              title={p.note ?? undefined}
              className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium border ${providerChipCls(p.state)}`}
            >
              {p.state === "connected" && <CheckCircle2 className="h-3 w-3 flex-shrink-0" />}
              {p.state === "degraded" && <AlertCircle className="h-3 w-3 flex-shrink-0" />}
              {p.state === "disconnected" && <span className="h-1.5 w-1.5 rounded-full bg-slate-300 dark:bg-slate-600 flex-shrink-0" />}
              {p.label}
            </span>
          ))}
          {cap.status === "unavailable" && cap.suggest.length > 0 && (
            <span className="inline-flex items-center gap-1">
              <span className="text-[10px] font-medium uppercase tracking-wide text-slate-400 dark:text-slate-500">Unlock:</span>
              {cap.suggest.map((pid) => (
                <a
                  key={pid}
                  href="/settings?section=mcp_connections"
                  title={`Connect ${PROVIDER_LABELS[pid] ?? pid} in Settings`}
                  className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-violet-50 dark:bg-violet-900/20 text-violet-700 dark:text-violet-300 border border-violet-200 dark:border-violet-800/60 hover:bg-violet-100 dark:hover:bg-violet-900/40 transition-colors"
                >
                  <Plug className="h-3 w-3 flex-shrink-0" />
                  {PROVIDER_LABELS[pid] ?? pid}
                </a>
              ))}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

// One summary card: bare-account banner, gated-Zoom note, and per-capability
// rows. Deep-links to Settings → Connectors (no connector cards on this page).
// Wrapped in CollapsibleSection so users can collapse it once reviewed.
function CallReadinessCard({ summary }: { summary: CapabilitiesSummary }) {
  return (
    <CollapsibleSection
      title="Agent readiness"
      icon={Zap}
      defaultOpen
      headerExtra={
        <a
          href="/settings?section=mcp_connections"
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-semibold text-violet-600 dark:text-violet-400 border border-violet-200 dark:border-violet-800/60 hover:bg-violet-50 dark:hover:bg-violet-950/20 transition-colors shrink-0"
        >
          <Plug className="h-3 w-3" /> Manage connectors
        </a>
      }
    >
      {summary.external_connected === false ? (
        <div className="flex flex-wrap items-center gap-3 rounded-xl border border-amber-200/70 bg-amber-50/60 px-4 py-3 dark:border-amber-800/40 dark:bg-amber-950/20">
          <AlertCircle className="h-4 w-4 text-amber-500 flex-shrink-0" />
          <div className="flex-1 min-w-0">
            <p className="text-xs font-semibold text-amber-700 dark:text-amber-400">No external integrations connected</p>
            <p className="text-[11px] text-amber-700/90 dark:text-amber-400/90 mt-0.5 leading-snug">
              Your call agent can only check the product catalog — it can't book meetings, pull recordings, look up
              prospects, or touch a CRM yet. Connect your sales stack before going live.
            </p>
          </div>
          <a
            href="/settings?section=mcp_connections"
            className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-[11px] font-bold bg-amber-500 text-white hover:bg-amber-600 transition-colors shadow-sm"
          >
            <Plug className="h-3 w-3" /> Connect integrations
          </a>
        </div>
      ) : (
        <>
          {summary.meeting_write_granted === false && (
            <div className="flex items-start gap-2 rounded-xl border border-amber-200/70 bg-amber-50/60 px-4 py-3 dark:border-amber-800/40 dark:bg-amber-950/20">
              <AlertCircle className="h-3.5 w-3.5 text-amber-500 flex-shrink-0 mt-0.5" />
              <p className="text-[11px] text-amber-700 dark:text-amber-400 leading-snug">
                Zoom meeting creation is hidden until the <code className="font-mono">meeting:write</code> scope is
                granted — reconnect Zoom in Settings to unlock it.
              </p>
            </div>
          )}
          <div className="space-y-2.5">
            {summary.capabilities.map((cap) => (
              <ReadinessRow key={cap.key} cap={cap} />
            ))}
          </div>
        </>
      )}
    </CollapsibleSection>
  );
}

// Collapsible section wrapper — same pattern as the leads detail page
function CollapsibleSection({
  title,
  icon: Icon,
  defaultOpen = false,
  children,
  headerExtra,
}: {
  title: string;
  icon?: ElementType;
  defaultOpen?: boolean;
  children: React.ReactNode;
  headerExtra?: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-2xl border border-slate-200/60 bg-white/60 shadow-sm backdrop-blur-sm dark:border-slate-800/40 dark:bg-slate-900/40 overflow-hidden transition-all duration-300 hover:shadow-md hover:border-violet-500/10">
      <div className="flex items-center justify-between px-6 py-4">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-2.5 text-left flex-1 min-w-0 cursor-pointer"
        >
          {Icon && <Icon className="h-4 w-4 text-violet-500 flex-shrink-0" />}
          <span className="text-sm font-bold bg-gradient-to-r from-slate-800 to-slate-600 dark:from-slate-200 dark:to-slate-400 bg-clip-text text-transparent">
            {title}
          </span>
        </button>
        <div className="flex items-center gap-2 flex-shrink-0">
          {headerExtra}
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 transition-colors cursor-pointer"
          >
            {open ? (
              <ChevronUp className="h-4 w-4" />
            ) : (
              <ChevronDown className="h-4 w-4" />
            )}
          </button>
        </div>
      </div>
      {open && <div className="px-6 pb-6 pt-0">{children}</div>}
    </div>
  );
}

export default function VoiceAgentsPage() {
  const { user, sessionTimeout } = useAuth();
  const [agents, setAgents] = useState<AgentPayload[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [tab, setTab] = useState<TabId>("overview");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [agentDraft, setAgentDraft] = useState({ name: "", description: "" });
  const [runtimeDraft, setRuntimeDraft] = useState<Runtime>({});
  const [promptDraft, setPromptDraft] = useState({ name: "Prompt", system_prompt: "", instructions: "" });
  const [events, setEvents] = useState<ExecutionEvent[]>([]);
  const [tools, setTools] = useState<ToolConfig[]>([]);
  const [templates, setTemplates] = useState<ExtractionTemplate[]>([]);
  const [toolDraft, setToolDraft] = useState({ name: "", description: "", http_method: "POST", url: "" });
  const [templateDraft, setTemplateDraft] = useState({ name: "", instructions: "", extraction_schema: '{\n  "field": "string"\n}' });
  const [graphJson, setGraphJson] = useState("{}");
  const [dirtyTabs, setDirtyTabs] = useState<Set<TabId>>(new Set());
  const [eventFilter, setEventFilter] = useState("");
  const [promptVersions, setPromptVersions] = useState<PromptVersion[]>([]);
  const [agentStats, setAgentStats] = useState<{ total_calls: number; last_call: string | null }>({ total_calls: 0, last_call: null });
  const [evalStats, setEvalStats] = useState<EvalStats | null>(null);
  const [extractionResults, setExtractionResults] = useState<ExtractionResult[]>([]);
  const [expandedResult, setExpandedResult] = useState<number | null>(null);
  const [capSummary, setCapSummary] = useState<CapabilitiesSummary | null>(null);

  // Dispositions tab
  type Disposition = { id: number; name: string; label: string; color?: string | null; description?: string | null; is_terminal: boolean };
  const [dispositions, setDispositions] = useState<Disposition[]>([]);
  const [dispModal, setDispModal] = useState<Disposition | null | "new">(null);
  const [dispForm, setDispForm] = useState({ name: "", label: "", color: "#6366f1", description: "", is_terminal: false });
  const [dispSaving, setDispSaving] = useState(false);
  const [dispError, setDispError] = useState<string | null>(null);
  const [testCallOpen, setTestCallOpen] = useState(false);
  const [testCallPhone, setTestCallPhone] = useState("");
  const [testCallLoading, setTestCallLoading] = useState(false);
  const [testCallResult, setTestCallResult] = useState<{ ok: boolean; msg: string } | null>(null);
  const [testCallInteractionId, setTestCallInteractionId] = useState<number | null>(null);
  const [testCallStatus, setTestCallStatus] = useState<string | null>(null);
  const [testCallLeads, setTestCallLeads] = useState<{ id: number; name: string; normalized_phone: string }[]>([]);
  const [testCallLeadId, setTestCallLeadId] = useState<number | null>(null);
  const [testCallPhoneMatch, setTestCallPhoneMatch] = useState<{ id: number; name: string; normalized_phone: string } | null>(null);
  const [testCallPhoneSearching, setTestCallPhoneSearching] = useState(false);

  type IVROption = { digit: string; label: string; action: "agent" | "transfer" | "hangup"; transfer_to?: string };
  type IVRMenu = { enabled: boolean; greeting: string; timeout_seconds: number; options: IVROption[] };
  const defaultIVR: IVRMenu = { enabled: false, greeting: "Press 1 for sales, press 2 for support, or stay on the line to speak with an AI agent.", timeout_seconds: 5, options: [] };
  const [ivrMenu, setIVRMenu] = useState<IVRMenu>(defaultIVR);
  const [callFeatures, setCallFeatures] = useState<CallFeaturesConfig>({
    voicemail: { enabled: false, detection_duration: 30, check_interval: 7, min_transcript_length: 7 },
    dtmf: { enabled: false, menu: {} },
    language_detection: { enabled: false, provider: "llm", detection_turns: 3 },
    ambient_noise: { enabled: false, preset: "call-center", volume: 0.15 },
    filler: { use_fillers: false, backchanneling: false, backchanneling_message_gap: 5.0 },
    calling_guardrails: { enabled: false, start_hour: 9, end_hour: 22, sunday_blocked: true, bypass_urgent: false },
    retry: { max_retries: 3, retry_delay_minutes: 60, retry_backoff_multiplier: 1.0 },
    final_call_message: {},
  });

  const selected = useMemo(
    () => agents.find((item) => item.agent.id === selectedId) ?? agents[0] ?? null,
    [agents, selectedId],
  );

  async function request(url: string, init?: RequestInit) {
    const res = await apiFetch(url, init);
    if (res.status === 401) {
      sessionTimeout();
      throw new Error("unauthorized");
    }
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `Server returned ${res.status}`);
    }
    return res;
  }

  async function loadAgents(nextSelectedId?: number) {
    setLoading(true);
    setError(null);
    try {
      const res = await request(`${API_BASE}/crm/voice-agents`);
      const data: AgentPayload[] = await res.json();
      setAgents(data);
      setSelectedId(nextSelectedId ?? selectedId ?? data[0]?.agent.id ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load voice agents");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (user) void loadAgents();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  // Agent readiness — same capabilities payload as the Settings card.
  const fetchCapabilities = useCallback(async () => {
    try {
      const res = await apiFetch(`${API_BASE}/mcp-connections/capabilities/summary`);
      if (res.status === 401) { sessionTimeout(); return; }
      if (!res.ok) return;
      setCapSummary(await res.json());
    } catch { /* non-fatal — the readiness card stays hidden */ }
  }, [sessionTimeout]);

  useEffect(() => {
    if (user) void fetchCapabilities();
  }, [user, fetchCapabilities]);

  // Keep the card in sync with connections made elsewhere (e.g. Settings).
  useEffect(() => {
    const t = setInterval(fetchCapabilities, 30000);
    return () => clearInterval(t);
  }, [fetchCapabilities]);

  useEffect(() => {
    if (!selected) return;
    setAgentDraft({
      name: selected.agent.name,
      description: selected.agent.description || "",
    });
    const rt = selected.runtime || {};
    setRuntimeDraft(rt);
    const ivr = (rt.runtime_json as Record<string, unknown> | undefined)?.ivr_menu as IVRMenu | undefined;
    setIVRMenu(ivr ? { ...defaultIVR, ...ivr } : defaultIVR);
    const cf = (rt.runtime_json as Record<string, unknown> | undefined)?.call_features as CallFeaturesConfig | undefined;
    if (cf) {
      setCallFeatures((prev) => ({
        ...prev,
        ...cf,
        voicemail: { ...prev.voicemail, ...(cf.voicemail || {}) },
        dtmf: { ...prev.dtmf, ...(cf.dtmf || {}) },
      }));
    }
    setPromptDraft({
      name: selected.active_prompt?.name || "Prompt",
      system_prompt: selected.active_prompt?.system_prompt || "",
      instructions: selected.active_prompt?.instructions || "",
    });
    void loadTabData(selected.agent.id, tab);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, tab, selected?.agent.id]);

  async function loadTabData(agentId: number, activeTab: TabId) {
    try {
      if (activeTab === "executions") {
        const res = await request(`${API_BASE}/crm/voice-agents/${agentId}/executions?limit=100`);
        setEvents(await res.json());
      }
      if (activeTab === "overview") {
        try {
          const statsRes = await request(`${API_BASE}/crm/voice-agents/${agentId}/stats`);
          setAgentStats(await statsRes.json());
        } catch { /* non-blocking */ }
        try {
          const evalRes = await request(`${API_BASE}/crm/voice-agents/${agentId}/eval-stats`);
          setEvalStats(await evalRes.json());
        } catch { /* non-blocking */ }
      }
      if (activeTab === "prompts") {
        const res = await request(`${API_BASE}/crm/voice-agents/${agentId}/prompts`);
        setPromptVersions(await res.json());
      }
      if (activeTab === "tools") {
        const res = await request(`${API_BASE}/crm/voice-agents/${agentId}/tools`);
        setTools(await res.json());
      }
      if (activeTab === "extractions") {
        const res = await request(`${API_BASE}/crm/voice-agents/${agentId}/extraction-templates`);
        setTemplates(await res.json());
        try {
          const rRes = await request(`${API_BASE}/crm/voice-agents/${agentId}/extraction-results`);
          setExtractionResults(await rRes.json());
        } catch { /* non-blocking */ }
      }
      if (activeTab === "dispositions") {
        const res = await apiFetch(`${API_BASE}/crm/dispositions?agent_id=${agentId}`);
        if (res.ok) setDispositions(await res.json());
      }
      if (activeTab === "graph") {
        const res = await request(`${API_BASE}/crm/voice-agents/${agentId}/graph`);
        const data = await res.json();
        setGraphJson(JSON.stringify(data.graph_json || {}, null, 2));
      }
      if (activeTab === "call" && selected?.runtime?.runtime_json) {
        const rj = selected.runtime.runtime_json as Record<string, unknown>;
        const cf = (rj.call_features || rj.voicemail) as Partial<CallFeaturesConfig> | undefined;
        if (cf) {
          setCallFeatures((prev) => ({
            ...prev,
            ...cf,
            voicemail: { ...prev.voicemail, ...(cf.voicemail || (rj.voicemail as object) || {}) },
            dtmf: { ...prev.dtmf, ...(cf.dtmf || {}) },
          }));
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load tab data");
    }
  }

  async function activatePromptVersion(versionId: number) {
    if (!selected) return;
    try {
      await request(`${API_BASE}/crm/voice-agents/${selected.agent.id}/prompts/${versionId}/activate`, { method: "POST" });
      setMessage("Prompt version activated");
      await loadAgents(selected.agent.id);
      await loadTabData(selected.agent.id, "prompts");
    } catch {
      setError("Failed to activate prompt version");
    }
  }

  const TEST_CALL_STATUS_LABELS: Record<string, string> = {
    initiated: "Calling...", ringing: "Ringing...", "in-progress": "In conversation",
    in_progress: "In conversation", connected: "In conversation",
    completed: "Call ended", "no-answer": "No answer", no_answer: "No answer",
    busy: "Line busy", failed: "Call failed", cancelled: "Cancelled", canceled: "Cancelled",
  };
  const TEST_CALL_TERMINAL = new Set(["completed","no-answer","no_answer","busy","failed","canceled","cancelled","error","low_balance","stopped"]);

  useEffect(() => {
    if (!testCallInteractionId) return;
    const iv = setInterval(async () => {
      try {
        const res = await apiFetch(`${API_BASE}/call-status?interaction_id=${testCallInteractionId}`);
        if (!res.ok) return;
        const data = await res.json();
        setTestCallStatus(data.call_status);
        if (data.is_terminal) {
          clearInterval(iv);
          setTimeout(() => { setTestCallInteractionId(null); setTestCallStatus(null); }, 5000);
        }
      } catch { /* ignore */ }
    }, 2000);
    return () => clearInterval(iv);
  }, [testCallInteractionId]);

  useEffect(() => {
    if (!testCallOpen) return;
    apiFetch(`${API_BASE}/crm/leads?page=1&limit=100`).then(r => r.json()).then(d => {
      const items = d.items ?? d.leads ?? d ?? [];
      setTestCallLeads(Array.isArray(items) ? items.filter((l: { normalized_phone?: string }) => l.normalized_phone) : []);
    }).catch(() => {});
  }, [testCallOpen]);

  // When phone typed manually (no lead selected), search for matching lead
  useEffect(() => {
    if (testCallLeadId || !testCallPhone.trim()) {
      setTestCallPhoneMatch(null);
      return;
    }
    const phone = testCallPhone.trim();
    const timer = setTimeout(async () => {
      setTestCallPhoneSearching(true);
      try {
        const res = await apiFetch(`${API_BASE}/crm/leads?search=${encodeURIComponent(phone)}&limit=5`);
        if (res.ok) {
          const data = await res.json();
          const match = (data.items ?? []).find((l: { normalized_phone: string }) =>
            l.normalized_phone.replace(/\D/g, "").endsWith(phone.replace(/\D/g, "").slice(-10))
          );
          setTestCallPhoneMatch(match ?? null);
        }
      } catch { /* non-fatal */ } finally {
        setTestCallPhoneSearching(false);
      }
    }, 500);
    return () => clearTimeout(timer);
  }, [testCallPhone, testCallLeadId, API_BASE]);

  async function triggerTestCall() {
    if (!selected || !testCallPhone.trim()) return;
    setTestCallLoading(true);
    setTestCallResult(null);
    setTestCallInteractionId(null);
    setTestCallStatus(null);
    try {
      // Use matched lead_id if user hasn't explicitly selected one
      const effectiveLeadId = testCallLeadId ?? testCallPhoneMatch?.id ?? null;
      let url = `${API_BASE}/make-call?to=${encodeURIComponent(testCallPhone.trim())}&agent_id=${selected.agent.id}`;
      if (effectiveLeadId) url += `&lead_id=${effectiveLeadId}`;
      const res = await apiFetch(url, { method: "POST" });
      const body = await res.json().catch(() => ({}));
      if (res.ok) {
        setTestCallResult({ ok: true, msg: "Call initiated!" });
        if (body.interaction_id) setTestCallInteractionId(body.interaction_id);
      } else {
        setTestCallResult({ ok: false, msg: body.detail || `Error ${res.status}` });
      }
    } catch (err) {
      setTestCallResult({ ok: false, msg: err instanceof Error ? err.message : "Failed" });
    } finally {
      setTestCallLoading(false);
    }
  }

  function markDirty() {
    setDirtyTabs(prev => new Set(prev).add(tab));
  }

  function clearDirty() {
    setDirtyTabs(prev => { const n = new Set(prev); n.delete(tab); return n; });
  }

  async function createAgent() {
    setSaving(true);
    setMessage(null);
    setError(null);
    try {
      const res = await request(`${API_BASE}/crm/voice-agents`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: `Voice Agent ${agents.length + 1}`,
          system_prompt: "You are Rio, a concise inside-sales voice assistant.",
        }),
      });
      const data: AgentPayload = await res.json();
      setMessage("Agent created");
      await loadAgents(data.agent.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create agent");
    } finally {
      setSaving(false);
    }
  }

  async function saveOverview() {
    if (!selected) return;
    setSaving(true);
    setMessage(null);
    setError(null);
    try {
      await request(`${API_BASE}/crm/voice-agents/${selected.agent.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(agentDraft),
      });
      setMessage("Agent saved");
      clearDirty();
      await loadAgents(selected.agent.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save agent");
    } finally {
      setSaving(false);
    }
  }

  async function saveRuntime() {
    if (!selected) return;
    setSaving(true);
    setMessage(null);
    setError(null);
    try {
      await request(`${API_BASE}/crm/voice-agents/${selected.agent.id}/runtime`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(runtimeDraft),
      });
      setMessage("Runtime saved");
      clearDirty();
      await loadAgents(selected.agent.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save runtime");
    } finally {
      setSaving(false);
    }
  }

  async function saveIVR() {
    if (!selected) return;
    setSaving(true);
    setMessage(null);
    setError(null);
    try {
      await request(`${API_BASE}/crm/voice-agents/${selected.agent.id}/runtime`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          runtime_json: { ...(runtimeDraft.runtime_json || {}), ivr_menu: ivrMenu },
        }),
      });
      setMessage("IVR saved");
      await loadAgents(selected.agent.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save IVR");
    } finally {
      setSaving(false);
    }
  }

  async function publishPrompt() {
    if (!selected) return;
    setSaving(true);
    setMessage(null);
    setError(null);
    try {
      await request(`${API_BASE}/crm/voice-agents/${selected.agent.id}/prompts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...promptDraft, publish: true }),
      });
      setMessage("Prompt published");
      clearDirty();
      await loadAgents(selected.agent.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to publish prompt");
    } finally {
      setSaving(false);
    }
  }

  async function setDefault() {
    if (!selected) return;
    await request(`${API_BASE}/crm/voice-agents/${selected.agent.id}/set-default`, { method: "POST" });
    await loadAgents(selected.agent.id);
    setMessage("Default agent updated");
  }

  async function archiveAgent() {
    if (!selected || selected.agent.is_default) return;
    await request(`${API_BASE}/crm/voice-agents/${selected.agent.id}`, { method: "DELETE" });
    setSelectedId(null);
    await loadAgents();
  }

  async function createTool() {
    if (!selected) return;
    await request(`${API_BASE}/crm/voice-agents/${selected.agent.id}/tools`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...toolDraft,
        input_extraction_schema: {},
        tool_type: "custom_http",
        is_active: true,
      }),
    });
    setToolDraft({ name: "", description: "", http_method: "POST", url: "" });
    await loadTabData(selected.agent.id, "tools");
  }

  async function createTemplate() {
    if (!selected) return;
    let parsed: Record<string, unknown> = {};
    try {
      parsed = JSON.parse(templateDraft.extraction_schema || "{}");
    } catch {
      setError("Extraction schema must be valid JSON");
      return;
    }
    await request(`${API_BASE}/crm/voice-agents/${selected.agent.id}/extraction-templates`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: templateDraft.name,
        instructions: templateDraft.instructions,
        extraction_schema: parsed,
        is_active: true,
      }),
    });
    setTemplateDraft({ name: "", instructions: "", extraction_schema: '{\n  "field": "string"\n}' });
    await loadTabData(selected.agent.id, "extractions");
  }

  async function saveGraph() {
    if (!selected) return;
    let parsed: Record<string, unknown> = {};
    try {
      parsed = JSON.parse(graphJson || "{}");
    } catch {
      setError("Graph JSON is invalid");
      return;
    }
    await request(`${API_BASE}/crm/voice-agents/${selected.agent.id}/graph`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ graph_json: parsed, is_enabled: Object.keys(parsed).length > 0 }),
    });
    setMessage("Graph saved");
  }

  async function applyTrafficSplit(promptId: number, split: number) {
    if (!selected) return;
    try {
      await request(
        `${API_BASE}/crm/voice-agents/${selected.agent.id}/prompts/${promptId}/traffic-split?traffic_split=${split}`,
        { method: "PATCH" }
      );
      await loadTabData(selected.agent.id, "prompts");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update traffic split");
    }
  }

  // Helper: read/write nested runtime_json fields
  function rjGet(path: string[]): string {
    let obj: Record<string, unknown> = (runtimeDraft.runtime_json || {}) as Record<string, unknown>;
    for (const key of path.slice(0, -1)) {
      obj = (obj[key] as Record<string, unknown>) || {};
    }
    const val = obj[path[path.length - 1]];
    return val !== undefined && val !== null ? String(val) : "";
  }

  function rjSet(path: string[], value: unknown) {
    const rj = { ...(runtimeDraft.runtime_json || {}) } as Record<string, unknown>;
    let obj = rj;
    for (const key of path.slice(0, -1)) {
      obj[key] = { ...(obj[key] as Record<string, unknown> || {}) };
      obj = obj[key] as Record<string, unknown>;
    }
    const last = path[path.length - 1];
    if (value === "" || value === null) delete obj[last]; else obj[last] = value;
    setRuntimeDraft({ ...runtimeDraft, runtime_json: rj });
    markDirty();
  }

  async function saveCallFeatures() {
    if (!selected) return;
    setSaving(true);
    setMessage(null);
    setError(null);
    try {
      await request(`${API_BASE}/crm/voice-agents/${selected.agent.id}/runtime`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          runtime_json: {
            ...(runtimeDraft.runtime_json || {}),
            call_features: callFeatures,
            ambient_noise: callFeatures.ambient_noise,
          },
        }),
      });
      setMessage("Call features saved");
      await loadAgents(selected.agent.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save call features");
    } finally {
      setSaving(false);
    }
  }

  if (!user) return null;

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-indigo-50/10 to-slate-100 text-slate-950 dark:from-slate-950 dark:via-slate-900/60 dark:to-slate-950 dark:text-slate-100 transition-all duration-500">
      <div className="flex min-h-screen">
        <aside className="w-80 shrink-0 border-r border-slate-200/50 bg-white/70 backdrop-blur-xl dark:border-slate-800/40 dark:bg-slate-900/60 transition-all duration-300">
          <div className="flex items-center justify-between border-b border-slate-200/50 px-6 py-5 dark:border-slate-800/40">
            <div>
              <h1 className="text-xl font-bold bg-gradient-to-r from-violet-600 to-indigo-600 bg-clip-text text-transparent dark:from-violet-400 dark:to-indigo-400">Voice Agent</h1>
              <p className="text-xs text-slate-500 mt-0.5 font-medium">{agents.length} configured</p>
            </div>
            <button
              onClick={createAgent}
              disabled={saving}
              className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-r from-violet-600 to-indigo-600 text-white shadow-md shadow-violet-500/10 hover:from-violet-500 hover:to-indigo-500 hover:shadow-violet-500/25 active:scale-95 transition-all disabled:opacity-60 cursor-pointer"
              title="Create agent"
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            </button>
          </div>
          <div className="space-y-3 p-4">
            {loading ? (
              <div className="flex items-center gap-2 px-3 py-6 text-sm text-slate-400 font-medium justify-center">
                <Loader2 className="h-4 w-4 animate-spin text-violet-500" /> Loading Agents...
              </div>
            ) : (
              agents.map((item) => (
                <button
                  key={item.agent.id}
                  onClick={() => setSelectedId(item.agent.id)}
                  className={clsx(
                    "w-full rounded-xl border p-4 text-left transition-all duration-300 shadow-sm cursor-pointer",
                    selected?.agent.id === item.agent.id
                      ? "border-violet-500/30 bg-gradient-to-br from-violet-500/10 via-indigo-500/5 to-transparent dark:from-violet-500/20 dark:via-indigo-500/10 dark:to-transparent ring-2 ring-violet-500/10 shadow-sm"
                      : "border-slate-100/50 bg-white/40 hover:border-violet-200/50 hover:bg-violet-50/20 dark:border-slate-800/30 dark:bg-slate-900/30 dark:hover:border-violet-900/20 dark:hover:bg-violet-950/5",
                  )}
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-semibold text-sm text-slate-800 dark:text-slate-200">{item.agent.name}</span>
                    {item.agent.is_default && (
                      <span className="rounded-lg bg-amber-100 px-2 py-0.5 text-[10px] font-bold text-amber-700 dark:bg-amber-500/15 dark:text-amber-300">
                        Default
                      </span>
                    )}
                  </div>
                  <div className="mt-1.5 text-[11px] text-slate-400 font-medium">
                    {item.runtime.llm_provider || "llm"} / {item.runtime.tts_provider || "tts"}
                  </div>
                </button>
              ))
            )}
          </div>
        </aside>

        <main className="flex-1 overflow-x-hidden">
          <div className="border-b border-slate-200/50 bg-white/50 backdrop-blur-md px-8 py-5 dark:border-slate-800/40 dark:bg-slate-900/50">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="flex items-center gap-3">
                  <h2 className="text-2xl font-bold bg-gradient-to-r from-slate-900 to-slate-700 dark:from-slate-100 dark:to-slate-300 bg-clip-text text-transparent">{selected?.agent.name || "Voice Agents"}</h2>
                  {selected?.agent.status && (
                    <span className="rounded-lg bg-slate-100/80 px-2.5 py-1 text-xs font-semibold text-slate-600 dark:bg-slate-800/80 dark:text-slate-300 border border-slate-200/30 dark:border-slate-700/20">
                      {selected.agent.status}
                    </span>
                  )}
                </div>
                <p className="text-xs text-slate-400 mt-1 font-medium">{selected?.agent.description || "Agent behavior, runtime, and execution history"}</p>
              </div>
              <div className="flex items-center gap-3">
                {selected && (
                <div className="flex gap-2">
                  <button
                    onClick={() => { setTestCallOpen(true); setTestCallResult(null); setTestCallPhone(""); }}
                    className="inline-flex items-center gap-2 rounded-xl border border-emerald-200/60 bg-emerald-50/30 px-4 py-2.5 text-xs font-medium text-emerald-700 hover:bg-emerald-50 hover:border-emerald-300 transition-all dark:border-emerald-900/40 dark:bg-emerald-950/10 dark:hover:bg-emerald-950/30 dark:text-emerald-400 cursor-pointer"
                  >
                    <PhoneForwarded className="h-3.5 w-3.5" /> Test Call
                  </button>
                  <button
                    onClick={setDefault}
                    disabled={selected.agent.is_default}
                    className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white/80 px-4 py-2.5 text-xs font-medium hover:bg-slate-50 hover:border-slate-300 transition-all disabled:opacity-50 dark:border-slate-800 dark:bg-slate-900/80 dark:hover:bg-slate-800 dark:hover:border-slate-700 cursor-pointer"
                  >
                    <Check className="h-3.5 w-3.5" /> Default
                  </button>
                  <button
                    onClick={archiveAgent}
                    disabled={selected.agent.is_default}
                    className="inline-flex items-center gap-2 rounded-xl border border-red-200/60 bg-red-50/30 px-4 py-2.5 text-xs font-medium text-red-600 hover:bg-red-50 hover:border-red-300 transition-all disabled:opacity-50 dark:border-red-900/40 dark:bg-red-950/10 dark:hover:bg-red-950/30 cursor-pointer"
                  >
                    <Trash2 className="h-3.5 w-3.5" /> Archive
                  </button>
                </div>
              )}
                <UserChip />
              </div>
            </div>
            <div className="mt-5 flex gap-2 overflow-x-auto py-1 scrollbar-none">
              {tabs.map(({ id, label, Icon }) => (
                <button
                  key={id}
                  onClick={() => setTab(id)}
                  className={clsx(
                    "relative inline-flex items-center gap-2 rounded-xl px-4 py-2.5 text-xs font-semibold whitespace-nowrap transition-all duration-300 active:scale-95 cursor-pointer",
                    tab === id
                      ? "bg-gradient-to-r from-violet-600 to-indigo-600 text-white shadow-lg shadow-violet-500/20"
                      : "bg-slate-50 text-slate-500 hover:bg-slate-100 hover:text-slate-800 border border-slate-200/40 dark:bg-slate-850/40 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200 dark:border-slate-800/30",
                  )}
                >
                  <Icon className="h-3.5 w-3.5" /> {label}
                  {dirtyTabs.has(id) && (
                    <span className="absolute -top-1 -right-1 h-2 w-2 rounded-full bg-amber-400 border border-white dark:border-slate-900" />
                  )}
                </button>
              ))}
            </div>
          </div>

          {/* Test Call Modal */}
          {testCallOpen && selected && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
              <div className="w-full max-w-sm rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl dark:border-slate-800 dark:bg-slate-900">
                <div className="mb-4 flex items-center justify-between">
                  <h3 className="font-bold text-slate-900 dark:text-slate-100">Test Call — {selected.agent.name}</h3>
                  <button onClick={() => { setTestCallOpen(false); setTestCallInteractionId(null); setTestCallStatus(null); setTestCallResult(null); setTestCallLeadId(null); setTestCallPhone(""); setTestCallPhoneMatch(null); }} className="text-slate-400 hover:text-slate-600 cursor-pointer"><X className="h-4 w-4" /></button>
                </div>

                {testCallLeads.length > 0 && (
                  <label className="block mb-3">
                    <span className="text-xs font-bold uppercase text-slate-400 block mb-1.5">Lead (optional)</span>
                    <select
                      className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-sm outline-none focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100"
                      value={testCallLeadId ?? ""}
                      onChange={(e) => {
                        const id = e.target.value ? Number(e.target.value) : null;
                        setTestCallLeadId(id);
                        if (id) {
                          const lead = testCallLeads.find(l => l.id === id);
                          if (lead) setTestCallPhone(lead.normalized_phone);
                        }
                      }}
                    >
                      <option value="">— no lead —</option>
                      {testCallLeads.map(l => (
                        <option key={l.id} value={l.id}>{l.name} · {l.normalized_phone}</option>
                      ))}
                    </select>
                  </label>
                )}

                <label className="block mb-3">
                  <span className="text-xs font-bold uppercase text-slate-400 block mb-1.5">Phone Number</span>
                  <input
                    className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-sm outline-none focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100"
                    placeholder="+919876543210"
                    value={testCallPhone}
                    onChange={(e) => { setTestCallPhone(e.target.value); setTestCallLeadId(null); setTestCallPhoneMatch(null); }}
                  />
                </label>

                {/* Phone-to-lead match hint */}
                {!testCallLeadId && testCallPhone.trim() && (
                  testCallPhoneSearching ? (
                    <div className="mb-3 flex items-center gap-2 rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-400 dark:bg-slate-800/60">
                      <Loader2 className="h-3 w-3 animate-spin flex-shrink-0" />
                      Looking up lead…
                    </div>
                  ) : testCallPhoneMatch ? (
                    <div className="mb-3 flex items-center justify-between gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs dark:border-emerald-800/40 dark:bg-emerald-950/20">
                      <span className="text-emerald-700 dark:text-emerald-300">
                        Matches lead: <span className="font-semibold">{testCallPhoneMatch.name}</span>
                        <span className="ml-1 opacity-60">({testCallPhoneMatch.normalized_phone})</span>
                      </span>
                      <button
                        type="button"
                        onClick={() => { setTestCallLeadId(testCallPhoneMatch.id); setTestCallPhone(testCallPhoneMatch.normalized_phone); setTestCallPhoneMatch(null); }}
                        className="rounded-lg bg-emerald-600 px-2 py-0.5 text-[10px] font-bold text-white hover:bg-emerald-700 cursor-pointer"
                      >
                        Use
                      </button>
                    </div>
                  ) : testCallPhone.trim().length >= 5 && !testCallPhoneSearching ? (
                    <div className="mb-3 rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:bg-amber-950/20 dark:text-amber-300">
                      No matching lead found — call will log as unknown lead.
                    </div>
                  ) : null
                )}

                {testCallStatus && (
                  <div className={clsx("mb-3 rounded-xl px-4 py-3 text-xs font-medium flex items-center gap-2",
                    TEST_CALL_TERMINAL.has(testCallStatus)
                      ? "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300"
                      : "bg-violet-50 text-violet-700 dark:bg-violet-950/20 dark:text-violet-300"
                  )}>
                    {!TEST_CALL_TERMINAL.has(testCallStatus) && <Loader2 className="h-3 w-3 animate-spin flex-shrink-0" />}
                    {TEST_CALL_STATUS_LABELS[testCallStatus] ?? testCallStatus}
                  </div>
                )}

                {testCallResult && !testCallStatus && (
                  <div className={clsx("mb-3 rounded-xl px-4 py-3 text-xs font-medium", testCallResult.ok ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/20 dark:text-emerald-300" : "bg-red-50 text-red-700 dark:bg-red-950/20 dark:text-red-300")}>
                    {testCallResult.msg}
                  </div>
                )}

                <button
                  onClick={triggerTestCall}
                  disabled={testCallLoading || !testCallPhone.trim() || (!!testCallStatus && !TEST_CALL_TERMINAL.has(testCallStatus))}
                  className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-500 px-4 py-2.5 text-xs font-bold text-white shadow-md hover:from-emerald-400 hover:to-teal-400 active:scale-95 transition-all disabled:opacity-60 cursor-pointer"
                >
                  {testCallLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <PhoneForwarded className="h-4 w-4" />}
                  {testCallLoading ? "Calling..." : "Call Now"}
                </button>
              </div>
            </div>
          )}

          <div className="p-8">
            {capSummary && capSummary.capabilities.length > 0 && (
              <div className="mb-6">
                <CallReadinessCard summary={capSummary} />
              </div>
            )}

            {(message || error) && (
              <div
                className={clsx(
                  "mb-6 rounded-2xl border px-5 py-4 text-xs font-medium shadow-sm backdrop-blur-sm",
                  error
                    ? "border-red-200 bg-red-50/60 text-red-700 dark:border-red-900/40 dark:bg-red-950/20 dark:text-red-300"
                    : "border-emerald-200 bg-emerald-50/60 text-emerald-700 dark:border-emerald-900/40 dark:bg-emerald-950/20 dark:text-emerald-300",
                )}
              >
                {error || message}
              </div>
            )}

            {!selected ? (
              <div className="rounded-2xl border border-dashed border-slate-200 bg-white/40 p-12 text-center text-sm font-medium text-slate-400 dark:border-slate-800/40 dark:bg-slate-900/20">
                No agent selected.
              </div>
            ) : tab === "overview" ? (
              <section className="max-w-2xl space-y-5">
                <div className="flex gap-4">
                  <div className="flex-1 rounded-2xl border border-slate-200/60 bg-white/60 p-4 shadow-sm backdrop-blur-sm dark:border-slate-800/40 dark:bg-slate-900/40 flex items-center gap-3">
                    <BarChart2 className="h-5 w-5 text-violet-500 shrink-0" />
                    <div>
                      <p className="text-2xl font-bold text-slate-900 dark:text-slate-100">{agentStats.total_calls}</p>
                      <p className="text-xs text-slate-400 font-medium">Total Calls</p>
                    </div>
                  </div>
                  <div className="flex-1 rounded-2xl border border-slate-200/60 bg-white/60 p-4 shadow-sm backdrop-blur-sm dark:border-slate-800/40 dark:bg-slate-900/40 flex items-center gap-3">
                    <Clock className="h-5 w-5 text-indigo-500 shrink-0" />
                    <div>
                      <p className="text-sm font-bold text-slate-900 dark:text-slate-100 truncate">{agentStats.last_call ? new Date(agentStats.last_call).toLocaleDateString() : "—"}</p>
                      <p className="text-xs text-slate-400 font-medium">Last Call</p>
                    </div>
                  </div>
                  <div className="flex-1 rounded-2xl border border-slate-200/60 bg-white/60 p-4 shadow-sm backdrop-blur-sm dark:border-slate-800/40 dark:bg-slate-900/40 flex items-center gap-3">
                    {evalStats?.avg_overall != null && evalStats.avg_overall >= 3.5
                      ? <CheckCircle2 className="h-5 w-5 text-emerald-500 shrink-0" />
                      : <XCircle className="h-5 w-5 text-red-400 shrink-0" />}
                    <div>
                      <p className="text-2xl font-bold text-slate-900 dark:text-slate-100">
                        {evalStats?.avg_overall != null ? `${Math.round(evalStats.avg_overall / 5 * 100)}%` : "—"}
                      </p>
                      <p className="text-xs text-slate-400 font-medium">AI Quality</p>
                      {evalStats?.pass_rate != null && (
                        <p className="text-[10px] text-slate-500">{Math.round(evalStats.pass_rate * 100)}% pass · {evalStats.evaluated} eval'd</p>
                      )}
                    </div>
                  </div>
                </div>
                {evalStats && evalStats.evaluated > 0 && (
                  <CollapsibleSection title="Quality by Axis" icon={BarChart2} defaultOpen>
                    <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
                      {Object.entries(evalStats.axis_averages).map(([ax, score]) => {
                        const pct = score != null ? (score / 5) * 100 : 0;
                        const color = score != null && score >= 4 ? "bg-emerald-500" : score != null && score >= 3 ? "bg-amber-500" : "bg-red-500";
                        const textColor = score != null && score >= 4 ? "text-emerald-500" : score != null && score >= 3 ? "text-amber-500" : "text-red-400";
                        return (
                          <div key={ax}>
                            <div className="flex items-center justify-between mb-1">
                              <span className="text-[10px] text-slate-500 capitalize">{ax.replace(/_/g, " ")}</span>
                              <span className={`text-[10px] font-bold ${textColor}`}>{score != null ? `${score}/5` : "—"}</span>
                            </div>
                            <div className="h-1.5 rounded-full bg-slate-200 dark:bg-slate-700 overflow-hidden">
                              <div className={`h-full rounded-full ${color} transition-all`} style={{ width: `${pct}%` }} />
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </CollapsibleSection>
                )}
                <CollapsibleSection title="Agent Details" icon={Bot} defaultOpen>
                  <div className="space-y-5">
                    <Field label="Name">
                      <input
                        className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500"
                        value={agentDraft.name}
                        onChange={(e) => { setAgentDraft({ ...agentDraft, name: e.target.value }); markDirty(); }}
                      />
                    </Field>
                    <Field label="Description">
                      <textarea
                        className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500 min-h-28"
                        value={agentDraft.description}
                        onChange={(e) => { setAgentDraft({ ...agentDraft, description: e.target.value }); markDirty(); }}
                      />
                    </Field>
                    <ActionButton onClick={saveOverview} saving={saving} label="Save Agent" />
                  </div>
                </CollapsibleSection>
              </section>
            ) : tab === "prompts" ? (
              <section className="max-w-4xl space-y-5">
                <div className="rounded-2xl border border-slate-200/60 bg-white/60 p-6 shadow-sm backdrop-blur-sm dark:border-slate-800/40 dark:bg-slate-900/40 space-y-5">
                  <Field label="Version Name">
                    <input
                      className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500"
                      value={promptDraft.name}
                      onChange={(e) => { setPromptDraft({ ...promptDraft, name: e.target.value }); markDirty(); }}
                    />
                  </Field>
                  <Field label="System Prompt">
                    <textarea
                      className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500 min-h-72 font-mono"
                      value={promptDraft.system_prompt}
                      onChange={(e) => { setPromptDraft({ ...promptDraft, system_prompt: e.target.value }); markDirty(); }}
                    />
                  </Field>
                  <Field label="Instructions">
                    <textarea
                      className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500 min-h-32"
                      value={promptDraft.instructions}
                      onChange={(e) => { setPromptDraft({ ...promptDraft, instructions: e.target.value }); markDirty(); }}
                    />
                  </Field>
                  <ActionButton onClick={publishPrompt} saving={saving} label="Publish Prompt" />
                </div>
                {evalStats && evalStats.evaluated > 0 && (
                  <div className="rounded-2xl border border-violet-500/20 bg-violet-500/5 p-5">
                    <div className="flex items-center gap-2 mb-3">
                      <Layers className="h-4 w-4 text-violet-400" />
                      <p className="text-xs font-bold text-violet-400 uppercase tracking-widest">Quality Signal — last {evalStats.evaluated} evaluated calls</p>
                    </div>
                    <div className="grid grid-cols-3 gap-3 md:grid-cols-6">
                      {Object.entries(evalStats.axis_averages).map(([ax, score]) => {
                        const pct = score != null ? (score / 5) * 100 : 0;
                        const color = score != null && score >= 4 ? "bg-emerald-500" : score != null && score >= 3 ? "bg-amber-500" : "bg-red-500";
                        const textColor = score != null && score >= 4 ? "text-emerald-400" : score != null && score >= 3 ? "text-amber-400" : "text-red-400";
                        return (
                          <div key={ax} className="rounded-lg border border-white/10 bg-white/5 p-2">
                            <p className="text-[9px] uppercase tracking-wider text-slate-500 mb-1">{ax.replace(/_/g, " ")}</p>
                            <p className={`text-sm font-bold ${textColor}`}>{score != null ? `${score}/5` : "—"}</p>
                            <div className="mt-1 h-1 rounded-full bg-white/10 overflow-hidden">
                              <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
                            </div>
                          </div>
                        );
                      })}
                    </div>
                    {evalStats.avg_overall != null && (
                      <p className="mt-3 text-xs text-slate-500">
                        Overall: <span className={`font-bold ${evalStats.avg_overall >= 3.5 ? "text-emerald-400" : "text-red-400"}`}>{evalStats.avg_overall}/5</span>
                        &nbsp;·&nbsp; Pass rate: <span className="font-bold">{Math.round((evalStats.pass_rate ?? 0) * 100)}%</span>
                        &nbsp;·&nbsp; If scores are low, update the active prompt above.
                      </p>
                    )}
                  </div>
                )}

                {promptVersions.length > 0 && (
                  <div className="rounded-2xl border border-slate-200/60 bg-white/60 p-6 shadow-sm backdrop-blur-sm dark:border-slate-800/40 dark:bg-slate-900/40">
                    <p className="text-sm font-bold bg-gradient-to-r from-slate-800 to-slate-600 dark:from-slate-200 dark:to-slate-400 bg-clip-text text-transparent mb-4">Version History & A/B Traffic</p>
                    <div className="space-y-3">
                      {promptVersions.map((v) => (
                        <div key={v.id} className={clsx("rounded-xl border px-4 py-3", v.is_active ? "border-violet-300 bg-violet-50/50 dark:border-violet-800/50 dark:bg-violet-950/20" : "border-slate-100 bg-white/40 dark:border-slate-800/30 dark:bg-slate-900/20")}>
                          <div className="flex items-center justify-between">
                            <div>
                              <span className="text-xs font-bold text-slate-700 dark:text-slate-300">v{v.version} — {v.name}</span>
                              {v.created_at && <span className="ml-2 text-[10px] text-slate-400">{new Date(v.created_at).toLocaleDateString()}</span>}
                              {v.is_active && <span className="ml-2 rounded-md bg-violet-100 px-1.5 py-0.5 text-[10px] font-bold text-violet-700 dark:bg-violet-900/40 dark:text-violet-300">Active</span>}
                              {v.traffic_split != null && v.traffic_split! > 0 && !v.is_active && (
                                <span className="ml-2 rounded-md bg-amber-100 px-1.5 py-0.5 text-[10px] font-bold text-amber-700 dark:bg-amber-900/40 dark:text-amber-300">
                                  {v.traffic_split}% traffic
                                </span>
                              )}
                            </div>
                            {!v.is_active && (
                              <button
                                onClick={() => activatePromptVersion(v.id)}
                                className="rounded-lg border border-violet-200 px-2.5 py-1 text-[10px] font-bold text-violet-600 hover:bg-violet-50 dark:border-violet-800/40 dark:text-violet-400 dark:hover:bg-violet-950/20 transition-all cursor-pointer"
                              >
                                Activate
                              </button>
                            )}
                          </div>
                          {!v.is_active && (
                            <div className="mt-2 flex items-center gap-3">
                              <span className="text-[10px] text-slate-500 shrink-0">A/B Split</span>
                              <input
                                type="range"
                                min={0}
                                max={100}
                                step={5}
                                defaultValue={v.traffic_split ?? 0}
                                onMouseUp={(e) => applyTrafficSplit(v.id, Number((e.target as HTMLInputElement).value))}
                                onTouchEnd={(e) => applyTrafficSplit(v.id, Number((e.target as HTMLInputElement).value))}
                                className="flex-1 h-1 accent-violet-600 cursor-pointer"
                              />
                              <span className="text-[10px] font-bold text-slate-400 w-8 text-right">{v.traffic_split ?? 0}%</span>
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </section>
            ) : tab === "runtime" ? (
              <section className="max-w-4xl space-y-6">
                {/* STT */}
                <CollapsibleSection title="Speech-to-Text (STT)" icon={Settings2} defaultOpen>
                  <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
                    <Field label="STT Provider">
                      <ProviderSelect value={runtimeDraft.stt_provider || ""} onChange={(v) => { setRuntimeDraft({ ...runtimeDraft, stt_provider: v }); markDirty(); }} options={["deepgram", "sarvam", "assemblyai", "groq", "inworld", "ringg_ai", "gladia", "cartesia", "smallest", "vachana"]} />
                    </Field>
                    {(!runtimeDraft.stt_provider || runtimeDraft.stt_provider === "deepgram") && (
                      <Field label="Deepgram Model">
                        <ProviderSelect value={(runtimeDraft.runtime_json?.stt_model as string) || ""} onChange={(v) => { setRuntimeDraft({ ...runtimeDraft, runtime_json: { ...runtimeDraft.runtime_json, stt_model: v } }); markDirty(); }} options={["nova-2", "nova-2-general", "nova-2-phone-call", "nova-2-meeting", "base"]} />
                      </Field>
                    )}
                    {runtimeDraft.stt_provider === "sarvam" && (
                      <Field label="Sarvam Language">
                        <ProviderSelect value={(runtimeDraft.runtime_json?.stt_language as string) || ""} onChange={(v) => { setRuntimeDraft({ ...runtimeDraft, runtime_json: { ...runtimeDraft.runtime_json, stt_language: v } }); markDirty(); }} options={["hi-IN", "en-IN", "ta-IN", "te-IN", "kn-IN", "ml-IN", "mr-IN", "bn-IN", "gu-IN", "pa-IN"]} />
                      </Field>
                    )}
                    {runtimeDraft.stt_provider === "assemblyai" && (
                      <Field label="AssemblyAI Model">
                        <ProviderSelect value={(runtimeDraft.runtime_json?.stt_model as string) || ""} onChange={(v) => { setRuntimeDraft({ ...runtimeDraft, runtime_json: { ...runtimeDraft.runtime_json, stt_model: v } }); markDirty(); }} options={["best", "nano"]} />
                      </Field>
                    )}
                    {runtimeDraft.stt_provider === "inworld" && (
                      <Field label="Inworld Model">
                        <input
                          className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500"
                          placeholder="inworld/inworld-stt-1"
                          value={(runtimeDraft.runtime_json?.stt_model as string) || ""}
                          onChange={(e) => { setRuntimeDraft({ ...runtimeDraft, runtime_json: { ...runtimeDraft.runtime_json, stt_model: e.target.value } }); markDirty(); }}
                        />
                      </Field>
                    )}
                    {runtimeDraft.stt_provider === "ringg_ai" && (
                      <Field label="Ringg Language">
                        <ProviderSelect value={(runtimeDraft.runtime_json?.stt_language as string) || ""} onChange={(v) => { setRuntimeDraft({ ...runtimeDraft, runtime_json: { ...runtimeDraft.runtime_json, stt_language: v } }); markDirty(); }} options={["en", "hi", "ta", "te", "kn", "ml", "mr", "bn", "gu", "pa"]} />
                      </Field>
                    )}
                    {runtimeDraft.stt_provider === "gladia" && (
                      <Field label="Gladia Language Code">
                        <input
                          className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500"
                          placeholder="en"
                          value={(runtimeDraft.runtime_json?.stt_language as string) || ""}
                          onChange={(e) => { setRuntimeDraft({ ...runtimeDraft, runtime_json: { ...runtimeDraft.runtime_json, stt_language: e.target.value } }); markDirty(); }}
                        />
                      </Field>
                    )}
                    {runtimeDraft.stt_provider === "vachana" && (
                      <>
                        <Field label="Vachana Language">
                          <ProviderSelect value={(runtimeDraft.runtime_json?.stt_language as string) || ""} onChange={(v) => { setRuntimeDraft({ ...runtimeDraft, runtime_json: { ...runtimeDraft.runtime_json, stt_language: v } }); markDirty(); }} options={["hi-IN", "en-IN", "ta-IN", "te-IN", "kn-IN", "ml-IN", "mr-IN", "bn-IN", "gu-IN", "pa-IN", "en-IN,hi-IN"]} />
                        </Field>
                        <Field label="Vachana Format">
                          <ProviderSelect value={(runtimeDraft.runtime_json?.stt_model as string) || ""} onChange={(v) => { setRuntimeDraft({ ...runtimeDraft, runtime_json: { ...runtimeDraft.runtime_json, stt_model: v } }); markDirty(); }} options={["verbatim", "transcribe"]} />
                        </Field>
                      </>
                    )}
                  </div>
                </CollapsibleSection>

                {/* TTS */}
                <CollapsibleSection title="Text-to-Speech (TTS)" icon={Settings2} defaultOpen>
                  <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
                    <Field label="TTS Provider">
                      <ProviderSelect value={runtimeDraft.tts_provider || ""} onChange={(v) => { setRuntimeDraft({ ...runtimeDraft, tts_provider: v }); markDirty(); }} options={["cartesia", "elevenlabs", "deepgram", "sarvam", "polly", "inworld", "smallest", "rime", "vachana"]} />
                    </Field>
                    {(!runtimeDraft.tts_provider || runtimeDraft.tts_provider === "cartesia") && (
                      <>
                        <Field label="Cartesia Voice ID">
                          <input
                            className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500"
                            placeholder="e.g. 79a125e8-cd45-4c13-8a67-188112f4dd22"
                            value={(runtimeDraft.runtime_json?.tts_voice_id as string) || ""}
                            onChange={(e) => { setRuntimeDraft({ ...runtimeDraft, runtime_json: { ...runtimeDraft.runtime_json, tts_voice_id: e.target.value } }); markDirty(); }}
                          />
                        </Field>
                        <Field label="Cartesia Model">
                          <ProviderSelect value={(runtimeDraft.runtime_json?.tts_model as string) || ""} onChange={(v) => { setRuntimeDraft({ ...runtimeDraft, runtime_json: { ...runtimeDraft.runtime_json, tts_model: v } }); markDirty(); }} options={["sonic-english", "sonic-multilingual", "sonic-2"]} />
                        </Field>
                      </>
                    )}
                    {runtimeDraft.tts_provider === "elevenlabs" && (
                      <>
                        <Field label="ElevenLabs Voice ID">
                          <input
                            className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500"
                            placeholder="e.g. EXAVITQu4vr4xnSDxMaL"
                            value={(runtimeDraft.runtime_json?.tts_voice_id as string) || ""}
                            onChange={(e) => { setRuntimeDraft({ ...runtimeDraft, runtime_json: { ...runtimeDraft.runtime_json, tts_voice_id: e.target.value } }); markDirty(); }}
                          />
                        </Field>
                        <Field label="ElevenLabs Model">
                          <ProviderSelect value={(runtimeDraft.runtime_json?.tts_model as string) || ""} onChange={(v) => { setRuntimeDraft({ ...runtimeDraft, runtime_json: { ...runtimeDraft.runtime_json, tts_model: v } }); markDirty(); }} options={["eleven_turbo_v2", "eleven_turbo_v2_5", "eleven_multilingual_v2", "eleven_flash_v2_5"]} />
                        </Field>
                      </>
                    )}
                    {runtimeDraft.tts_provider === "deepgram" && (
                      <Field label="Deepgram Voice">
                        <ProviderSelect value={(runtimeDraft.runtime_json?.tts_voice_id as string) || ""} onChange={(v) => { setRuntimeDraft({ ...runtimeDraft, runtime_json: { ...runtimeDraft.runtime_json, tts_voice_id: v } }); markDirty(); }} options={["aura-asteria-en", "aura-luna-en", "aura-stella-en", "aura-athena-en", "aura-hera-en", "aura-orion-en", "aura-arcas-en", "aura-perseus-en", "aura-angus-en", "aura-orpheus-en", "aura-helios-en", "aura-zeus-en"]} />
                      </Field>
                    )}
                    {runtimeDraft.tts_provider === "sarvam" && (
                      <>
                        <Field label="Sarvam Voice">
                          <ProviderSelect value={(runtimeDraft.runtime_json?.tts_voice_id as string) || ""} onChange={(v) => { setRuntimeDraft({ ...runtimeDraft, runtime_json: { ...runtimeDraft.runtime_json, tts_voice_id: v } }); markDirty(); }} options={["meera", "pavithra", "maitreyi", "arvind", "amol", "amartya", "diya", "neel", "misha", "vian", "arjun", "maya"]} />
                        </Field>
                        <Field label="Sarvam Language">
                          <ProviderSelect value={(runtimeDraft.runtime_json?.tts_language as string) || ""} onChange={(v) => { setRuntimeDraft({ ...runtimeDraft, runtime_json: { ...runtimeDraft.runtime_json, tts_language: v } }); markDirty(); }} options={["hi-IN", "en-IN", "ta-IN", "te-IN", "kn-IN", "ml-IN", "mr-IN", "bn-IN", "gu-IN", "pa-IN"]} />
                        </Field>
                      </>
                    )}
                    {runtimeDraft.tts_provider === "polly" && (
                      <>
                        <Field label="Polly Voice">
                          <ProviderSelect value={(runtimeDraft.runtime_json?.tts_voice_id as string) || ""} onChange={(v) => { setRuntimeDraft({ ...runtimeDraft, runtime_json: { ...runtimeDraft.runtime_json, tts_voice_id: v } }); markDirty(); }} options={["Kajal", "Aditi", "Joanna", "Matthew", "Raveena", "Aria"]} />
                        </Field>
                        <Field label="Polly Engine">
                          <ProviderSelect value={(runtimeDraft.runtime_json?.tts_model as string) || ""} onChange={(v) => { setRuntimeDraft({ ...runtimeDraft, runtime_json: { ...runtimeDraft.runtime_json, tts_model: v } }); markDirty(); }} options={["neural", "standard"]} />
                        </Field>
                      </>
                    )}
                    {runtimeDraft.tts_provider === "vachana" && (
                      <>
                        <Field label="Vachana Voice">
                          <ProviderSelect value={(runtimeDraft.runtime_json?.tts_voice_id as string) || ""} onChange={(v) => { setRuntimeDraft({ ...runtimeDraft, runtime_json: { ...runtimeDraft.runtime_json, tts_voice_id: v } }); markDirty(); }} options={["Karan", "Simran", "Nara", "Riya", "Viraj", "Raju"]} />
                        </Field>
                        <Field label="Vachana Model">
                          <ProviderSelect value={(runtimeDraft.runtime_json?.tts_model as string) || ""} onChange={(v) => { setRuntimeDraft({ ...runtimeDraft, runtime_json: { ...runtimeDraft.runtime_json, tts_model: v } }); markDirty(); }} options={["vachana-voice-v3"]} />
                        </Field>
                      </>
                    )}
                    {runtimeDraft.tts_provider === "inworld" && (
                      <>
                        <Field label="Inworld Voice ID">
                          <input
                            className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500"
                            placeholder="inworld-asteria-en"
                            value={(runtimeDraft.runtime_json?.tts_voice_id as string) || ""}
                            onChange={(e) => { setRuntimeDraft({ ...runtimeDraft, runtime_json: { ...runtimeDraft.runtime_json, tts_voice_id: e.target.value } }); markDirty(); }}
                          />
                        </Field>
                        <Field label="Inworld Model">
                          <input
                            className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500"
                            placeholder="inworld-tts-1"
                            value={(runtimeDraft.runtime_json?.tts_model as string) || ""}
                            onChange={(e) => { setRuntimeDraft({ ...runtimeDraft, runtime_json: { ...runtimeDraft.runtime_json, tts_model: e.target.value } }); markDirty(); }}
                          />
                        </Field>
                      </>
                    )}
                    {runtimeDraft.tts_provider === "smallest" && (
                      <>
                        <Field label="Smallest Voice">
                          <ProviderSelect value={(runtimeDraft.runtime_json?.tts_voice_id as string) || ""} onChange={(v) => { setRuntimeDraft({ ...runtimeDraft, runtime_json: { ...runtimeDraft.runtime_json, tts_voice_id: v } }); markDirty(); }} options={["meher", "riya", "arjun", "maya"]} />
                        </Field>
                        <Field label="Smallest Model">
                          <ProviderSelect value={(runtimeDraft.runtime_json?.tts_model as string) || ""} onChange={(v) => { setRuntimeDraft({ ...runtimeDraft, runtime_json: { ...runtimeDraft.runtime_json, tts_model: v } }); markDirty(); }} options={["lightning_v3.1_pro", "lightning"]} />
                        </Field>
                      </>
                    )}
                    {runtimeDraft.tts_provider === "rime" && (
                      <Field label="Rime Voice ID">
                        <input
                          className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500"
                          placeholder="e.g. aria"
                          value={(runtimeDraft.runtime_json?.tts_voice_id as string) || ""}
                          onChange={(e) => { setRuntimeDraft({ ...runtimeDraft, runtime_json: { ...runtimeDraft.runtime_json, tts_voice_id: e.target.value } }); markDirty(); }}
                        />
                      </Field>
                    )}
                  </div>
                </CollapsibleSection>

                {/* LLM */}
                <CollapsibleSection title="Language Model (LLM)" icon={Sparkles} defaultOpen>
                  <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
                    <Field label="LLM Provider">
                      <ProviderSelect value={runtimeDraft.llm_provider || ""} onChange={(v) => setRuntimeDraft({ ...runtimeDraft, llm_provider: v })} options={["mistral", "openai", "gemini", "groq", "anthropic", "openrouter", "cerebras"]} />
                    </Field>
                    {(!runtimeDraft.llm_provider || runtimeDraft.llm_provider === "mistral") && (
                      <Field label="Mistral Model">
                        <ProviderSelect value={(runtimeDraft.runtime_json?.llm_model as string) || ""} onChange={(v) => setRuntimeDraft({ ...runtimeDraft, runtime_json: { ...runtimeDraft.runtime_json, llm_model: v } })} options={["mistral-large-latest", "mistral-small-latest", "open-mistral-7b", "open-mixtral-8x7b"]} />
                      </Field>
                    )}
                    {runtimeDraft.llm_provider === "openai" && (
                      <Field label="OpenAI Model">
                        <ProviderSelect value={(runtimeDraft.runtime_json?.llm_model as string) || ""} onChange={(v) => setRuntimeDraft({ ...runtimeDraft, runtime_json: { ...runtimeDraft.runtime_json, llm_model: v } })} options={["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"]} />
                      </Field>
                    )}
                    {runtimeDraft.llm_provider === "gemini" && (
                      <Field label="Gemini Model">
                        <ProviderSelect value={(runtimeDraft.runtime_json?.llm_model as string) || ""} onChange={(v) => setRuntimeDraft({ ...runtimeDraft, runtime_json: { ...runtimeDraft.runtime_json, llm_model: v } })} options={["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash-lite"]} />
                      </Field>
                    )}
                    {runtimeDraft.llm_provider === "anthropic" && (
                      <Field label="Anthropic Model">
                        <ProviderSelect value={(runtimeDraft.runtime_json?.llm_model as string) || ""} onChange={(v) => setRuntimeDraft({ ...runtimeDraft, runtime_json: { ...runtimeDraft.runtime_json, llm_model: v } })} options={["claude-haiku-4-5-20251001", "claude-sonnet-4-6", "claude-opus-4-7"]} />
                      </Field>
                    )}
                    {runtimeDraft.llm_provider === "groq" && (
                      <Field label="Groq Model">
                        <ProviderSelect value={(runtimeDraft.runtime_json?.llm_model as string) || ""} onChange={(v) => setRuntimeDraft({ ...runtimeDraft, runtime_json: { ...runtimeDraft.runtime_json, llm_model: v } })} options={["llama-3.1-8b-instant", "llama-3.1-70b-versatile", "llama3-8b-8192", "mixtral-8x7b-32768"]} />
                      </Field>
                    )}
                    {runtimeDraft.llm_provider === "openrouter" && (
                      <Field label="OpenRouter Model">
                        <input 
                          className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500" 
                          placeholder="e.g. meta-llama/llama-3.1-8b-instruct" 
                          value={(runtimeDraft.runtime_json?.llm_model as string) || ""} 
                          onChange={(e) => setRuntimeDraft({ ...runtimeDraft, runtime_json: { ...runtimeDraft.runtime_json, llm_model: e.target.value } })} 
                        />
                      </Field>
                    )}
                    {runtimeDraft.llm_provider === "cerebras" && (
                      <Field label="Cerebras Model">
                        <ProviderSelect value={(runtimeDraft.runtime_json?.llm_model as string) || ""} onChange={(v) => setRuntimeDraft({ ...runtimeDraft, runtime_json: { ...runtimeDraft.runtime_json, llm_model: v } })} options={["llama3.1-8b", "llama3.1-70b", "llama-3.3-70b"]} />
                      </Field>
                    )}
                  </div>
                </CollapsibleSection>

                {/* Call Settings */}
                <CollapsibleSection title="Call Settings" icon={PhoneCall} defaultOpen>
                  <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
                    <Field label="Telephony Engine">
                      <ProviderSelect value={runtimeDraft.telephony_engine || ""} onChange={(v) => setRuntimeDraft({ ...runtimeDraft, telephony_engine: v })} options={["twilio", "exotel", "enablex", "vobiz", "plivo"]} />
                    </Field>
                    <Field label="Language">
                      <ProviderSelect value={runtimeDraft.language || "en-IN"} onChange={(v) => { setRuntimeDraft({ ...runtimeDraft, language: v }); markDirty(); }} options={["en-IN", "hi-IN", "en-US", "ta-IN", "te-IN", "kn-IN", "ml-IN", "mr-IN", "bn-IN", "gu-IN", "pa-IN"]} />
                    </Field>
                    <Field label="Verbosity (1=brief, 3=detailed)">
                      <ProviderSelect value={runtimeDraft.ai_verbosity || "2"} onChange={(v) => setRuntimeDraft({ ...runtimeDraft, ai_verbosity: v })} options={["1", "2", "3"]} />
                    </Field>
                    <Field label="Max Call Duration (seconds)">
                      <input 
                        className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500" 
                        type="number" 
                        placeholder="e.g. 300" 
                        value={runtimeDraft.max_call_duration_seconds ?? ""} 
                        onChange={(e) => setRuntimeDraft({ ...runtimeDraft, max_call_duration_seconds: e.target.value ? Number(e.target.value) : null })} 
                      />
                    </Field>
                    <Field label="Silence Re-engage (seconds)">
                      <input 
                        className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500" 
                        type="number" 
                        placeholder="e.g. 8" 
                        value={runtimeDraft.silence_reengage_seconds ?? ""} 
                        onChange={(e) => setRuntimeDraft({ ...runtimeDraft, silence_reengage_seconds: e.target.value ? Number(e.target.value) : null })} 
                      />
                    </Field>
                  </div>
                </CollapsibleSection>

                {/* Barge-in Tuning */}
                <CollapsibleSection title="Barge-in Tuning" icon={Shield}>
                  <p className="text-xs text-slate-500 mb-5">Per-agent override of interrupt sensitivity. Leave blank to use env defaults.</p>
                  <div className="grid grid-cols-1 gap-5 md:grid-cols-3">
                    <Field label="RMS Threshold (loudness)">
                      <input className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500" type="number" placeholder="1200" value={rjGet(["barge_in", "rms_threshold"])} onChange={(e) => rjSet(["barge_in", "rms_threshold"], e.target.value ? Number(e.target.value) : "")} />
                    </Field>
                    <Field label="Frames Needed (consecutive)">
                      <input className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500" type="number" placeholder="8" value={rjGet(["barge_in", "frames_needed"])} onChange={(e) => rjSet(["barge_in", "frames_needed"], e.target.value ? Number(e.target.value) : "")} />
                    </Field>
                    <Field label="TTS Guard (ms after agent starts)">
                      <input className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500" type="number" placeholder="1500" value={rjGet(["barge_in", "tts_guard_ms"])} onChange={(e) => rjSet(["barge_in", "tts_guard_ms"], e.target.value ? Number(e.target.value) : "")} />
                    </Field>
                    <Field label="Post-speech Cooldown (ms)">
                      <input className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500" type="number" placeholder="1200" value={rjGet(["barge_in", "post_speech_cooldown_ms"])} onChange={(e) => rjSet(["barge_in", "post_speech_cooldown_ms"], e.target.value ? Number(e.target.value) : "")} />
                    </Field>
                    <div className="flex items-center justify-between rounded-xl border border-slate-200 bg-white/30 px-4 py-2.5 dark:border-slate-800 dark:bg-slate-950/20">
                      <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Use Silero VAD</span>
                      <button onClick={() => rjSet(["barge_in", "use_silero_vad"], rjGet(["barge_in", "use_silero_vad"]) === "true" ? false : true)} className={clsx("relative h-5 w-9 rounded-full transition-colors cursor-pointer", rjGet(["barge_in", "use_silero_vad"]) === "true" ? "bg-violet-600" : "bg-slate-300 dark:bg-slate-600")}>
                        <span className={clsx("absolute left-0 top-0.5 h-4 w-4 rounded-full bg-white transition-transform", rjGet(["barge_in", "use_silero_vad"]) === "true" ? "translate-x-4" : "translate-x-0.5")} />
                      </button>
                    </div>
                    <div className="flex items-center justify-between rounded-xl border border-slate-200 bg-white/30 px-4 py-2.5 dark:border-slate-800 dark:bg-slate-950/20">
                      <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Disable Barge-in</span>
                      <button onClick={() => rjSet(["barge_in", "disabled"], rjGet(["barge_in", "disabled"]) === "true" ? false : true)} className={clsx("relative h-5 w-9 rounded-full transition-colors cursor-pointer", rjGet(["barge_in", "disabled"]) === "true" ? "bg-red-500" : "bg-slate-300 dark:bg-slate-600")}>
                        <span className={clsx("absolute left-0 top-0.5 h-4 w-4 rounded-full bg-white transition-transform", rjGet(["barge_in", "disabled"]) === "true" ? "translate-x-4" : "translate-x-0.5")} />
                      </button>
                    </div>
                  </div>
                </CollapsibleSection>

                {/* Silence Watcher */}
                <CollapsibleSection title="Silence Watcher" icon={Sliders}>
                  <p className="text-xs text-slate-500 mb-5">How long to wait after agent finishes before re-engaging. Leave blank for env defaults.</p>
                  <div className="grid grid-cols-1 gap-5 md:grid-cols-3">
                    <Field label="Silence Threshold (seconds)">
                      <input className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500" type="number" placeholder="6" value={rjGet(["silence", "threshold_s"])} onChange={(e) => rjSet(["silence", "threshold_s"], e.target.value ? Number(e.target.value) : "")} />
                    </Field>
                    <Field label="Check Interval (seconds)">
                      <input className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500" type="number" placeholder="3" value={rjGet(["silence", "check_interval_s"])} onChange={(e) => rjSet(["silence", "check_interval_s"], e.target.value ? Number(e.target.value) : "")} />
                    </Field>
                    <Field label="Max Re-engages per Call">
                      <input className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500" type="number" placeholder="1" min={0} max={5} value={rjGet(["silence", "max_reengages"])} onChange={(e) => rjSet(["silence", "max_reengages"], e.target.value ? Number(e.target.value) : "")} />
                    </Field>
                  </div>
                </CollapsibleSection>

                {/* Feedback Phrase */}
                <CollapsibleSection title="End-of-call Feedback Phrase" icon={MessageSquare}>
                  <p className="text-xs text-slate-500 mb-5">Injected before goodbye if the agent hasn't asked for a 1-5 rating.</p>
                  <Field label="Feedback Phrase">
                    <input className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500" placeholder="Before we wrap up — on a scale of 1 to 5, how would you rate your experience speaking with me today?" value={rjGet(["feedback_phrase"])} onChange={(e) => rjSet(["feedback_phrase"], e.target.value || "")} />
                  </Field>
                </CollapsibleSection>

                <ActionButton onClick={saveRuntime} saving={saving} label="Save Runtime" />
              </section>
            ) : tab === "chat" ? (
              <AgentChatPanel agentId={selected.agent.id} />
            ) : tab === "web_call" ? (
              <AgentChatPanel agentId={selected.agent.id} initialMode="web_call" />
            ) : tab === "tools" ? (
              <section className="max-w-5xl space-y-6">
                {/* Built-in tools */}
                <CollapsibleSection title="Built-in Tools" icon={Wrench} defaultOpen>
                  <div className="flex items-center justify-between rounded-xl border border-slate-200/50 bg-white/40 p-4 dark:border-slate-800/30 dark:bg-slate-900/30">
                    <div>
                      <p className="text-sm font-semibold">Calendar Booking</p>
                      <p className="text-xs text-slate-500 mt-0.5 font-medium">Agent can book Google Calendar meetings during a call</p>
                    </div>
                    <button
                      onClick={async () => {
                        // Treat legacy "calendar_book" rows (from before the booking-tool
                        // consolidation) as the same toggle state as "book_demo".
                        const existing = tools.find((t) => t.tool_type === "book_demo" || t.tool_type === "calendar_book");
                        if (existing) {
                          await apiFetch(`${API_BASE}/crm/voice-agents/${selected!.agent.id}/tools/${existing.id}`, { method: "DELETE" });
                        } else {
                          await apiFetch(`${API_BASE}/crm/voice-agents/${selected!.agent.id}/tools`, {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ name: "book_demo", description: "Book a demo/meeting on Google Calendar (online demos include a Meet link)", tool_type: "book_demo", http_method: null, url: null, input_extraction_schema: {}, is_active: true }),
                          });
                        }
                        const res = await apiFetch(`${API_BASE}/crm/voice-agents/${selected!.agent.id}/tools`, {});
                        if (res.ok) setTools(await res.json());
                      }}
                      className={clsx(
                        "relative h-6 w-11 rounded-full transition-colors cursor-pointer",
                        tools.some((t) => t.tool_type === "book_demo" || t.tool_type === "calendar_book") ? "bg-violet-600" : "bg-slate-300 dark:bg-slate-600"
                      )}
                    >
                      <span className={clsx(
                        "absolute left-0 top-1 h-4 w-4 rounded-full bg-white transition-transform",
                        tools.some((t) => t.tool_type === "book_demo" || t.tool_type === "calendar_book") ? "translate-x-6" : "translate-x-1"
                      )} />
                    </button>
                  </div>
                </CollapsibleSection>

                {/* Custom HTTP tools */}
                <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_380px]">
                  <div>
                    <p className="text-sm font-bold bg-gradient-to-r from-slate-800 to-slate-600 dark:from-slate-200 dark:to-slate-400 bg-clip-text text-transparent mb-3">Custom HTTP Tools</p>
                    <ListPanel items={tools.filter(t => t.tool_type !== "book_demo" && t.tool_type !== "calendar_book").map((tool) => ({
                    label: `${tool.name} · ${tool.http_method || tool.tool_type} · ${tool.is_active ? "active" : "off"}`,
                    onDelete: async () => {
                      await apiFetch(`${API_BASE}/crm/voice-agents/${selected!.agent.id}/tools/${tool.id}`, { method: "DELETE" });
                      await loadTabData(selected!.agent.id, "tools");
                    },
                  }))} />
                  </div>
                  <div className="space-y-4 rounded-2xl border border-slate-200/60 bg-white/60 p-6 shadow-sm backdrop-blur-sm dark:border-slate-800/40 dark:bg-slate-900/40">
                    <Field label="Tool Name">
                      <input 
                        className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500" 
                        value={toolDraft.name} 
                        onChange={(e) => setToolDraft({ ...toolDraft, name: e.target.value })} 
                      />
                    </Field>
                    <Field label="Description">
                      <input 
                        className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500" 
                        value={toolDraft.description} 
                        onChange={(e) => setToolDraft({ ...toolDraft, description: e.target.value })} 
                      />
                    </Field>
                    <Field label="Method">
                      <ProviderSelect value={toolDraft.http_method} onChange={(v) => setToolDraft({ ...toolDraft, http_method: v })} options={["GET", "POST", "PUT", "PATCH"]} />
                    </Field>
                    <Field label="URL">
                      <input 
                        className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500" 
                        value={toolDraft.url} 
                        onChange={(e) => setToolDraft({ ...toolDraft, url: e.target.value })} 
                      />
                    </Field>
                    <button 
                      onClick={createTool} 
                      className="inline-flex items-center gap-2 justify-center rounded-xl bg-gradient-to-r from-violet-600 to-indigo-600 px-4 py-2.5 text-xs font-semibold text-white shadow-md shadow-violet-500/10 hover:from-violet-500 hover:to-indigo-500 hover:shadow-violet-500/25 active:scale-95 transition-all w-full cursor-pointer"
                    >
                      <Plus className="h-3.5 w-3.5" /> Add Tool
                    </button>
                  </div>
                </div>
              </section>
            ) : tab === "extractions" ? (
              <section className="max-w-6xl space-y-6">
                <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_420px]">
                <div>
                  <p className="text-sm font-bold bg-gradient-to-r from-slate-800 to-slate-600 dark:from-slate-200 dark:to-slate-400 bg-clip-text text-transparent mb-3">Extraction Schema Templates</p>
                  <ListPanel items={templates.map((tpl) => ({
                    label: `${tpl.name} · ${tpl.is_active ? "active" : "off"}`,
                    onDelete: async () => {
                      await apiFetch(`${API_BASE}/crm/voice-agents/${selected!.agent.id}/extraction-templates/${tpl.id}`, { method: "DELETE" });
                      await loadTabData(selected!.agent.id, "extractions");
                    },
                  }))} />
                </div>
                <div className="space-y-4 rounded-2xl border border-slate-200/60 bg-white/60 p-6 shadow-sm backdrop-blur-sm dark:border-slate-800/40 dark:bg-slate-900/40">
                  <Field label="Template Name">
                    <input 
                      className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500" 
                      value={templateDraft.name} 
                      onChange={(e) => setTemplateDraft({ ...templateDraft, name: e.target.value })} 
                    />
                  </Field>
                  <Field label="Instructions">
                    <textarea 
                      className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500 min-h-24" 
                      value={templateDraft.instructions} 
                      onChange={(e) => setTemplateDraft({ ...templateDraft, instructions: e.target.value })} 
                    />
                  </Field>
                  <Field label="Schema JSON">
                    <textarea 
                      className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500 min-h-40 font-mono" 
                      value={templateDraft.extraction_schema} 
                      onChange={(e) => setTemplateDraft({ ...templateDraft, extraction_schema: e.target.value })} 
                    />
                  </Field>
                  <button
                    onClick={createTemplate}
                    className="inline-flex items-center gap-2 justify-center rounded-xl bg-gradient-to-r from-violet-600 to-indigo-600 px-4 py-2.5 text-xs font-semibold text-white shadow-md shadow-violet-500/10 hover:from-violet-500 hover:to-indigo-500 hover:shadow-violet-500/25 active:scale-95 transition-all w-full cursor-pointer"
                  >
                    <Plus className="h-3.5 w-3.5" /> Add Template
                  </button>
                </div>
                </div>

                {/* Extraction Results Viewer */}
                {extractionResults.length > 0 && (
                  <div className="rounded-2xl border border-slate-200/60 bg-white/60 p-6 shadow-sm backdrop-blur-sm dark:border-slate-800/40 dark:bg-slate-900/40">
                    <p className="text-sm font-bold bg-gradient-to-r from-slate-800 to-slate-600 dark:from-slate-200 dark:to-slate-400 bg-clip-text text-transparent mb-4">
                      Extraction Results ({extractionResults.length})
                    </p>
                    <div className="space-y-2">
                      {extractionResults.map((r) => (
                        <div key={r.id} className="rounded-xl border border-slate-200/60 dark:border-slate-800/40 overflow-hidden">
                          <button
                            onClick={() => setExpandedResult(expandedResult === r.id ? null : r.id)}
                            className="w-full flex items-center justify-between px-4 py-3 hover:bg-slate-50/50 dark:hover:bg-slate-950/10 transition-colors cursor-pointer"
                          >
                            <div className="flex items-center gap-3 text-xs">
                              <span className={`rounded-md px-1.5 py-0.5 font-bold ${r.status === "completed" ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-400" : "bg-red-100 text-red-700 dark:bg-red-950/30 dark:text-red-400"}`}>{r.status}</span>
                              <span className="font-semibold text-slate-700 dark:text-slate-300">{r.template_name}</span>
                              {r.interaction_id && <span className="text-slate-400">call #{r.interaction_id}</span>}
                            </div>
                            <div className="flex items-center gap-2">
                              <span className="text-[10px] text-slate-400">{new Date(r.created_at).toLocaleDateString()}</span>
                              {expandedResult === r.id ? <ChevronUp className="h-3.5 w-3.5 text-slate-400" /> : <ChevronDown className="h-3.5 w-3.5 text-slate-400" />}
                            </div>
                          </button>
                          {expandedResult === r.id && (
                            <pre className="overflow-x-auto bg-slate-950 px-4 py-3 text-[11px] font-mono text-slate-300 border-t border-slate-900 max-h-64">
                              {JSON.stringify(r.output_json, null, 2)}
                            </pre>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </section>
            ) : tab === "ivr" ? (
              <section className="max-w-3xl space-y-6">
                {/* Enable toggle */}
                <div className="flex items-center justify-between rounded-2xl border border-slate-200/60 bg-white/60 p-6 shadow-sm backdrop-blur-sm dark:border-slate-800/40 dark:bg-slate-900/40">
                  <div>
                    <p className="font-bold text-sm bg-gradient-to-r from-slate-800 to-slate-600 dark:from-slate-200 dark:to-slate-400 bg-clip-text text-transparent">Enable IVR Menu</p>
                    <p className="text-xs text-slate-500 mt-1 font-medium">Play an interactive menu before connecting the AI agent</p>
                  </div>
                  <button
                    onClick={() => setIVRMenu({ ...ivrMenu, enabled: !ivrMenu.enabled })}
                    className={clsx("relative h-6 w-11 rounded-full transition-colors cursor-pointer", ivrMenu.enabled ? "bg-violet-600" : "bg-slate-300 dark:bg-slate-600")}
                  >
                    <span className={clsx("absolute left-0 top-1 h-4 w-4 rounded-full bg-white transition-transform", ivrMenu.enabled ? "translate-x-6" : "translate-x-1")} />
                  </button>
                </div>

                {ivrMenu.enabled && (
                  <>
                    <div className="rounded-2xl border border-slate-200/60 bg-white/60 p-6 shadow-sm backdrop-blur-sm dark:border-slate-800/40 dark:bg-slate-900/40 space-y-5">
                      <Field label="Greeting Message">
                        <textarea 
                          className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500 min-h-20" 
                          value={ivrMenu.greeting} 
                          onChange={(e) => setIVRMenu({ ...ivrMenu, greeting: e.target.value })} 
                        />
                      </Field>
                      <Field label="Input Timeout (seconds)">
                        <input 
                          className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500" 
                          type="number" 
                          min={1} 
                          max={30} 
                          value={ivrMenu.timeout_seconds} 
                          onChange={(e) => setIVRMenu({ ...ivrMenu, timeout_seconds: Number(e.target.value) })} 
                        />
                      </Field>
                    </div>

                    {/* Options */}
                    <div className="rounded-2xl border border-slate-200/60 bg-white/60 p-6 shadow-sm backdrop-blur-sm dark:border-slate-800/40 dark:bg-slate-900/40">
                      <div className="mb-4 flex items-center justify-between">
                        <span className="text-sm font-bold bg-gradient-to-r from-slate-800 to-slate-600 dark:from-slate-200 dark:to-slate-400 bg-clip-text text-transparent">Menu Options</span>
                        <button
                          onClick={() => setIVRMenu({ ...ivrMenu, options: [...ivrMenu.options, { digit: String(ivrMenu.options.length + 1), label: "", action: "agent" }] })}
                          className="inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs font-semibold text-violet-600 dark:text-violet-400 hover:bg-violet-50/50 dark:hover:bg-violet-950/20 transition-all cursor-pointer"
                        >
                          <Plus className="h-3.5 w-3.5" /> Add Option
                        </button>
                      </div>
                      <div className="space-y-4">
                        {ivrMenu.options.map((opt, idx) => (
                          <div key={idx} className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900 shadow-sm relative group">
                            <div className="flex items-start gap-4">
                              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-violet-100 to-indigo-100 text-sm font-extrabold text-violet-700 dark:from-violet-950/60 dark:to-indigo-950/60 dark:text-violet-300">
                                {opt.digit}
                              </div>
                              <div className="flex-1 grid grid-cols-1 gap-3 sm:grid-cols-3">
                                <label className="block">
                                  <span className="mb-1 block text-[10px] font-bold uppercase tracking-wider text-slate-400">Digit</span>
                                  <select 
                                    className="w-full rounded-xl border border-slate-200 bg-white/50 px-3 py-1.5 text-xs outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500" 
                                    value={opt.digit} 
                                    onChange={(e) => {
                                      const updated = [...ivrMenu.options];
                                      updated[idx] = { ...opt, digit: e.target.value };
                                      setIVRMenu({ ...ivrMenu, options: updated });
                                    }}
                                  >
                                    {["0","1","2","3","4","5","6","7","8","9","*","#"].map((d) => <option key={d} value={d}>{d}</option>)}
                                  </select>
                                </label>
                                <label className="block">
                                  <span className="mb-1 block text-[10px] font-bold uppercase tracking-wider text-slate-400">Label</span>
                                  <input 
                                    className="w-full rounded-xl border border-slate-200 bg-white/50 px-3 py-1.5 text-xs outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500" 
                                    placeholder="Sales" 
                                    value={opt.label} 
                                    onChange={(e) => {
                                      const updated = [...ivrMenu.options];
                                      updated[idx] = { ...opt, label: e.target.value };
                                      setIVRMenu({ ...ivrMenu, options: updated });
                                    }} 
                                  />
                                </label>
                                <label className="block">
                                  <span className="mb-1 block text-[10px] font-bold uppercase tracking-wider text-slate-400">Action</span>
                                  <select 
                                    className="w-full rounded-xl border border-slate-200 bg-white/50 px-3 py-1.5 text-xs outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500" 
                                    value={opt.action} 
                                    onChange={(e) => {
                                      const updated = [...ivrMenu.options];
                                      updated[idx] = { ...opt, action: e.target.value as IVROption["action"] };
                                      setIVRMenu({ ...ivrMenu, options: updated });
                                    }}
                                  >
                                    <option value="agent">Connect AI Agent</option>
                                    <option value="transfer">Transfer to Number</option>
                                    <option value="hangup">Hang Up</option>
                                  </select>
                                </label>
                                {opt.action === "transfer" && (
                                  <label className="block sm:col-span-3">
                                    <span className="mb-1 block text-[10px] font-bold uppercase tracking-wider text-slate-400">Transfer To</span>
                                    <input 
                                      className="w-full rounded-xl border border-slate-200 bg-white/50 px-3 py-1.5 text-xs outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500" 
                                      placeholder="+919876543210" 
                                      value={opt.transfer_to || ""} 
                                      onChange={(e) => {
                                        const updated = [...ivrMenu.options];
                                        updated[idx] = { ...opt, transfer_to: e.target.value };
                                        setIVRMenu({ ...ivrMenu, options: updated });
                                      }} 
                                    />
                                  </label>
                                )}
                              </div>
                              <button 
                                onClick={() => {
                                  const updated = ivrMenu.options.filter((_, i) => i !== idx);
                                  setIVRMenu({ ...ivrMenu, options: updated });
                                }} 
                                className="absolute right-3 top-3 text-slate-400 hover:text-red-500 transition-colors opacity-0 group-hover:opacity-100 cursor-pointer"
                              >
                                <X className="h-4 w-4" />
                              </button>
                            </div>
                          </div>
                        ))}
                        {ivrMenu.options.length === 0 && (
                          <div className="rounded-xl border border-dashed border-slate-200 dark:border-slate-800/80 p-8 text-center text-xs font-semibold text-slate-400">
                            No options yet. Add an option above.
                          </div>
                        )}
                      </div>
                    </div>
                  </>
                )}

                <ActionButton onClick={saveIVR} saving={saving} label="Save IVR Config" />
              </section>
            ) : tab === "call" ? (
              <section className="max-w-3xl space-y-6">
                <CallFeaturesEditor value={callFeatures} onChange={setCallFeatures} />
                <div className="pt-2">
                  <ActionButton onClick={saveCallFeatures} saving={saving} label="Save Call Features" />
                </div>
              </section>
            ) : tab === "graph" ? (
              <section className="max-w-6xl space-y-6">
                <GraphEditor
                  graphJson={graphJson}
                  onChange={setGraphJson}
                  onSave={saveGraph}
                  saving={saving}
                />
              </section>
            ) : (
              <section className="max-w-5xl space-y-4">
                {events.length > 0 && (
                  <div className="flex items-center gap-3">
                    <label className="text-xs font-bold uppercase text-slate-400">Filter</label>
                    <select
                      className="rounded-xl border border-slate-200 bg-white/50 px-3 py-1.5 text-xs font-medium outline-none focus:border-violet-500 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 cursor-pointer"
                      value={eventFilter}
                      onChange={(e) => setEventFilter(e.target.value)}
                    >
                      <option value="">All events</option>
                      {[...new Set(events.map(e => e.event_type))].map(t => (
                        <option key={t} value={t}>{t}</option>
                      ))}
                    </select>
                    <span className="text-xs text-slate-400 font-medium">{events.filter(e => !eventFilter || e.event_type === eventFilter).length} events</span>
                  </div>
                )}
                {events.length === 0 ? (
                  <div className="rounded-2xl border border-dashed border-slate-200 bg-white/40 p-12 text-center text-sm font-semibold text-slate-400 dark:border-slate-800/40 dark:bg-slate-900/20">
                    No execution events yet.
                  </div>
                ) : (
                  events.filter(e => !eventFilter || e.event_type === eventFilter).map((event) => (
                    <div key={event.id} className="rounded-2xl border border-slate-200/60 bg-white/60 p-6 shadow-sm backdrop-blur-sm dark:border-slate-800/40 dark:bg-slate-900/40 transition-all duration-300 hover:shadow-md hover:border-violet-500/10">
                      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 pb-3 mb-4 dark:border-slate-800/40">
                        <div className="flex items-center gap-2.5 font-bold text-sm bg-gradient-to-r from-violet-600 to-indigo-600 bg-clip-text text-transparent dark:from-violet-400 dark:to-indigo-400">
                          <TerminalSquare className="h-4 w-4 text-violet-500" /> {event.event_type}
                        </div>
                        <span className="text-[11px] font-semibold text-slate-400">{new Date(event.created_at).toLocaleString()}</span>
                      </div>
                      {event.summary && <p className="text-sm font-medium text-slate-600 dark:text-slate-300 mb-3">{event.summary}</p>}
                      <pre className="overflow-x-auto rounded-xl bg-slate-950 p-4 text-[11px] font-mono text-slate-300 border border-slate-900 shadow-inner max-h-96">{JSON.stringify(event.payload || {}, null, 2)}</pre>
                    </div>
                  ))
                )}
              </section>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-2 block text-xs font-bold uppercase tracking-wider text-slate-400">{label}</span>
      {children}
    </label>
  );
}

function ProviderSelect({ value, onChange, options }: { value: string; onChange: (value: string) => void; options: string[] }) {
  return (
    <select 
      className="w-full rounded-xl border border-slate-200 bg-white/50 px-4 py-2.5 text-sm outline-none transition-all duration-300 focus:border-violet-500 focus:ring-4 focus:ring-violet-500/10 dark:border-slate-800 dark:bg-slate-950/40 dark:text-slate-100 dark:focus:border-violet-500 cursor-pointer" 
      value={value} 
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="">Company default</option>
      {options.map((option) => (
        <option key={option} value={option}>{option}</option>
      ))}
    </select>
  );
}

function ActionButton({ onClick, saving, label }: { onClick: () => void; saving: boolean; label: string }) {
  return (
    <button 
      onClick={onClick} 
      disabled={saving} 
      className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-indigo-600 px-6 py-3 text-xs font-bold text-white shadow-lg shadow-violet-500/25 hover:from-violet-500 hover:to-indigo-500 hover:shadow-violet-500/35 active:scale-98 transition-all disabled:opacity-60 cursor-pointer"
    >
      {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
      {label}
    </button>
  );
}

type ListItem = { label: string; onDelete?: () => void };

function ListPanel({ items }: { items: ListItem[] }) {
  return (
    <div className="rounded-2xl border border-slate-200/60 bg-white/60 backdrop-blur-sm dark:border-slate-800/40 dark:bg-slate-900/40 shadow-sm overflow-hidden">
      {items.length === 0 ? (
        <div className="p-12 text-center text-xs font-semibold text-slate-400">No records yet.</div>
      ) : (
        <div className="divide-y divide-slate-100 dark:divide-slate-800/60">
          {items.map((item, i) => (
            <div key={i} className="flex items-center justify-between px-5 py-4 hover:bg-slate-50/50 dark:hover:bg-slate-950/10 transition-colors group">
              <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">{item.label}</span>
              {item.onDelete && (
                <button
                  onClick={item.onDelete}
                  className="opacity-0 group-hover:opacity-100 text-slate-300 hover:text-red-500 transition-all cursor-pointer"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
