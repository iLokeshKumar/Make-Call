"use client";

import { useState, useEffect, useCallback } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { Save, Brain, Bell, Zap, Sun, Moon, Monitor, Loader2, CheckCircle2, PhoneForwarded, KeyRound, Settings, Eye, EyeOff, Mail, RefreshCw, Calendar, Link2, Link2Off, Gauge, Webhook, Server, Database, ShieldCheck, Layers, Plus, Trash2, Play, RotateCcw, Clock, CheckCircle, XCircle, ExternalLink, Copy, Sparkles, Network, Package } from "lucide-react";
import { useTheme } from "@/components/ThemeProvider";
import { useAuth } from "@/context/AuthContext";

import { apiFetch } from "@/utils/apiFetch";
import { API_BASE, CRM_BASE } from "@/lib/api";
import { useRecentlyViewed } from "@/hooks/useRecentlyViewed";
import SettingsHome from "@/components/settings/SettingsHome";
import SectionHeader from "@/components/settings/SectionHeader";
import { SECTION_DEFS } from "@/components/settings/sectionDefs";
import SubAccountsTab from "@/components/settings/SubAccountsTab";
import ComplianceTab from "@/components/settings/ComplianceTab";
import DispositionsTab from "@/components/settings/DispositionsTab";
import AgentTemplatesTab from "@/components/settings/AgentTemplatesTab";
import IntegrationsTab from "@/components/settings/IntegrationsTab";
import CostTab from "@/components/settings/CostTab";
import FeatureFlagsTab from "@/components/settings/FeatureFlagsTab";
import ToolCallLogsTab from "@/components/settings/ToolCallLogsTab";
import MCPConnectionsTab from "@/components/settings/MCPConnectionsTab";
import CollectionsTab from "@/components/settings/CollectionsTab";
import SchemeClaimsTab from "@/components/settings/SchemeClaimsTab";
import BooksSyncTab from "@/components/settings/BooksSyncTab";
import PurchaseIndentsTab from "@/components/settings/PurchaseIndentsTab";

const themeOptions = [
    { value: "light", label: "Light", icon: Sun },
    { value: "dark", label: "Dark", icon: Moon },
    { value: "system", label: "System", icon: Monitor },
] as const;


const COMPANY_SETTING_KEYS = {
    systemInstruction: ["SYSTEM_INSTRUCTION", "system_instruction"],
    sttProvider: ["STT_PROVIDER", "stt_provider"],
    llmProvider: ["LLM_PROVIDER", "llm_provider"],
    evalJudgeProvider: ["EVAL_JUDGE_PROVIDER", "eval_judge_provider"],
    evalJudgeModel: ["EVAL_JUDGE_MODEL", "eval_judge_model"],
    ttsProvider: ["TTS_PROVIDER", "tts_provider"],
    telephonyEngine: ["TELEPHONY_ENGINE", "telephony_engine"],
    aiVerbosity: ["AI_VERBOSITY", "ai_verbosity"],
    bizHoursStart: ["BUSINESS_HOURS_START", "business_hours_start"],
    bizHoursEnd: ["BUSINESS_HOURS_END", "business_hours_end"],
    bizSundayBlocked: ["BUSINESS_SUNDAY_BLOCKED", "business_sunday_blocked"],
    bizHoursDisabled: ["DISABLE_BUSINESS_HOURS_GUARD", "disable_business_hours_guard"],
    silenceThreshold: ["SILENCE_THRESHOLD_S", "silence_threshold_s"],
    silenceCheckInterval: ["SILENCE_CHECK_INTERVAL_S", "silence_check_interval_s"],
    voicemailDetection: ["VOICEMAIL_DETECTION_ENABLED", "voicemail_detection_enabled"],
    agentName: ["AGENT_NAME", "agent_name"],
    callConnectMessage: ["CALL_CONNECT_MESSAGE", "call_connect_message"],
    agentGreeting: ["AGENT_GREETING", "agent_greeting"],
    agentPersonalizedGreeting: ["AGENT_PERSONALIZED_GREETING", "agent_personalized_greeting"],
    // ASR / Transcript tuning and storage (per-company)
    asrStoreRawJson: ["ASR_STORE_RAW_JSON", "asr_store_raw_json"],
    asrOverlapThreshold: ["ASR_OVERLAP_THRESHOLD", "asr_overlap_threshold"],
    ambientNoiseEnabled: ["AMBIENT_NOISE_ENABLED", "ambient_noise_enabled"],
    ambientNoisePreset: ["AMBIENT_NOISE_PRESET", "ambient_noise_preset"],
    ambientNoiseVolume: ["AMBIENT_NOISE_VOLUME", "ambient_noise_volume"],
} as const;

const INTEGRATION_KEY_ALIASES: Record<string, string> = {
    SMTP_SERVER: "SMTP_HOST" };

const INTEGRATION_KEY_MIRRORS: Record<string, string> = {
    TWILIO_PHONE_NUMBER: "PHONE_NUMBER_FROM",
    WHATSAPP_NUMBER: "WHATSAPP_NUMBER_FROM" };

function readSettingValue(
    settings: Record<string, string>,
    keys: readonly [string, string],
    fallback: string
) {
    return settings[keys[0]] ?? settings[keys[1]] ?? fallback;
}

function normalizeIntegrationValues(keysData: Record<string, string>) {
    return {
        ...keysData,
        PHONE_NUMBER_FROM: keysData.TWILIO_PHONE_NUMBER ?? keysData.PHONE_NUMBER_FROM ?? "",
        WHATSAPP_NUMBER_FROM: keysData.WHATSAPP_NUMBER ?? keysData.WHATSAPP_NUMBER_FROM ?? "",
        TWILIO_PHONE_NUMBER: keysData.TWILIO_PHONE_NUMBER ?? keysData.PHONE_NUMBER_FROM ?? "",
        WHATSAPP_NUMBER: keysData.WHATSAPP_NUMBER ?? keysData.WHATSAPP_NUMBER_FROM ?? "",
        SMTP_SERVER: keysData.SMTP_SERVER ?? keysData.SMTP_HOST ?? "",
        
        };
}

function isMaskedValue(value: string) {
    return value.startsWith("***") || value.includes("...");
}

function isSecretIntegrationKey(key: string) {
    return /(API_KEY|AUTH_TOKEN|PASSWORD|TOKEN|SECRET)/.test(key);
}

type RoleOption = {
    id: number;
    name: string;
    description?: string;
};

export default function SettingsPage() {
    const { theme, setTheme } = useTheme();
    const { user, sessionTimeout } = useAuth();
    const searchParams = useSearchParams();
    const router = useRouter();
    const [systemInstruction, setSystemInstruction] = useState("");
    const [sttProvider, setSttProvider] = useState("deepgram");
    const [llmProvider, setLlmProvider] = useState("mistral");
    const [evalJudgeProvider, setEvalJudgeProvider] = useState("");
    const [evalJudgeModel, setEvalJudgeModel] = useState("");
    const [ttsProvider, setTtsProvider] = useState("cartesia");
    const [telephonyEngine, setTelephonyEngine] = useState("twilio");
    const [aiVerbosity, setAiVerbosity] = useState("1");

    // Call-window (business hours) controls — per-company, persisted as
    // CompanySetting rows.  Dialer reads these to gate is_lead_callable.
    const [bizHoursStart, setBizHoursStart] = useState("9");
    const [bizHoursEnd, setBizHoursEnd] = useState("22");
    const [bizSundayBlocked, setBizSundayBlocked] = useState("1");
    const [bizHoursDisabled, setBizHoursDisabled] = useState("0");
    // Silence-watcher tunables — voice agent re-engages after this many
    // seconds of silence post-Rio-utterance.
    const [silenceThreshold, setSilenceThreshold] = useState("6");
    const [silenceCheckInterval, setSilenceCheckInterval] = useState("3");
    const [voicemailDetection, setVoicemailDetection] = useState("0");
    const [ambientNoiseEnabled, setAmbientNoiseEnabled] = useState("0");
    const [ambientNoisePreset, setAmbientNoisePreset] = useState("call-center");
    const [ambientNoiseVolume, setAmbientNoiseVolume] = useState("15");
    const [agentName, setAgentName] = useState("Rio");
    const [callConnectMessage, setCallConnectMessage] = useState("");
    const [agentGreeting, setAgentGreeting] = useState("");
    const [agentPersonalizedGreeting, setAgentPersonalizedGreeting] = useState("");

    // ASR / Transcription controls
    const [asrStoreRawJson, setAsrStoreRawJson] = useState(false);
    const [asrOverlapThreshold, setAsrOverlapThreshold] = useState("0.6");

    // Google Calendar
    const [calendarStatus, setCalendarStatus] = useState<{ connected: boolean; email?: string | null } | null>(null);
    const [calendarLoading, setCalendarLoading] = useState(false);

    // Usage limits — per-company overrides stored as CompanySetting keys
    // usage_limit_calls_made, usage_limit_emails_sent, usage_limit_whatsapp_sent.
    // Empty string means "use tier default".
    const [usageLimitCalls, setUsageLimitCalls] = useState("");
    const [usageLimitEmails, setUsageLimitEmails] = useState("");
    const [usageLimitWhatsapp, setUsageLimitWhatsapp] = useState("");

    // API Keys State
    const [apiKeys, setApiKeys] = useState<Record<string, string>>({});
    
    // UI State
    const [activeSection, setActiveSection] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [saveSuccess, setSaveSuccess] = useState(false);
    const [saveError, setSaveError] = useState<string | null>(null);
    const [visibleKeys, setVisibleKeys] = useState<Record<string, boolean>>({});
    const [roles, setRoles] = useState<RoleOption[]>([]);
    const [inviteEmail, setInviteEmail] = useState("");
    const [inviteRoleId, setInviteRoleId] = useState<number | null>(null);
    const [inviteExpiresHours, setInviteExpiresHours] = useState(72);
    const [inviteMessage, setInviteMessage] = useState<string | null>(null);
    const [isInviting, setIsInviting] = useState(false);
    const hasAdminAccess = user?.role === "company_admin" || user?.role === "company_owner";

    const [pinnedIds, setPinnedIds] = useState<string[]>(() => {
        if (typeof window === "undefined") return [];
        try { return JSON.parse(localStorage.getItem("rio_settings_pinned") ?? "[]"); } catch { return []; }
    });
    const { items: recentSections, track: trackSection, clear: clearRecent } = useRecentlyViewed("rio_settings_recent");

    // Competitor tab state
    const [competitorNames, setCompetitorNames] = useState("");
    const [savingCompetitors, setSavingCompetitors] = useState(false);
    const [competitorSaved, setCompetitorSaved] = useState(false);
    const [competitorSummary, setCompetitorSummary] = useState<Array<{ competitor: string; count: number; counter_script?: string }>>([]);
    const [counterScripts, setCounterScripts] = useState<Record<string, string>>({});
    const [savingScript, setSavingScript] = useState<string | null>(null);
    const [newCompetitorName, setNewCompetitorName] = useState("");

    // Webhooks tab
    type WebhookConfig = { id: number; name: string; url: string; events: string[]; is_active: boolean; timeout_seconds: number; agent_filter?: string | null; outcome_filter?: string | null };
    type WebhookDeliveryLog = { id: number; webhook_id: number; event_type: string; http_status?: number | null; error?: string | null; created_at: string };
    const [webhooks, setWebhooks] = useState<WebhookConfig[]>([]);
    const [webhookLogs, setWebhookLogs] = useState<WebhookDeliveryLog[]>([]);
    const [webhookModal, setWebhookModal] = useState<WebhookConfig | null | "new">(null);
    const [webhookForm, setWebhookForm] = useState({ name: "", url: "", events: [] as string[], timeout_seconds: 10, is_active: true });
    const [webhookSaving, setWebhookSaving] = useState(false);
    const [webhookError, setWebhookError] = useState<string | null>(null);
    const [availableEvents, setAvailableEvents] = useState<any[]>([]);
    const [testingWebhook, setTestingWebhook] = useState<number | null>(null);

    // SIP Trunks tab
    type SipTrunk = { id: number; name: string; host: string; port: number; transport: string; provider: string; username?: string | null; sip_uri?: string | null; codecs: string; dtmf_mode: string; status: string; is_default: boolean };
    const [sipTrunks, setSipTrunks] = useState<SipTrunk[]>([]);
    const [sipModal, setSipModal] = useState<SipTrunk | null | "new">(null);
    const [sipForm, setSipForm] = useState({ name: "", host: "", port: 5060, transport: "udp", provider: "generic_sip", username: "", password: "", sip_uri: "", codecs: "PCMU,PCMA", dtmf_mode: "rfc2833", is_default: false });
    const [sipSaving, setSipSaving] = useState(false);
    const [sipError, setSipError] = useState<string | null>(null);

    // Provider Credentials tab
    type ProviderCred = { id: number; provider: string; key_name: string; created_at?: string };
    const [providerCreds, setProviderCreds] = useState<ProviderCred[]>([]);
    const [credForm, setCredForm] = useState({ provider: "deepgram", key_name: "API_KEY", value: "" });
    const [credSaving, setCredSaving] = useState(false);
    const [credError, setCredError] = useState<string | null>(null);
    const [credSuccess, setCredSuccess] = useState(false);

    // MCP Connections tab
    type MCPServer = { id: number; name: string; provider: string; url: string; transport: string; auth_type: string; capabilities_json: string[]; enabled: boolean; priority: number; last_health_status: string | null; last_health_checked_at: string | null; created_at: string; updated_at: string };
    const [mcpServers, setMcpServers] = useState<MCPServer[]>([]);
    const [mcpModal, setMcpModal] = useState<MCPServer | "new" | null>(null);
    const [mcpForm, setMcpForm] = useState({ name: "", provider: "apollo", url: "", transport: "http", auth_type: "oauth2", capabilities_json: [] as string[], enabled: true, priority: 100 });
    const [mcpSaving, setMcpSaving] = useState(false);
    const [mcpError, setMcpError] = useState<string | null>(null);
    const [mcpDiscovering, setMcpDiscovering] = useState<number | null>(null);

    // Inventory Sources tab
    type InvSource = { id: number; name: string; source_type: string; priority: number; enabled: boolean; last_sync_at: string | null; created_at: string };
    const [invSources, setInvSources] = useState<InvSource[]>([]);
    const [invModal, setInvModal] = useState<InvSource | "new" | null>(null);
    const [invForm, setInvForm] = useState({ name: "", source_type: "csv", priority: 80, config_json: "{}", enabled: true });
    const [invSaving, setInvSaving] = useState(false);
    const [invError, setInvError] = useState<string | null>(null);

    // Company Prompts (in persona tab)
    type CompanyPromptVersion = { id: number; version: number; prompt_text: string; is_active: boolean; change_reason?: string | null; created_at?: string };
    const [companyPrompts, setCompanyPrompts] = useState<CompanyPromptVersion[]>([]);
    const [newPromptText, setNewPromptText] = useState("");
    const [newPromptReason, setNewPromptReason] = useState("");
    const [promptSaving, setPromptSaving] = useState(false);
    const [promptSaved, setPromptSaved] = useState(false);

    // Per-user AI/preference settings (accessible to all roles)
    const [myAiPrompt, setMyAiPrompt] = useState("");
    const [myAiVerbosity, setMyAiVerbosity] = useState("1");
    const [savingMyAi, setSavingMyAi] = useState(false);
    const [myAiSaved, setMyAiSaved] = useState(false);
    const [myWarmTransfer, setMyWarmTransfer] = useState<Record<string, string>>({
        WARM_TRANSFER_NUMBER: "",
        WARM_TRANSFER_NAME: "" });
    const [savingMyWarmTransfer, setSavingMyWarmTransfer] = useState(false);
    const [myWarmTransferSaved, setMyWarmTransferSaved] = useState(false);

    // Per-user email settings (accessible to all roles)
    const [myEmail, setMyEmail] = useState<Record<string, string>>({
        SMTP_HOST: "", SMTP_PORT: "", SMTP_SECURITY: "ssl", SMTP_USERNAME: "", SMTP_PASSWORD: "", SMTP_FROM_EMAIL: "",
        IMAP_SERVER: "", IMAP_PORT: "", IMAP_SECURITY: "ssl", IMAP_USERNAME: "", IMAP_PASSWORD: "" });
    const [savingMyEmail, setSavingMyEmail] = useState(false);
    const [myEmailSaved, setMyEmailSaved] = useState(false);
    const [syncingInbox, setSyncingInbox] = useState(false);
    const [syncResult, setSyncResult] = useState<string | null>(null);

    useEffect(() => {
        const fetchSettingsAndKeys = async () => {
            if (!user) {
                setLoading(false);
                return;
            }

            try {
                const [settingsRes, keysRes, myEmailRes, myAiRes, calRes] = await Promise.all([
                    apiFetch(`${CRM_BASE}/company-settings`, {
                    }),
                    apiFetch(`${CRM_BASE}/company-integrations`, {
                    }),
                    apiFetch(`${CRM_BASE}/me/email-settings`, {
                    }),
                    apiFetch(`${CRM_BASE}/me/settings`, {
                    }),
                    apiFetch(`${CRM_BASE}/calendar/status`, {}).catch(() => null),
                ]);
                if (calRes && calRes.ok) setCalendarStatus(await calRes.json());

                if (settingsRes.status === 401 || keysRes.status === 401) {
                    sessionTimeout();
                    return;
                }

                if (settingsRes.ok) {
                    const data = await settingsRes.json() as Record<string, string>;
                    setSystemInstruction(readSettingValue(data, COMPANY_SETTING_KEYS.systemInstruction, ""));
                    setSttProvider(readSettingValue(data, COMPANY_SETTING_KEYS.sttProvider, "deepgram"));
                    setLlmProvider(readSettingValue(data, COMPANY_SETTING_KEYS.llmProvider, "mistral"));
                    setEvalJudgeProvider(readSettingValue(data, COMPANY_SETTING_KEYS.evalJudgeProvider, ""));
                    setEvalJudgeModel(readSettingValue(data, COMPANY_SETTING_KEYS.evalJudgeModel, ""));
                    setTtsProvider(readSettingValue(data, COMPANY_SETTING_KEYS.ttsProvider, "cartesia"));
                    setTelephonyEngine(readSettingValue(data, COMPANY_SETTING_KEYS.telephonyEngine, "twilio"));
                    setAiVerbosity(readSettingValue(data, COMPANY_SETTING_KEYS.aiVerbosity, "2"));
                    setBizHoursStart(readSettingValue(data, COMPANY_SETTING_KEYS.bizHoursStart, "9"));
                    setBizHoursEnd(readSettingValue(data, COMPANY_SETTING_KEYS.bizHoursEnd, "22"));
                    setBizSundayBlocked(readSettingValue(data, COMPANY_SETTING_KEYS.bizSundayBlocked, "1"));
                    setBizHoursDisabled(readSettingValue(data, COMPANY_SETTING_KEYS.bizHoursDisabled, "0"));
                    setSilenceThreshold(readSettingValue(data, COMPANY_SETTING_KEYS.silenceThreshold, "6"));
                    setSilenceCheckInterval(readSettingValue(data, COMPANY_SETTING_KEYS.silenceCheckInterval, "3"));
                    setVoicemailDetection(readSettingValue(data, COMPANY_SETTING_KEYS.voicemailDetection, "0"));
                    setAmbientNoiseEnabled(readSettingValue(data, COMPANY_SETTING_KEYS.ambientNoiseEnabled, "0"));
                    setAmbientNoisePreset(readSettingValue(data, COMPANY_SETTING_KEYS.ambientNoisePreset, "call-center"));
                    setAmbientNoiseVolume(readSettingValue(data, COMPANY_SETTING_KEYS.ambientNoiseVolume, "15"));
                    setAgentName(readSettingValue(data, COMPANY_SETTING_KEYS.agentName, "Rio"));
                    setCallConnectMessage(readSettingValue(data, COMPANY_SETTING_KEYS.callConnectMessage, ""));
                    setAgentGreeting(readSettingValue(data, COMPANY_SETTING_KEYS.agentGreeting, ""));
                    setAgentPersonalizedGreeting(readSettingValue(data, COMPANY_SETTING_KEYS.agentPersonalizedGreeting, ""));
                    // ASR company-level settings
                    try {
                        const raw = readSettingValue(data, COMPANY_SETTING_KEYS.asrStoreRawJson, "0");
                        setAsrStoreRawJson(raw === "1" || raw === "true");
                    } catch (e) {
                        setAsrStoreRawJson(false);
                    }
                    setAsrOverlapThreshold(readSettingValue(data, COMPANY_SETTING_KEYS.asrOverlapThreshold, "0.6"));

                    setUsageLimitCalls(data["usage_limit_calls_made"] ?? "");
                    setUsageLimitEmails(data["usage_limit_emails_sent"] ?? "");
                    setUsageLimitWhatsapp(data["usage_limit_whatsapp_sent"] ?? "");
                    if (data.COMPETITOR_NAMES) setCompetitorNames(data.COMPETITOR_NAMES);
                }

                // Load competitor summary (mentions + counter-scripts)
                if (hasAdminAccess) {
                    try {
                        const summaryRes = await apiFetch(`${CRM_BASE}/competitors/summary`, {
                        });
                        if (summaryRes.ok) {
                            const summary = await summaryRes.json() as Array<{ competitor: string; count: number; counter_script?: string }>;
                            setCompetitorSummary(summary);
                            const scripts: Record<string, string> = {};
                            summary.forEach(s => { if (s.counter_script) scripts[s.competitor] = s.counter_script; });
                            setCounterScripts(scripts);
                        }
                    } catch {  }
                }

                if (myEmailRes.ok) {
                    const myEmailData = await myEmailRes.json() as Record<string, string>;
                    setMyEmail(prev => ({ ...prev, ...myEmailData }));
                }

                if (myAiRes.ok) {
                    const myAiData = await myAiRes.json() as Record<string, string>;
                    if (myAiData.SYSTEM_PROMPT) setMyAiPrompt(myAiData.SYSTEM_PROMPT);
                    if (myAiData.AI_VERBOSITY) setMyAiVerbosity(myAiData.AI_VERBOSITY);
                    setMyWarmTransfer({
                        WARM_TRANSFER_NUMBER: myAiData.WARM_TRANSFER_NUMBER || "",
                        WARM_TRANSFER_NAME: myAiData.WARM_TRANSFER_NAME || "" });
                }

                if (keysRes.ok) {
                    const keysData = normalizeIntegrationValues(await keysRes.json() as Record<string, string>);
                    const defaultKeys = {
                        TRUECALLER_KEY_ID: "",
                        TRUECALLER_API_KEY: "",
                        TRUECALLER_CLIENT_ACCOUNT_ID: "",
                        API_LAYER_API_KEY: "",
                        DEEPGRAM_API_KEY: "",
                        ELEVENLABS_API_KEY: "",
                        CARTESIA_API_KEY: "",
                        SARVAM_API_KEY: "",
                        SARVAM_STT_MODEL: "",
                        SARVAM_TTS_MODEL: "",
                        SARVAM_VOICE_ID: "",
                        CARTESIA_STT_MODEL: "",
                        CARTESIA_TTS_MODEL: "",
                        OPENAI_API_KEY: "",
                        MISTRAL_API_KEY: "",
                        ANTHROPIC_API_KEY: "",
                        GEMINI_API_KEY: "",
                        PERPLEXITY_API_KEY: "",
                        CEREBRAS_API_KEY: "",
                        OPENROUTER_API_KEY: "",
                        APOLLO_API_KEY: "",
                        TWILIO_ACCOUNT_SID: "",
                        TWILIO_AUTH_TOKEN: "",
                        TWILIO_PHONE_NUMBER: "",
                        PHONE_NUMBER_FROM: "",
                        WHATSAPP_NUMBER: "",
                        WHATSAPP_NUMBER_FROM: "",
                        EXOTEL_ACCOUNT_SID: "",
                        EXOTEL_API_KEY: "",
                        EXOTEL_API_TOKEN: "",
                        EXOPHONE: "",
                        EXOTEL_APP_ID: "",
                        ENABLEX_APP_ID: "",
                        ENABLEX_APP_KEY: "",
                        ENABLEX_FROM_NUMBER: "",
                        SMTP_SERVER: "",
                        SMTP_PORT: "",
                        SMTP_USERNAME: "",
                        SMTP_PASSWORD: "",
                        SMTP_FROM_EMAIL: "",
                        ELEVENLABS_VOICE_ID: "",
                        CARTESIA_VOICE_ID: "",
                        DEEPGRAM_VOICE: "",
                        MISTRAL_MODEL: "",
                        OPENAI_MODEL: "",
                        GEMINI_MODEL: "",
                        ANTHROPIC_MODEL: "",
                        PERPLEXITY_MODEL: "",
                        OPENROUTER_MODEL: "",
                        CEREBRAS_MODEL: "",
                        DEEPGRAM_STT_MODEL: "",
                        DEEPGRAM_TTS_MODEL: "",
                        ELEVENLABS_TTS_MODEL: "",
                        ELEVENLABS_STT_MODEL: "",
                        MIMO_VOICE_ID: "",
                        MIMO_TTS_MODEL: "",
                        MIMO_API_KEY: "",
                        MIMO_MODEL: "",
                        SMALLEST_API_KEY: "",
                        SMALLEST_STT_MODEL: "",
                        SMALLEST_TTS_MODEL: "",
                        SMALLEST_LLM_MODEL: "",
                        MISTRAL_TTS_MODEL: "",
                        MISTRAL_VOICE_ID: "",
                        GROQ_API_KEY: "",
                        GROQ_MODEL: "",
                        PLIVO_AUTH_ID: "",
                        PLIVO_AUTH_TOKEN: "",
                        PLIVO_PHONE_NUMBER: "",
                        VOBIZ_AUTH_ID: "",
                        VOBIZ_AUTH_TOKEN: "",
                        VOBIZ_PHONE_NUMBER: "",
                        WARM_TRANSFER_NUMBER: "",
                        WARM_TRANSFER_NAME: "",
                        RINGG_AI_API_KEY: "",
                        RINGG_AI_STT_MODEL: "",
                        GLADIA_API_KEY: "",
                        GLADIA_STT_MODEL: "",
                        ASSEMBLYAI_API_KEY: "",
                        ASSEMBLYAI_STT_MODEL: "",
                        INWORLD_API_KEY: "",
                        INWORLD_STT_MODEL: "",
                        INWORLD_TTS_MODEL: "",
                        INWORLD_VOICE_ID: "",
                        INWORLD_LLM_MODEL: "",
                        RIME_API_KEY: "",
                        RIME_TTS_MODEL: "",
                        AWS_ACCESS_KEY_ID: "",
                        AWS_SECRET_ACCESS_KEY: "",
                        AWS_DEFAULT_REGION: "",
                        POLLY_TTS_MODEL: "",
                        POLLY_VOICE_ID: "",
                        AZURE_TTS_MODEL: "",
                        AZURE_VOICE_ID: "",
                        AZURE_STT_MODEL: "",
                        AZURE_LLM_MODEL: "",
                        AZURE_SPEECH_ENDPOINT: "",
                        AZURE_LLM_ENDPOINT: "",
                        AZURE_LLM_API_KEY: "",
                        AZURE_LLM_API_VERSION: "",
                        AZURE_LLM_REGION: "",
                        AZURE_SPEECH_API_VERSION: "",
                        AZURE_SPEECH_API_KEY: "",
                        AZURE_SPEECH_REGION: "",
                        AIRLLM_MODEL: "",
                        AIRLLM_COMPRESSION: "",
                        AIRLLM_MAX_NEW_TOKENS: "",
                        KITTEN_TTS_MODEL: "",
                        KITTEN_TTS_VOICE: "",
                        VACHANA_API_KEY: "",
                        VACHANA_STT_MODEL: "",
                        VACHANA_TTS_MODEL: "",
                        VACHANA_VOICE_ID: "",
                    };
                    setApiKeys({ ...defaultKeys, ...keysData });
                }
            } catch (error) {
                console.error("Error fetching settings:", error);
            } finally {
                setLoading(false);
            }
        };

        fetchSettingsAndKeys();
    }, [user, sessionTimeout]);

    useEffect(() => {
        if (!user || !hasAdminAccess) return;
        const controller = new AbortController();

        const fetchRoles = async () => {
            try {
                const res = await apiFetch(`${API_BASE}/admin/roles`, {
                    signal: controller.signal });
                if (res.status === 401) { sessionTimeout(); return; }
                if (!res.ok) {
                    console.warn("Failed to load roles", res.status);
                    return;
                }
                const data: RoleOption[] = await res.json();
                setRoles(data);
                if (!inviteRoleId && data.length) {
                    setInviteRoleId(data[0].id);
                }
            } catch (err) {
                if ((err as DOMException).name === "AbortError") {
                    return;
                }
                console.error("Failed to load roles", err);
            }
        };

        fetchRoles();
        return () => controller.abort();
    }, [user, hasAdminAccess, inviteRoleId]);

    // Load section-specific data lazily
    useEffect(() => {
        if (!user || !hasAdminAccess) return;
        if (activeSection === "webhooks") {
            Promise.all([
                apiFetch(`${CRM_BASE}/webhooks`).then(r => r.ok ? r.json() : []).catch(() => []),
                apiFetch(`${CRM_BASE}/webhooks/delivery-logs`).then(r => r.ok ? r.json() : []).catch(() => []),
                apiFetch(`${CRM_BASE}/integrations/events`).then(r => r.ok ? r.json() : []).catch(() => []),
            ]).then(([wh, logs, evts]) => {
                setWebhooks(wh as WebhookConfig[]);
                setWebhookLogs(logs as WebhookDeliveryLog[]);
                setAvailableEvents(evts as any[]);
            });
        }
        if (activeSection === "sip_trunks") {
            apiFetch(`${CRM_BASE}/sip-trunks`).then(r => r.ok ? r.json() : []).then(d => setSipTrunks(d as SipTrunk[])).catch(() => {});
        }
        if (activeSection === "credentials") {
            apiFetch(`${CRM_BASE}/provider-credentials`).then(r => r.ok ? r.json() : []).then(d => setProviderCreds(d as ProviderCred[])).catch(() => {});
        }
        if (activeSection === "mcp_connections") {
            apiFetch(`${API_BASE}/mcp-connections/registry`).then(r => r.ok ? r.json() : []).then(d => setMcpServers(d as MCPServer[])).catch(() => {});
        }
        if (activeSection === "inventory_sources") {
            apiFetch(`${CRM_BASE}/inventory-sources`).then(r => r.ok ? r.json() : []).then(d => setInvSources(d as InvSource[])).catch(() => {});
        }
        if (activeSection === "voice_ai") {
            apiFetch(`${CRM_BASE}/company-prompts`).then(r => r.ok ? r.json() : []).then((d: CompanyPromptVersion[]) => {
                setCompanyPrompts(d);
                const active = d.find(p => p.is_active);
                if (active && !newPromptText) setNewPromptText(active.prompt_text);
            }).catch(() => {});
        }
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [activeSection, user, hasAdminAccess]);

    // Webhook CRUD helpers
    const openWebhookModal = (w: WebhookConfig | "new") => {
        setWebhookError(null);
        if (w === "new") { setWebhookForm({ name: "", url: "", events: [], timeout_seconds: 10, is_active: true }); }
        else { setWebhookForm({ name: w.name, url: w.url, events: w.events, timeout_seconds: w.timeout_seconds, is_active: w.is_active }); }
        setWebhookModal(w);
    };
    const saveWebhook = async () => {
        setWebhookError(null); setWebhookSaving(true);
        try {
            const isNew = webhookModal === "new";
            const url = isNew ? `${CRM_BASE}/webhooks` : `${CRM_BASE}/webhooks/${(webhookModal as WebhookConfig).id}`;
            const res = await apiFetch(url, { method: isNew ? "POST" : "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(webhookForm) });
            if (!res.ok) { const b = await res.json().catch(() => ({})); throw new Error(b.detail ?? `Server ${res.status}`); }
            const fresh = await apiFetch(`${CRM_BASE}/webhooks`).then(r => r.json());
            setWebhooks(fresh);
            setWebhookModal(null);
        } catch (e) { setWebhookError(e instanceof Error ? e.message : "Save failed"); }
        finally { setWebhookSaving(false); }
    };
    const deleteWebhook = async (id: number) => {
        if (!window.confirm("Delete this webhook?")) return;
        await apiFetch(`${CRM_BASE}/webhooks/${id}`, { method: "DELETE" });
        setWebhooks(prev => prev.filter(w => w.id !== id));
    };
    const testWebhook = async (id: number) => {
        setTestingWebhook(id);
        await apiFetch(`${CRM_BASE}/webhooks/${id}/test`, { method: "POST" }).catch(() => {});
        setTestingWebhook(null);
    };

    // SIP trunk helpers
    const openSipModal = (t: SipTrunk | "new") => {
        setSipError(null);
        if (t === "new") { setSipForm({ name: "", host: "", port: 5060, transport: "udp", provider: "generic_sip", username: "", password: "", sip_uri: "", codecs: "PCMU,PCMA", dtmf_mode: "rfc2833", is_default: false }); }
        else { setSipForm({ name: t.name, host: t.host, port: t.port, transport: t.transport, provider: t.provider, username: t.username ?? "", password: "", sip_uri: t.sip_uri ?? "", codecs: t.codecs, dtmf_mode: t.dtmf_mode, is_default: t.is_default }); }
        setSipModal(t);
    };
    const saveSipTrunk = async () => {
        setSipError(null); setSipSaving(true);
        try {
            const isNew = sipModal === "new";
            const url = isNew ? `${CRM_BASE}/sip-trunks` : `${CRM_BASE}/sip-trunks/${(sipModal as SipTrunk).id}`;
            const res = await apiFetch(url, { method: isNew ? "POST" : "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(sipForm) });
            if (!res.ok) { const b = await res.json().catch(() => ({})); throw new Error(b.detail ?? `Server ${res.status}`); }
            const fresh = await apiFetch(`${CRM_BASE}/sip-trunks`).then(r => r.json());
            setSipTrunks(fresh);
            setSipModal(null);
        } catch (e) { setSipError(e instanceof Error ? e.message : "Save failed"); }
        finally { setSipSaving(false); }
    };
    const deleteSipTrunk = async (id: number) => {
        if (!window.confirm("Delete this SIP trunk?")) return;
        await apiFetch(`${CRM_BASE}/sip-trunks/${id}`, { method: "DELETE" });
        setSipTrunks(prev => prev.filter(t => t.id !== id));
    };

    // Provider credential helpers
    const saveProviderCred = async () => {
        setCredError(null); setCredSaving(true); setCredSuccess(false);
        try {
            const res = await apiFetch(`${CRM_BASE}/provider-credentials`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(credForm) });
            if (!res.ok) { const b = await res.json().catch(() => ({})); throw new Error(b.detail ?? `Server ${res.status}`); }
            const fresh = await apiFetch(`${CRM_BASE}/provider-credentials`).then(r => r.json());
            setProviderCreds(fresh);
            setCredForm(prev => ({ ...prev, value: "" }));
            setCredSuccess(true);
            setTimeout(() => setCredSuccess(false), 2500);
        } catch (e) { setCredError(e instanceof Error ? e.message : "Save failed"); }
        finally { setCredSaving(false); }
    };
    const deleteProviderCred = async (id: number) => {
        if (!window.confirm("Delete this credential?")) return;
        await apiFetch(`${CRM_BASE}/provider-credentials/${id}`, { method: "DELETE" });
        setProviderCreds(prev => prev.filter(c => c.id !== id));
    };

    // Company prompt helpers
    const saveCompanyPrompt = async () => {
        setPromptSaving(true); setPromptSaved(false);
        try {
            const res = await apiFetch(`${CRM_BASE}/company-prompts`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt_text: newPromptText, change_reason: newPromptReason || null }) });
            if (!res.ok) throw new Error(`Server ${res.status}`);
            const fresh = await apiFetch(`${CRM_BASE}/company-prompts`).then(r => r.json());
            setCompanyPrompts(fresh);
            setNewPromptReason("");
            setPromptSaved(true);
            setTimeout(() => setPromptSaved(false), 2500);
        } catch { /* silent */ }
        finally { setPromptSaving(false); }
    };
    const activatePrompt = async (id: number) => {
        await apiFetch(`${CRM_BASE}/company-prompts/${id}/activate`, { method: "POST" });
        const fresh = await apiFetch(`${CRM_BASE}/company-prompts`).then(r => r.json());
        setCompanyPrompts(fresh);
    };

    const handleSave = async () => {
        console.log("💾 [Settings] Starting save operation...");
        setSaving(true);
        setSaveSuccess(false);
        setSaveError(null);

        try {
            const settingsPayload = {
                items: [
                    { key: "SYSTEM_INSTRUCTION", value: systemInstruction, is_secret: false },
                    { key: "STT_PROVIDER", value: sttProvider, is_secret: false },
                    { key: "LLM_PROVIDER", value: llmProvider, is_secret: false },
                    { key: "EVAL_JUDGE_PROVIDER", value: evalJudgeProvider, is_secret: false },
                    { key: "EVAL_JUDGE_MODEL", value: evalJudgeModel, is_secret: false },
                    { key: "TTS_PROVIDER", value: ttsProvider, is_secret: false },
                    { key: "TELEPHONY_ENGINE", value: telephonyEngine, is_secret: false },
                    { key: "AI_VERBOSITY", value: aiVerbosity, is_secret: false },
                    { key: "BUSINESS_HOURS_START", value: bizHoursStart, is_secret: false },
                    { key: "BUSINESS_HOURS_END", value: bizHoursEnd, is_secret: false },
                    { key: "BUSINESS_SUNDAY_BLOCKED", value: bizSundayBlocked, is_secret: false },
                    { key: "DISABLE_BUSINESS_HOURS_GUARD", value: bizHoursDisabled, is_secret: false },
                    { key: "SILENCE_THRESHOLD_S", value: silenceThreshold, is_secret: false },
                    { key: "SILENCE_CHECK_INTERVAL_S", value: silenceCheckInterval, is_secret: false },
                    { key: "VOICEMAIL_DETECTION_ENABLED", value: voicemailDetection, is_secret: false },
                    { key: "AMBIENT_NOISE_ENABLED", value: ambientNoiseEnabled, is_secret: false },
                    { key: "AMBIENT_NOISE_PRESET", value: ambientNoisePreset, is_secret: false },
                    { key: "AMBIENT_NOISE_VOLUME", value: ambientNoiseVolume, is_secret: false },
                    { key: "AGENT_NAME", value: agentName, is_secret: false },
                    { key: "CALL_CONNECT_MESSAGE", value: callConnectMessage, is_secret: false },
                    { key: "AGENT_GREETING", value: agentGreeting, is_secret: false },
                    { key: "AGENT_PERSONALIZED_GREETING", value: agentPersonalizedGreeting, is_secret: false },
                    { key: "ASR_STORE_RAW_JSON", value: asrStoreRawJson ? "1" : "0", is_secret: false },
                    { key: "ASR_OVERLAP_THRESHOLD", value: asrOverlapThreshold, is_secret: false },
                    { key: "usage_limit_calls_made", value: usageLimitCalls, is_secret: false },
                    { key: "usage_limit_emails_sent", value: usageLimitEmails, is_secret: false },
                    { key: "usage_limit_whatsapp_sent", value: usageLimitWhatsapp, is_secret: false },
                ] };

              const normalizedIntegrationValues = Object.entries(apiKeys).reduce<Record<string, string>>((acc, [rawKey, rawValue]) => {
                  const normalizedKey = INTEGRATION_KEY_ALIASES[rawKey] ?? rawKey;
                  acc[normalizedKey] = rawValue;
                  return acc;
              }, {});

              const integrationValues = { ...normalizedIntegrationValues };

              const integrationPayload = {
                  items: Object.entries(integrationValues)
                      .filter(([, value]) => typeof value === "string")
                      .map(([key, value]) => ({
                          key,
                          value: value.trim(),
                          is_secret: isSecretIntegrationKey(key) }))
                      .filter((item) => item.value && !isMaskedValue(item.value)) };

            const [res, keysRes] = await Promise.all([
                apiFetch(`${CRM_BASE}/company-settings`, {
                    method: "PATCH",
                    headers: {
                        "Content-Type": "application/json" },
                    body: JSON.stringify(settingsPayload) }),
                apiFetch(`${CRM_BASE}/company-integrations`, {
                    method: "PATCH",
                    headers: {
                        "Content-Type": "application/json" },
                    body: JSON.stringify(integrationPayload) }),
            ]);

            if (res.status === 401 || keysRes.status === 401) {
                sessionTimeout();
                return;
            }

            if (!res.ok || !keysRes.ok) {
                const settingsError = res.ok ? "" : await res.text();
                const integrationsError = keysRes.ok ? "" : await keysRes.text();
                throw new Error(
                    `Save failed (${res.status}/${keysRes.status}) ${settingsError || integrationsError}`.trim()
                );
            }

            setSaveSuccess(true);
            setTimeout(() => setSaveSuccess(false), 3000);
        } catch (error) {
            console.error("❌ [Settings] Error saving settings:", error);
            setSaveError(error instanceof Error ? error.message : "Failed to save settings.");
        } finally {
            setSaving(false);
        }
    };

    const handleSendInvite = async () => {
        if (!inviteEmail.trim()) {
            setInviteMessage("Please enter the invitee's email address.");
            return;
        }
        const roleId = inviteRoleId ?? roles[0]?.id;
        if (!roleId) {
            setInviteMessage("No roles available for invitations.");
            return;
        }

        setIsInviting(true);
        setInviteMessage(null);
        try {
            const res = await apiFetch(`${API_BASE}/auth/invites`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json" },
                body: JSON.stringify({
                    email: inviteEmail.trim(),
                    role_id: roleId,
                    expires_in_hours: inviteExpiresHours }) });

            if (res.status === 401) { sessionTimeout(); return; }
            const data = await res.json();
            if (res.ok) {
                setInviteMessage(`Invite sent to ${inviteEmail.trim()}.`);
                setInviteEmail("");
            } else {
                setInviteMessage(data.detail || "Failed to send invite.");
            }
        } catch (err) {
            setInviteMessage("Network error while sending invite.");
        } finally {
            setIsInviting(false);
        }
    };

    const handleKeyChange = (key: string, value: string) => {
        setApiKeys(prev => {
            const next = { ...prev, [key]: value };
            const mirrorKey = INTEGRATION_KEY_MIRRORS[key];
            if (mirrorKey) {
                next[mirrorKey] = value;
            }
            return next;
        });
    };

    const toggleKeyVisibility = (key: string) => {
        setVisibleKeys(prev => ({ ...prev, [key]: !prev[key] }));
    };

    const saveMyAiSettings = async () => {
        if (!user) return;
        setSavingMyAi(true);
        try {
            await apiFetch(`${CRM_BASE}/me/settings`, {
                method: "PUT",
                headers: {"Content-Type": "application/json" },
                body: JSON.stringify({ SYSTEM_PROMPT: myAiPrompt, AI_VERBOSITY: myAiVerbosity }) });
            setMyAiSaved(true);
            setTimeout(() => setMyAiSaved(false), 3000);
        } catch (e) {
            console.error("Failed to save AI settings", e);
        } finally {
            setSavingMyAi(false);
        }
    };

    const handleMyWarmTransferChange = (key: string, value: string) => {
        setMyWarmTransfer(prev => ({ ...prev, [key]: value }));
    };

    const saveMyWarmTransferSettings = async () => {
        if (!user) return;
        setSavingMyWarmTransfer(true);
        try {
            await apiFetch(`${CRM_BASE}/me/settings`, {
                method: "PUT",
                headers: {"Content-Type": "application/json" },
                body: JSON.stringify(myWarmTransfer) });
            setMyWarmTransferSaved(true);
            setTimeout(() => setMyWarmTransferSaved(false), 3000);
        } catch (e) {
            console.error("Failed to save warm transfer settings", e);
        } finally {
            setSavingMyWarmTransfer(false);
        }
    };

    const handleMyEmailChange = (key: string, value: string) => {
        setMyEmail(prev => ({ ...prev, [key]: value }));
    };

    const saveMyEmailSettings = async () => {
        if (!user) return;
        setSavingMyEmail(true);
        try {
            await apiFetch(`${CRM_BASE}/me/email-settings`, {
                method: "PUT",
                headers: {"Content-Type": "application/json" },
                body: JSON.stringify(myEmail) });
            setMyEmailSaved(true);
            setTimeout(() => setMyEmailSaved(false), 3000);
        } catch (e) {
            console.error("Failed to save email settings", e);
        } finally {
            setSavingMyEmail(false);
        }
    };

    const saveCompetitorNames = async (overrideValue?: string) => {
        if (!user) return;
        setSavingCompetitors(true);
        try {
            await apiFetch(`${CRM_BASE}/company-settings`, {
                method: "PATCH",
                headers: {"Content-Type": "application/json" },
                body: JSON.stringify({ items: [{ key: "COMPETITOR_NAMES", value: overrideValue ?? competitorNames, is_secret: false }] }) });
            setCompetitorSaved(true);
            setTimeout(() => setCompetitorSaved(false), 3000);
        } catch (e) {
            console.error("Failed to save competitor names", e);
        } finally {
            setSavingCompetitors(false);
        }
    };

    const saveCounterScript = async (competitor: string) => {
        if (!user) return;
        setSavingScript(competitor);
        try {
            await apiFetch(`${CRM_BASE}/competitors/counter-script`, {
                method: "POST",
                headers: {"Content-Type": "application/json" },
                body: JSON.stringify({ competitor_name: competitor, counter_script: counterScripts[competitor] || "" }) });
            // Refresh summary so textarea falls back to the saved DB value
            const res = await apiFetch(`${CRM_BASE}/competitors/summary`, { });
            if (res.ok) setCompetitorSummary(await res.json());
            // Clear the local edit — no longer "unsaved"
            setCounterScripts(prev => {
                const next = { ...prev };
                delete next[competitor];
                return next;
            });
        } catch (e) {
            console.error("Failed to save counter-script", e);
        } finally {
            setSavingScript(null);
        }
    };

    const addCompetitorToList = () => {
        const name = newCompetitorName.trim().toLowerCase();
        if (!name) return;
        const current = competitorNames.split(",").map(s => s.trim()).filter(Boolean);
        if (!current.includes(name)) {
            setCompetitorNames([...current, name].join(", "));
        }
        setNewCompetitorName("");
    };

    const removeCompetitorFromList = (name: string) => {
        const updated = competitorNames.split(",").map(s => s.trim()).filter(s => s && s !== name);
        setCompetitorNames(updated.join(", "));
    };

    const triggerInboxSync = async () => {
        if (!user) return;
        setSyncingInbox(true);
        setSyncResult(null);
        try {
            const res = await apiFetch(`${CRM_BASE}/email/sync`, {
                method: "POST"
            });
            const data = await res.json();
            setSyncResult(`Synced — ${data.emails_ingested ?? 0} new email(s) ingested`);
        } catch (e) {
            setSyncResult("Sync failed");
        } finally {
            setSyncingInbox(false);
        }
    };

    const handleCalendarConnect = async () => {
        setCalendarLoading(true);
        try {
            const res = await apiFetch(`${CRM_BASE}/calendar/auth-url`, {});
            if (res.ok) {
                const data = await res.json() as { auth_url: string };
                window.location.href = data.auth_url;
            }
        } catch (e) {
            console.error("Failed to get calendar auth URL", e);
        } finally {
            setCalendarLoading(false);
        }
    };

    const navigateToSection = useCallback((id: string) => {
        const sec = SECTION_DEFS.find(s => s.id === id);
        if (sec) trackSection({ id, label: sec.label });
        setActiveSection(id);
        router.replace(`/settings?section=${id}`, { scroll: false });
    }, [trackSection, router]);

    const handleBack = useCallback(() => {
        setActiveSection(null);
        router.replace("/settings", { scroll: false });
    }, [router]);

    const togglePin = (id: string) => {
        setPinnedIds(prev => {
            const next = prev.includes(id) ? prev.filter(p => p !== id) : [...prev, id];
            localStorage.setItem("rio_settings_pinned", JSON.stringify(next));
            return next;
        });
    };

    // Sync URL → state on mount
    useEffect(() => {
        const sec = searchParams.get("section");
        if (sec && SECTION_DEFS.find(s => s.id === sec)) {
            setActiveSection(sec);
        }
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // Keyboard: Esc → home, ⌘S → save current section
    useEffect(() => {
        const handler = (e: KeyboardEvent) => {
            if (e.key === "Escape" && activeSection !== null) {
                handleBack();
            }
            if ((e.metaKey || e.ctrlKey) && e.key === "s" && activeSection !== null) {
                e.preventDefault();
                const save = getSectionSave();
                if (!save.hideSave && save.onSave) save.onSave();
            }
        };
        window.addEventListener("keydown", handler);
        return () => window.removeEventListener("keydown", handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [activeSection, handleBack]);

    const saveMyEmailSection = async () => {
        await Promise.all([saveMyEmailSettings(), saveMyWarmTransferSettings()]);
    };

    const getSectionSave = () => {
        if (!activeSection) return { hideSave: true as const };
        if (activeSection === "profile") return { onSave: saveMyAiSettings, saving: savingMyAi, saveSuccess: myAiSaved, saveError: null as string | null, hideSave: false as const };
        if (activeSection === "my_email") return { onSave: saveMyEmailSection, saving: savingMyEmail || savingMyWarmTransfer, saveSuccess: myEmailSaved, saveError: null as string | null, hideSave: false as const };
        if (["voice_ai", "telephony_config", "api_keys", "usage"].includes(activeSection)) return { onSave: handleSave, saving, saveSuccess, saveError, hideSave: false as const };
        return { hideSave: true as const };
    };

    const handleCalendarDisconnect = async () => {
        setCalendarLoading(true);
        try {
            await apiFetch(`${CRM_BASE}/calendar/disconnect`, { method: "DELETE" });
            setCalendarStatus({ connected: false, email: null });
        } catch (e) {
            console.error("Failed to disconnect calendar", e);
        } finally {
            setCalendarLoading(false);
        }
    };

    return (
        <>
            <div className="space-y-6 pb-8 text-slate-800 dark:text-slate-100">
            {/* Header */}
            {activeSection === null && (
                <div>
                    <h1 className="text-4xl font-bold tracking-tight">
                        <span className="gradient-text">Settings</span>
                    </h1>
                    <p className="mt-2 text-slate-600 dark:text-slate-400 font-medium">
                        Configure your CRM preferences and AI behavior
                    </p>
                </div>
            )}

            {/* Command Center — Home */}
            {activeSection === null ? (
                <SettingsHome
                    sections={SECTION_DEFS}
                    recentItems={recentSections}
                    pinnedIds={pinnedIds}
                    hasAdminAccess={hasAdminAccess}
                    onNavigate={navigateToSection}
                    onTogglePin={togglePin}
                    onClearRecent={clearRecent}
                />
            ) : (
            <>
            {/* SectionHeader */}
            {(() => { const _sec = SECTION_DEFS.find(s => s.id === activeSection); if (!_sec) return null; return <SectionHeader section={_sec} onBack={handleBack} {...getSectionSave()} />; })()}

            <div className="space-y-6">
                {/* Sub Accounts Tab */}
                {activeSection === "sub_accounts" && hasAdminAccess && (
                    <SubAccountsTab sessionTimeout={sessionTimeout} />
                )}

                {/* Compliance Tab */}
                {activeSection === "compliance" && hasAdminAccess && (
                    <ComplianceTab sessionTimeout={sessionTimeout} />
                )}

                {/* Dispositions Tab */}
                {activeSection === "dispositions" && hasAdminAccess && (
                    <DispositionsTab sessionTimeout={sessionTimeout} />
                )}

                {/* Agent Templates Tab */}
                {activeSection === "agent_templates" && hasAdminAccess && (
                    <AgentTemplatesTab sessionTimeout={sessionTimeout} />
                )}

                {/* Integrations Tab */}
                {activeSection === "integrations" && hasAdminAccess && (
                    <IntegrationsTab sessionTimeout={sessionTimeout} />
                )}

                {/* Cost Tab */}
                {activeSection === "cost" && hasAdminAccess && (
                    <CostTab sessionTimeout={sessionTimeout} />
                )}

                {/* Feature Flags Tab */}
                {activeSection === "feature_flags" && hasAdminAccess && (
                    <FeatureFlagsTab sessionTimeout={sessionTimeout} />
                )}

                {/* Tool Call Logs Tab */}
                {activeSection === "tool_logs" && hasAdminAccess && (
                    <ToolCallLogsTab sessionTimeout={sessionTimeout} />
                )}

                {/* Profile Section */}
                {activeSection === "profile" && (
                    <div className="space-y-6">
                        {/* Theme Settings */}
                <div className="rounded-2xl glass p-6 border border-white/40 dark:border-white/10">
                    <div className="flex items-center space-x-3 mb-6">
                        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-yellow-500 to-orange-500">
                            <Sun className="h-5 w-5 text-white" />
                        </div>
                        <div>
                            <h3 className="text-xl font-bold text-slate-900 dark:text-slate-100">Appearance</h3>
                            <p className="text-sm text-slate-500 dark:text-slate-400">Choose your interface theme</p>
                        </div>
                    </div>

                    <div className="grid grid-cols-3 gap-4">
                        {themeOptions.map((option) => {
                            const Icon = option.icon;
                            const isActive = theme === option.value;

                            return (
                                <button
                                    key={option.value}
                                    onClick={() => setTheme(option.value)}
                                    className={`
                                        relative overflow-hidden rounded-xl p-4 border-2 transition-all duration-300
                                        ${isActive
                                            ? 'border-violet-600 bg-gradient-to-br from-violet-500/10 to-blue-500/10 shadow-lg'
                                            : 'border-slate-200 dark:border-slate-700 bg-white/60 dark:bg-slate-800/60 hover:border-violet-400 dark:hover:border-violet-500'
                                        }
                                    `}
                                >
                                    <div className="flex flex-col items-center space-y-2">
                                        <div className={`
                                            flex h-12 w-12 items-center justify-center rounded-xl transition-all
                                            ${isActive
                                                ? 'bg-gradient-to-br from-violet-600 to-blue-600 shadow-lg shadow-violet-500/50'
                                                : 'bg-slate-100 dark:bg-slate-700'
                                            }
                                        `}>
                                            <Icon className={`h-6 w-6 ${isActive ? 'text-white' : 'text-slate-600 dark:text-slate-300'}`} />
                                        </div>
                                        <span className={`text-sm font-semibold ${isActive ? 'text-violet-700 dark:text-violet-400' : 'text-slate-700 dark:text-slate-300'}`}>
                                            {option.label}
                                        </span>
                                    </div>
                                    {isActive && (
                                        <div className="absolute top-2 right-2 h-2 w-2 rounded-full bg-green-500 animate-pulse" />
                                    )}
                                </button>
                            );
                        })}
                    </div>
                </div>

                {/* My Rio — visible to all roles */}
                <div className="rounded-2xl glass p-6 border border-white/40 dark:border-white/10">
                    <div className="flex items-center justify-between mb-6">
                        <div className="flex items-center space-x-3">
                            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-violet-500 to-purple-600">
                                <Brain className="h-5 w-5 text-white" />
                            </div>
                            <div>
                                <h3 className="text-xl font-bold text-slate-900 dark:text-slate-100">My Rio Persona</h3>
                                <p className="text-sm text-slate-500 dark:text-slate-400">
                                    {hasAdminAccess ? "Your personal override — takes priority over company-wide prompt" : "Customize Rio's voice for your calls"}
                                </p>
                            </div>
                        </div>
                    </div>

                    <div className="space-y-4">
                        <div>
                            <label className="text-xs font-bold uppercase text-slate-500 mb-1 block">
                                Response Brevity (1 = very brief · 5 = detailed)
                            </label>
                            <div className="flex items-center space-x-4">
                                <input
                                    type="range" min="1" max="5" step="1"
                                    value={myAiVerbosity}
                                    onChange={(e) => setMyAiVerbosity(e.target.value)}
                                    className="flex-1 accent-violet-600"
                                />
                                <span className="w-6 text-center font-bold text-violet-600">{myAiVerbosity}</span>
                            </div>
                        </div>
                        <div>
                            <label className="text-xs font-bold uppercase text-slate-500 mb-1 block">Personal Prompt / Persona Script</label>
                            <textarea
                                rows={6}
                                value={myAiPrompt}
                                onChange={(e) => setMyAiPrompt(e.target.value)}
                                placeholder="E.g. You are Rio, a friendly sales representative for Yexis Electronics. Always greet the lead by name and focus on their specific needs..."
                                className="w-full rounded-xl border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 p-3 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500 resize-none"
                            />
                            <p className="mt-1 text-xs text-slate-400">Leave blank to use the company-wide Rio prompt.</p>
                        </div>
                    </div>
                </div>

                {/* Invite Teammate — profile section, admin only */}
                {hasAdminAccess && (
                    <div className="rounded-2xl glass p-6 border border-white/40 dark:border-white/10 space-y-4 animate-in fade-in duration-300">
                        <div className="flex items-center justify-between">
                            <div>
                                <h2 className="text-lg font-bold text-slate-900 dark:text-white">Invite a teammate</h2>
                                <p className="text-sm text-slate-500 dark:text-slate-400">Send an invitation link that expires in a few days.</p>
                            </div>
                            <span className="text-xs uppercase tracking-[0.2em] text-slate-400 dark:text-slate-500">Owner Only</span>
                        </div>
                        <div className="grid gap-3 md:grid-cols-[2fr_1fr_1fr_1fr] items-end">
                            <div>
                                <label className="text-xs font-semibold uppercase text-slate-500 dark:text-slate-400">Email</label>
                                <input type="email" value={inviteEmail} onChange={(e) => setInviteEmail(e.target.value)} placeholder="jane@company.com" className="w-full rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/40 px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500" />
                            </div>
                            <div>
                                <label className="text-xs font-semibold uppercase text-slate-500 dark:text-slate-400">Role</label>
                                <select value={inviteRoleId ?? ""} onChange={(e) => setInviteRoleId(Number(e.target.value))} className="w-full rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/40 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500">
                                    {roles.length === 0 && <option value="">Loading roles...</option>}
                                    {roles.map((role) => <option key={role.id} value={role.id}>{role.name.replace(/_/g, " ")}</option>)}
                                </select>
                            </div>
                            <div>
                                <label className="text-xs font-semibold uppercase text-slate-500 dark:text-slate-400">Expires (hours)</label>
                                <input type="number" min={1} max={168} value={inviteExpiresHours} onChange={(e) => setInviteExpiresHours(Number(e.target.value))} className="w-full rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/40 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500" />
                            </div>
                            <button type="button" onClick={handleSendInvite} disabled={isInviting} className="w-full rounded-xl bg-gradient-to-r from-emerald-500 to-teal-500 text-white font-semibold py-2 text-sm uppercase tracking-wide shadow-lg shadow-emerald-500/30 hover:opacity-90 transition-all disabled:opacity-50 disabled:cursor-not-allowed">
                                {isInviting ? "Sending..." : "Send Invite"}
                            </button>
                        </div>
                        {inviteMessage && <p className={`text-xs ${inviteMessage.includes("sent") ? "text-emerald-500" : "text-red-500"}`}>{inviteMessage}</p>}
                    </div>
                )}
                    </div>
                )}

                {/* Telephony Config Section */}
                {activeSection === "telephony_config" && hasAdminAccess && (
                    <div className="space-y-6">
                {/* Telephony Configuration */}
                {hasAdminAccess && (
                    <div className="rounded-2xl glass p-6 border border-white/40 dark:border-white/10">
                        <div className="flex items-center space-x-3 mb-6">
                            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-blue-500 to-indigo-600">
                                <Zap className="h-5 w-5 text-white" />
                            </div>
                            <div>
                                <h3 className="text-xl font-bold text-slate-900 dark:text-slate-100">Telephony Engine</h3>
                                <p className="text-sm text-slate-500 dark:text-slate-400">Choose your call routing provider</p>
                            </div>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                            <button
                                onClick={() => setTelephonyEngine("twilio")}
                                className={`
                                    flex items-center space-x-3 p-4 rounded-xl border-2 transition-all
                                    ${telephonyEngine === "twilio"
                                        ? 'border-red-500 bg-red-500/5 dark:bg-red-500/10'
                                        : 'border-slate-200 dark:border-slate-800 bg-white/40 dark:bg-slate-900/40'}
                                `}
                            >
                                <div className={`h-10 w-10 rounded-lg flex items-center justify-center ${telephonyEngine === "twilio" ? 'bg-red-500 text-white' : 'bg-slate-100 dark:bg-slate-800 text-slate-500'}`}>
                                    <Bell className="h-5 w-5" />
                                </div>
                                <div className="text-left">
                                    <p className="font-bold text-sm">Twilio</p>
                                    <p className="text-xs text-slate-500">Global Coverage</p>
                                </div>
                            </button>
                            <button
                                onClick={() => setTelephonyEngine("enablex")}
                                className={`
                                    flex items-center space-x-3 p-4 rounded-xl border-2 transition-all
                                    ${telephonyEngine === "enablex"
                                        ? 'border-indigo-600 bg-indigo-600/5 dark:bg-indigo-600/10'
                                        : 'border-slate-200 dark:border-slate-800 bg-white/40 dark:bg-slate-900/40'}
                                `}
                            >
                                <div className={`h-10 w-10 rounded-lg flex items-center justify-center ${telephonyEngine === "enablex" ? 'bg-indigo-600 text-white' : 'bg-slate-100 dark:bg-slate-800 text-slate-500'}`}>
                                    <Zap className="h-5 w-5" />
                                </div>
                                <div className="text-left">
                                    <p className="font-bold text-sm">EnableX</p>
                                    <p className="text-xs text-slate-500">India Optimized</p>
                                </div>
                            </button>
                            <button
                                onClick={() => setTelephonyEngine("exotel")}
                                className={`
                                    flex items-center space-x-3 p-4 rounded-xl border-2 transition-all
                                    ${telephonyEngine === "exotel"
                                        ? 'border-orange-500 bg-orange-500/5 dark:bg-orange-500/10'
                                        : 'border-slate-200 dark:border-slate-800 bg-white/40 dark:bg-slate-900/40'}
                                `}
                            >
                                <div className={`h-10 w-10 rounded-lg flex items-center justify-center ${telephonyEngine === "exotel" ? 'bg-orange-500 text-white' : 'bg-slate-100 dark:bg-slate-800 text-slate-500'}`}>
                                    <PhoneForwarded className="h-5 w-5" />
                                </div>
                                <div className="text-left">
                                    <p className="font-bold text-sm">Exotel</p>
                                    <p className="text-xs text-slate-500">India Optimized PCM</p>
                                </div>
                            </button>
                            <button
                                onClick={() => setTelephonyEngine("plivo")}
                                className={`
                                    flex items-center space-x-3 p-4 rounded-xl border-2 transition-all
                                    ${telephonyEngine === "plivo"
                                        ? 'border-green-600 bg-green-600/5 dark:bg-green-600/10'
                                        : 'border-slate-200 dark:border-slate-800 bg-white/40 dark:bg-slate-900/40'}
                                `}
                            >
                                <div className={`h-10 w-10 rounded-lg flex items-center justify-center ${telephonyEngine === "plivo" ? 'bg-green-600 text-white' : 'bg-slate-100 dark:bg-slate-800 text-slate-500'}`}>
                                    <PhoneForwarded className="h-5 w-5" />
                                </div>
                                <div className="text-left">
                                    <p className="font-bold text-sm">Plivo</p>
                                    <p className="text-xs text-slate-500">Global VoIP</p>
                                </div>
                            </button>
                            <button
                                onClick={() => setTelephonyEngine("vobiz")}
                                className={`
                                    flex items-center space-x-3 p-4 rounded-xl border-2 transition-all
                                    ${telephonyEngine === "vobiz"
                                        ? 'border-cyan-600 bg-cyan-600/5 dark:bg-cyan-600/10'
                                        : 'border-slate-200 dark:border-slate-800 bg-white/40 dark:bg-slate-900/40'}
                                `}
                            >
                                <div className={`h-10 w-10 rounded-lg flex items-center justify-center ${telephonyEngine === "vobiz" ? 'bg-cyan-600 text-white' : 'bg-slate-100 dark:bg-slate-800 text-slate-500'}`}>
                                    <PhoneForwarded className="h-5 w-5" />
                                </div>
                                <div className="text-left">
                                    <p className="font-bold text-sm">Vobiz</p>
                                    <p className="text-xs text-slate-500">India Optimized</p>
                                </div>
                            </button>
                        </div>
                    </div>
                )}

                {/* Business hours — controls is_lead_callable guard */}
                {hasAdminAccess && (
                    <div className="mt-6 rounded-2xl border border-slate-200 dark:border-slate-800 bg-white/40 dark:bg-slate-900/40 p-6">
                        <div className="mb-4">
                            <h3 className="text-base font-bold text-slate-900 dark:text-white">Call Window (Business Hours)</h3>
                            <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                                Dialer refuses to place calls outside this window in the lead&apos;s local timezone.
                                Applies to manual &quot;Call now&quot; + campaign dialer + ISM outreach.
                            </p>
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div>
                                <label className="text-xs font-semibold text-slate-600 dark:text-slate-300 block mb-1.5">Start hour (0-23)</label>
                                <input
                                    type="number"
                                    min={0}
                                    max={23}
                                    value={bizHoursStart}
                                    onChange={(e) => setBizHoursStart(e.target.value)}
                                    className="w-full rounded-lg border border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900 px-3 py-2 text-sm outline-none focus:border-violet-400"
                                />
                            </div>
                            <div>
                                <label className="text-xs font-semibold text-slate-600 dark:text-slate-300 block mb-1.5">End hour (0-23, exclusive)</label>
                                <input
                                    type="number"
                                    min={0}
                                    max={23}
                                    value={bizHoursEnd}
                                    onChange={(e) => setBizHoursEnd(e.target.value)}
                                    className="w-full rounded-lg border border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900 px-3 py-2 text-sm outline-none focus:border-violet-400"
                                />
                            </div>
                            <label className="flex items-center gap-2 text-sm text-slate-700 dark:text-slate-300 cursor-pointer">
                                <input
                                    type="checkbox"
                                    checked={bizSundayBlocked === "1"}
                                    onChange={(e) => setBizSundayBlocked(e.target.checked ? "1" : "0")}
                                    className="h-4 w-4 rounded border-slate-300"
                                />
                                Block Sundays
                            </label>
                            <label className="flex items-center gap-2 text-sm text-slate-700 dark:text-slate-300 cursor-pointer">
                                <input
                                    type="checkbox"
                                    checked={bizHoursDisabled === "1"}
                                    onChange={(e) => setBizHoursDisabled(e.target.checked ? "1" : "0")}
                                    className="h-4 w-4 rounded border-slate-300"
                                />
                                Disable the guard entirely (dev use only)
                            </label>
                        </div>
                    </div>
                )}

                {/* Voice agent — silence re-engage */}
                {hasAdminAccess && (
                    <div className="mt-6 rounded-2xl border border-slate-200 dark:border-slate-800 bg-white/40 dark:bg-slate-900/40 p-6">
                        <div className="mb-4">
                            <h3 className="text-base font-bold text-slate-900 dark:text-white">Voice Silence Re-engage</h3>
                            <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                                After Rio finishes speaking, if the customer is silent for this many seconds,
                                Rio re-engages with a context-aware nudge (&ldquo;Take your time…&rdquo; / &ldquo;Still there?&rdquo;).
                                Lower = more proactive but talks over thinking pauses. Higher = more patient.
                            </p>
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div>
                                <label className="text-xs font-semibold text-slate-600 dark:text-slate-300 block mb-1.5">
                                    Silence threshold (seconds)
                                </label>
                                <input
                                    type="number"
                                    min={2}
                                    max={60}
                                    step={0.5}
                                    value={silenceThreshold}
                                    onChange={(e) => setSilenceThreshold(e.target.value)}
                                    className="w-full rounded-lg border border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900 px-3 py-2 text-sm outline-none focus:border-violet-400"
                                />
                                <p className="text-[10px] text-slate-400 mt-1">Default 6s. Range 2-60s.</p>
                            </div>
                            <div>
                                <label className="text-xs font-semibold text-slate-600 dark:text-slate-300 block mb-1.5">
                                    Check interval (seconds)
                                </label>
                                <input
                                    type="number"
                                    min={1}
                                    max={30}
                                    step={0.5}
                                    value={silenceCheckInterval}
                                    onChange={(e) => setSilenceCheckInterval(e.target.value)}
                                    className="w-full rounded-lg border border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900 px-3 py-2 text-sm outline-none focus:border-violet-400"
                                />
                                <p className="text-[10px] text-slate-400 mt-1">Default 3s. How often the watcher polls.</p>
                            </div>
                        </div>
                        <div className="mt-4 pt-4 border-t border-slate-100 dark:border-slate-800">
                            <label className="flex items-center gap-3 cursor-pointer">
                                <input
                                    type="checkbox"
                                    checked={voicemailDetection === "1"}
                                    onChange={(e) => setVoicemailDetection(e.target.checked ? "1" : "0")}
                                    className="h-4 w-4 rounded border-slate-300"
                                />
                                <div>
                                    <span className="text-sm font-semibold text-slate-700 dark:text-slate-200">Voicemail detection</span>
                                    <p className="text-[10px] text-slate-400 mt-0.5">Auto-hang up when answering machine detected. Saves call minutes.</p>
                                </div>
                            </label>
                        </div>

                        {/* ── Ambient Noise ── */}
                        <div className="mt-4 pt-4 border-t border-slate-100 dark:border-slate-800">
                            <div className="flex items-center justify-between mb-3">
                                <div>
                                    <span className="text-sm font-semibold text-slate-700 dark:text-slate-200">Ambient background noise</span>
                                    <p className="text-[10px] text-slate-400 mt-0.5">Mix background audio into all calls (Plivo/Vobiz only). Per-agent setting in Voice Agents overrides this.</p>
                                </div>
                                <label className="flex items-center gap-2 cursor-pointer">
                                    <input
                                        type="checkbox"
                                        checked={ambientNoiseEnabled === "1"}
                                        onChange={(e) => setAmbientNoiseEnabled(e.target.checked ? "1" : "0")}
                                        className="h-4 w-4 rounded border-slate-300"
                                    />
                                </label>
                            </div>
                            {ambientNoiseEnabled === "1" && (
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-3">
                                    <div>
                                        <label className="text-xs font-semibold text-slate-600 dark:text-slate-300 block mb-1.5">Preset</label>
                                        <select
                                            value={ambientNoisePreset}
                                            onChange={(e) => setAmbientNoisePreset(e.target.value)}
                                            className="w-full rounded-lg border border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900 px-3 py-2 text-sm outline-none focus:border-violet-400 cursor-pointer"
                                        >
                                            <option value="call-center">Call Center</option>
                                            <option value="office-ambience">Office Ambience</option>
                                            <option value="coffee-shop">Coffee Shop</option>
                                        </select>
                                    </div>
                                    <div>
                                        <label className="text-xs font-semibold text-slate-600 dark:text-slate-300 block mb-1.5">Volume ({ambientNoiseVolume}%)</label>
                                        <input
                                            type="range"
                                            min={1}
                                            max={50}
                                            value={ambientNoiseVolume}
                                            onChange={(e) => setAmbientNoiseVolume(e.target.value)}
                                            className="w-full accent-violet-600 cursor-pointer"
                                        />
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>
                )}

                {/* Agent Persona & Greetings */}
                {hasAdminAccess && (
                    <div className="mt-6 rounded-2xl border border-slate-200 dark:border-slate-800 bg-white/40 dark:bg-slate-900/40 p-6">
                        <div className="mb-4">
                            <h3 className="text-base font-bold text-slate-900 dark:text-white">Agent Persona &amp; Greetings</h3>
                            <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                                Customize what the voice agent says at the start of every call.
                                Use <code className="bg-slate-100 dark:bg-slate-800 px-1 rounded">&#123;agent_name&#125;</code>,{" "}
                                <code className="bg-slate-100 dark:bg-slate-800 px-1 rounded">&#123;company_name&#125;</code>,{" "}
                                <code className="bg-slate-100 dark:bg-slate-800 px-1 rounded">&#123;lead_name&#125;</code> as placeholders.
                                Leave blank to use defaults.
                            </p>
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div>
                                <label className="text-xs font-semibold text-slate-600 dark:text-slate-300 block mb-1.5">Agent name</label>
                                <input
                                    type="text"
                                    value={agentName}
                                    onChange={(e) => setAgentName(e.target.value)}
                                    placeholder="Rio"
                                    className="w-full rounded-lg border border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900 px-3 py-2 text-sm outline-none focus:border-violet-400"
                                />
                                <p className="text-[10px] text-slate-400 mt-1">Name the agent introduces itself as.</p>
                            </div>
                            <div>
                                <label className="text-xs font-semibold text-slate-600 dark:text-slate-300 block mb-1.5">Call connect message</label>
                                <input
                                    type="text"
                                    value={callConnectMessage}
                                    onChange={(e) => setCallConnectMessage(e.target.value)}
                                    placeholder="Connected to {company_name}. Please start speaking."
                                    className="w-full rounded-lg border border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900 px-3 py-2 text-sm outline-none focus:border-violet-400"
                                />
                                <p className="text-[10px] text-slate-400 mt-1">Played by telephony before AI stream connects.</p>
                            </div>
                            <div>
                                <label className="text-xs font-semibold text-slate-600 dark:text-slate-300 block mb-1.5">Opening greeting (no lead name)</label>
                                <input
                                    type="text"
                                    value={agentGreeting}
                                    onChange={(e) => setAgentGreeting(e.target.value)}
                                    placeholder="Hello, I'm {agent_name} from {company_name}. Can you hear me okay?"
                                    className="w-full rounded-lg border border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900 px-3 py-2 text-sm outline-none focus:border-violet-400"
                                />
                                <p className="text-[10px] text-slate-400 mt-1">Used when lead name is unknown.</p>
                            </div>
                            <div>
                                <label className="text-xs font-semibold text-slate-600 dark:text-slate-300 block mb-1.5">Personalized greeting (with lead name)</label>
                                <input
                                    type="text"
                                    value={agentPersonalizedGreeting}
                                    onChange={(e) => setAgentPersonalizedGreeting(e.target.value)}
                                    placeholder="Hello {lead_name}, this is {agent_name} from {company_name}. Can you hear me okay?"
                                    className="w-full rounded-lg border border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900 px-3 py-2 text-sm outline-none focus:border-violet-400"
                                />
                                <p className="text-[10px] text-slate-400 mt-1">Used when the lead name is known.</p>
                            </div>
                        </div>
                    </div>
                )}

                {hasAdminAccess && (
                    <div className="mt-6 rounded-2xl border border-slate-200 dark:border-slate-800 bg-white/40 dark:bg-slate-900/40 p-6">
                        <div className="flex items-center justify-between">
                            <div className="flex items-center space-x-3">
                                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-500 to-teal-500">
                                    <Gauge className="h-5 w-5 text-white" />
                                </div>
                                <div>
                                    <h3 className="text-base font-bold text-slate-900 dark:text-white">ASR / Transcription</h3>
                                    <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">Control company-level ASR storage and mapping heuristics.</p>
                                </div>
                            </div>
                            <div className="text-sm text-slate-500">
                                <span className="text-xs font-semibold">Per-company</span>
                            </div>
                        </div>

                        <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
                            <label className="flex items-center gap-3 cursor-pointer">
                                <input
                                    type="checkbox"
                                    checked={!!asrStoreRawJson}
                                    onChange={(e) => setAsrStoreRawJson(Boolean(e.target.checked))}
                                    className="h-4 w-4 rounded border-slate-300"
                                />
                                <div>
                                    <span className="text-sm font-semibold text-slate-700 dark:text-slate-200">Store raw provider JSON (ASR_STORE_RAW_JSON)</span>
                                    <p className="text-[10px] text-slate-400 mt-0.5">When enabled, backend will persist full provider JSON for debugging. Recommended: off for privacy.</p>
                                </div>
                            </label>

                            <div>
                                <label className="text-xs font-semibold text-slate-600 dark:text-slate-300 block mb-1.5">ASR overlap threshold (0.0 - 1.0)</label>
                                <input
                                    type="number"
                                    min={0}
                                    max={1}
                                    step={0.01}
                                    value={Number(asrOverlapThreshold)}
                                    onChange={(e) => setAsrOverlapThreshold(String(e.target.value))}
                                    className="w-full rounded-lg border border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900 px-3 py-2 text-sm outline-none focus:border-violet-400"
                                />
                                <p className="text-[10px] text-slate-400 mt-1">Adjust mapping sensitivity for segment→line matching. Default 0.6.</p>
                            </div>
                        </div>
                    </div>
                )}
                    

                {/* Google Calendar Integration */}
                {hasAdminAccess && (
                    <div className="mt-6 rounded-2xl border border-slate-200 dark:border-slate-800 bg-white/40 dark:bg-slate-900/40 p-6">
                        <div className="flex items-center justify-between">
                            <div className="flex items-center space-x-3">
                                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-blue-500 to-cyan-500">
                                    <Calendar className="h-5 w-5 text-white" />
                                </div>
                                <div>
                                    <h3 className="text-base font-bold text-slate-900 dark:text-white">Google Calendar</h3>
                                    <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                                        Let the AI agent book meetings directly into your calendar during calls.
                                    </p>
                                </div>
                            </div>
                            <div className="flex items-center space-x-3">
                                {calendarStatus?.connected ? (
                                    <>
                                        <div className="flex items-center space-x-2 text-emerald-600 dark:text-emerald-400 text-sm font-semibold">
                                            <div className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
                                            <span>{calendarStatus.email ?? "Connected"}</span>
                                        </div>
                                        <button
                                            onClick={handleCalendarDisconnect}
                                            disabled={calendarLoading}
                                            className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg border border-red-300 dark:border-red-700 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 text-xs font-bold transition-all disabled:opacity-50"
                                        >
                                            {calendarLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Link2Off className="h-3.5 w-3.5" />}
                                            <span>Disconnect</span>
                                        </button>
                                    </>
                                ) : (
                                    <button
                                        onClick={handleCalendarConnect}
                                        disabled={calendarLoading}
                                        className="flex items-center space-x-1.5 px-4 py-2 rounded-xl bg-gradient-to-r from-blue-500 to-cyan-500 text-white text-sm font-bold shadow-md shadow-blue-500/30 hover:opacity-90 transition-all disabled:opacity-50"
                                    >
                                        {calendarLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Link2 className="h-4 w-4" />}
                                        <span>Connect Google Calendar</span>
                                    </button>
                                )}
                            </div>
                        </div>
                    </div>
                )}
                    </div>
                )}

                {/* AI Configuration Tab */}
                {activeSection === "voice_ai" && hasAdminAccess && (
                    <div className="rounded-2xl glass p-6 border border-white/40 dark:border-white/10">
                        <div className="flex items-center space-x-3 mb-6">
                            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-purple-500 to-pink-500">
                                <Brain className="h-5 w-5 text-white" />
                            </div>
                            <div>
                                <h3 className="text-xl font-bold text-slate-900 dark:text-slate-100">Digital Sales Representative (Rio)</h3>
                                <p className="text-sm text-slate-500 dark:text-slate-400">Modular Engine Configuration</p>
                            </div>
                        </div>

                        <div className="space-y-8">
                            {/* Modular Providers Selection */}
                            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                                {/* STT Selection */}
                                <div className="space-y-2">
                                    <label className="text-xs font-bold text-slate-500 ml-1 uppercase">STT (Hearing)</label>
                                    <select
                                        value={sttProvider}
                                        onChange={(e) => setSttProvider(e.target.value)}
                                        className="w-full p-4 rounded-xl border-2 border-slate-200 dark:border-slate-800 bg-white/40 dark:bg-slate-900/40 font-bold focus:border-violet-500 focus:outline-none transition-all cursor-pointer"
                                    >
                                        <option value="deepgram">Deepgram</option>
                                        <option value="sarvam">Sarvam</option>
                                        <option value="cartesia">Cartesia</option>
                                        <option value="elevenlabs">ElevenLabs</option>
                                        <option value="smallest">Smallest</option>
                                        <option value="groq">Groq</option>
                                        <option value="gladia">Gladia</option>
                                        <option value="assemblyai">AssemblyAI</option>
                                        <option value="ringg_ai">Ringg.ai</option>
                                        <option value="inworld">Inworld</option>
                                        <option value="azure">Azure</option>
                                        <option value="vachana">Vachana</option>
                                    </select>
                                </div>

                                {/* LLM Selection */}
                                <div className="space-y-2">
                                    <label className="text-xs font-bold text-slate-500 ml-1 uppercase">LLM (Thinking)</label>
                                    <select
                                        value={llmProvider}
                                        onChange={(e) => setLlmProvider(e.target.value)}
                                        className="w-full p-4 rounded-xl border-2 border-slate-200 dark:border-slate-800 bg-white/40 dark:bg-slate-900/40 font-bold focus:border-violet-500 focus:outline-none transition-all cursor-pointer"
                                    >
                                        <option value="mistral">Mistral</option>
                                        <option value="anthropic">Claude</option>
                                        <option value="google">Gemini</option>
                                        <option value="perplexity">Perplexity</option>
                                        <option value="openrouter">OpenRouter (Inference)</option>
                                        <option value="cerebras">Cerebras (Inference)</option>
                                        <option value="sarvam">Sarvam (Multilingual)</option>
                                        <option value="groq">Groq</option>
                                        <option value="mimo">Mimo</option>
                                        <option value="azure">Azure</option>
                                        <option value="smallest">Smallest</option>
                                        {/* <option value="airllm">AirLLM</option> */}
                                        <option value="inworld">Inworld</option>
                                    </select>
                                </div>

                                {/* TTS Selection */}
                                <div className="space-y-2">
                                    <label className="text-xs font-bold text-slate-500 ml-1 uppercase">TTS (Speaking)</label>
                                    <select
                                        value={ttsProvider}
                                        onChange={(e) => setTtsProvider(e.target.value)}
                                        className="w-full p-4 rounded-xl border-2 border-slate-200 dark:border-slate-800 bg-white/40 dark:bg-slate-900/40 font-bold focus:border-violet-500 focus:outline-none transition-all cursor-pointer"
                                    >
                                        <option value="cartesia">Cartesia</option>
                                        <option value="elevenlabs">ElevenLabs</option>
                                        <option value="sarvam">Sarvam</option>
                                        <option value="deepgram">Deepgram</option>
                                        <option value="mimo">Mimo</option>
                                        <option value="mistral">Mistral</option>
                                        <option value="smallest">Smallest</option>
                                        <option value="groq">Groq</option>
                                        <option value="inworld">Inworld</option>
                                        <option value="rime">Rime</option>
                                        <option value="polly">Polly</option>
                                        <option value="azure">Azure</option>
                                        <option value="kitten">Kitten (Local)</option>
                                        <option value="vachana">Vachana</option>
                                    </select>
                                </div>
                            </div>

                            {/* Response Verbosity */}
                            <div className="space-y-4">
                                <div className="flex items-center justify-between ml-1">
                                    <label htmlFor="response-verbosity" className="text-sm font-bold text-slate-700 dark:text-slate-300">Response Verbosity</label>
                                    <span className={`text-xs font-bold px-2 py-1 rounded-md ${aiVerbosity === "1" ? "bg-red-500/10 text-red-500" :
                                        aiVerbosity === "3" ? "bg-blue-500/10 text-blue-500" :
                                            "bg-green-500/10 text-green-500"
                                        }`}>
                                        {aiVerbosity === "1" ? "Ultra-Concise" : aiVerbosity === "3" ? "Detailed" : "Balanced"}
                                    </span>
                                </div>
                                <div className="relative pt-1 px-1">
                                    <input
                                        id="response-verbosity"
                                        type="range"
                                        min="1"
                                        max="3"
                                        step="1"
                                        value={aiVerbosity}
                                        onChange={(e) => setAiVerbosity(e.target.value)}
                                        className="w-full h-2 bg-slate-200 dark:bg-slate-700 rounded-lg appearance-none cursor-pointer accent-violet-600"
                                    />
                                    <div className="flex justify-between mt-2 px-1">
                                        <span className="text-[10px] font-bold text-slate-400 uppercase tracking-tighter">Brevity</span>
                                        <span className="text-[10px] font-bold text-slate-400 uppercase tracking-tighter">Depth</span>
                                    </div>
                                    <p className="text-xs text-slate-500 dark:text-slate-400 mt-2 italic ml-1">
                                        {aiVerbosity === "1" && "Rio will stick to 1 short sentence or even 1 word."}
                                        {aiVerbosity === "2" && "Rio will provide concise 1-3 sentence answers."}
                                        {aiVerbosity === "3" && "Rio will provide elaborate, detailed explanations."}
                                    </p>
                                </div>
                            </div>

                            {/* Evaluation Judge */}
                            <div className="space-y-4 rounded-2xl border border-violet-500/20 bg-violet-500/5 p-5">
                                <div>
                                    <p className="text-sm font-bold text-slate-700 dark:text-slate-300">Evaluation Judge</p>
                                    <p className="text-xs text-slate-500 mt-0.5">LLM that scores each call on 6 quality axes after the call ends. Independent from the voice agent LLM.</p>
                                </div>
                                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                                    <div className="space-y-2">
                                        <label className="text-xs font-bold text-slate-500 ml-1 uppercase">Evaluation Judge Provider</label>
                                        <select
                                            value={evalJudgeProvider}
                                            onChange={(e) => setEvalJudgeProvider(e.target.value)}
                                            className="w-full p-4 rounded-xl border-2 border-slate-200 dark:border-slate-800 bg-white/40 dark:bg-slate-900/40 font-bold focus:border-violet-500 focus:outline-none transition-all cursor-pointer"
                                        >
                                            <option value="">Auto-detect from API keys</option>
                                            <option value="mistral">Mistral</option>
                                            <option value="openai">OpenAI</option>
                                            <option value="gemini">Gemini</option>
                                            <option value="claude">Claude</option>
                                            <option value="groq">Groq</option>
                                        </select>
                                        <p className="text-[11px] text-slate-500 ml-1">Leave blank → auto-pick based on which API key is set</p>
                                    </div>
                                    <div className="space-y-2">
                                        <label className="text-xs font-bold text-slate-500 ml-1 uppercase">Evaluation Judge Model</label>
                                        <input
                                            type="text"
                                            value={evalJudgeModel}
                                            onChange={(e) => setEvalJudgeModel(e.target.value)}
                                            placeholder="Leave blank for provider default"
                                            className="w-full p-4 rounded-xl border-2 border-slate-200 dark:border-slate-800 bg-white/40 dark:bg-slate-900/40 font-bold focus:border-violet-500 focus:outline-none transition-all"
                                        />
                                        <p className="text-[11px] text-slate-500 ml-1">Defaults: mistral-large-latest · gpt-4o-mini · gemini-1.5-flash · claude-haiku-4-5 · llama-3.1-8b-instant</p>
                                    </div>
                                </div>
                            </div>

                            {/* System Instructions */}
                            <div className="space-y-2">
                                <label className="text-sm font-bold text-slate-700 dark:text-slate-300 ml-1">System Instructions / Script</label>
                                {loading ? (
                                    <div className="h-64 rounded-xl border border-dashed border-slate-300 dark:border-slate-600 flex items-center justify-center bg-slate-50 dark:bg-slate-900/40">
                                        <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
                                    </div>
                                ) : (
                                    <textarea
                                        value={systemInstruction}
                                        onChange={(e) => setSystemInstruction(e.target.value)}
                                        className="w-full h-80 rounded-xl border border-slate-200 dark:border-white/10 bg-white/80 dark:bg-slate-800/60 backdrop-blur-sm p-4 text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-violet-400 shadow-sm font-mono text-sm leading-relaxed"
                                        placeholder="Paste your AI persona script here..."
                                    />
                                )}
                            </div>
                        </div>
                    </div>
                )}


                {/* Company Prompts — versioned prompt history */}
                {activeSection === "voice_ai" && hasAdminAccess && (
                    <div className="rounded-2xl glass p-6 border border-white/40 dark:border-white/10 space-y-5 mt-6">
                        <div className="flex items-center gap-3">
                            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-purple-500 to-indigo-600">
                                <Layers className="h-5 w-5 text-white" />
                            </div>
                            <div>
                                <h3 className="text-lg font-bold text-slate-900 dark:text-slate-100">Company Prompt Versions</h3>
                                <p className="text-sm text-slate-500 dark:text-slate-400">Versioned system prompts — save a new version and activate it company-wide</p>
                            </div>
                        </div>
                        {/* New version form */}
                        <div className="space-y-3 p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/40">
                            <label className="text-xs font-semibold text-slate-500 uppercase">New Prompt Version</label>
                            <textarea
                                rows={8}
                                value={newPromptText}
                                onChange={e => setNewPromptText(e.target.value)}
                                placeholder="Paste the new system prompt here…"
                                className="w-full p-3 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 font-mono focus:outline-none focus:ring-2 focus:ring-violet-500 resize-y"
                            />
                            <input
                                type="text"
                                value={newPromptReason}
                                onChange={e => setNewPromptReason(e.target.value)}
                                placeholder="Change reason (optional)"
                                className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500"
                            />
                            <div className="flex items-center gap-3">
                                <button onClick={saveCompanyPrompt} disabled={promptSaving || !newPromptText.trim()} className="flex items-center gap-2 px-4 py-2 rounded-lg bg-violet-600 text-white text-sm font-semibold hover:bg-violet-700 disabled:opacity-50 transition-colors">
                                    {promptSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                                    Save New Version
                                </button>
                                {promptSaved && <span className="text-sm text-emerald-600 font-semibold flex items-center gap-1"><CheckCircle2 className="h-4 w-4" /> Saved</span>}
                            </div>
                        </div>
                        {}
                        {companyPrompts.length > 0 && (
                            <div className="space-y-2">
                                <label className="text-xs font-semibold text-slate-500 uppercase">Version History</label>
                                {companyPrompts.map(p => (
                                    <div key={p.id} className={`rounded-lg border p-3 flex items-start gap-3 ${p.is_active ? "border-violet-400 bg-violet-50 dark:bg-violet-950/20" : "border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/30"}`}>
                                        <div className="flex-1 min-w-0">
                                            <div className="flex items-center gap-2 mb-1">
                                                <span className="text-xs font-bold text-slate-500">v{p.version}</span>
                                                {p.is_active && <span className="px-1.5 py-0.5 rounded bg-violet-100 dark:bg-violet-900/40 text-violet-700 dark:text-violet-300 text-xs font-bold">active</span>}
                                                {p.change_reason && <span className="text-xs text-slate-400 truncate">{p.change_reason}</span>}
                                            </div>
                                            <pre className="text-xs text-slate-600 dark:text-slate-400 font-mono whitespace-pre-wrap line-clamp-3">{p.prompt_text}</pre>
                                        </div>
                                        {!p.is_active && (
                                            <button onClick={() => activatePrompt(p.id)} className="shrink-0 flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-violet-600 text-white text-xs font-semibold hover:bg-violet-700 transition-colors">
                                                <Play className="h-3 w-3" /> Activate
                                            </button>
                                        )}
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                )}

                {/* Provider Credentials Tab */}
                {activeSection === "credentials" && hasAdminAccess && (
                    <div className="rounded-2xl glass p-6 border border-white/40 dark:border-white/10 space-y-6">
                        <div className="flex items-center gap-3">
                            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-teal-500 to-emerald-600">
                                <Database className="h-5 w-5 text-white" />
                            </div>
                            <div>
                                <h3 className="text-lg font-bold text-slate-900 dark:text-slate-100">Provider Credentials</h3>
                                <p className="text-sm text-slate-500 dark:text-slate-400">Encrypted per-provider API keys managed separately from integration settings</p>
                            </div>
                        </div>
                        {/* Add credential form */}
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/40">
                            <div>
                                <label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Provider</label>
                                <select value={credForm.provider} onChange={e => setCredForm(p => ({ ...p, provider: e.target.value }))} className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500">
                                    {["deepgram","cartesia","openai","mistral","anthropic","elevenlabs","twilio","plivo","exotel","vobiz","groq","azure","aws"].map(p => <option key={p} value={p}>{p}</option>)}
                                </select>
                            </div>
                            <div>
                                <label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Key Name</label>
                                <input type="text" value={credForm.key_name} onChange={e => setCredForm(p => ({ ...p, key_name: e.target.value }))} placeholder="API_KEY" className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm font-mono text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500" />
                            </div>
                            <div>
                                <label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Value</label>
                                <div className="flex gap-2">
                                    <input type="password" value={credForm.value} onChange={e => setCredForm(p => ({ ...p, value: e.target.value }))} placeholder="sk-…" className="flex-1 p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm font-mono text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500" />
                                    <button onClick={saveProviderCred} disabled={credSaving || !credForm.value.trim()} className="px-3 py-2 rounded-lg bg-violet-600 text-white text-sm font-semibold hover:bg-violet-700 disabled:opacity-50 transition-colors">
                                        {credSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                                    </button>
                                </div>
                            </div>
                            {credError && <div className="col-span-3 text-sm text-red-600">{credError}</div>}
                            {credSuccess && <div className="col-span-3 text-sm text-emerald-600 font-semibold flex items-center gap-1"><CheckCircle2 className="h-4 w-4" /> Saved</div>}
                        </div>
                        {/* Credentials list */}
                        {providerCreds.length === 0 ? (
                            <p className="text-sm text-slate-400 text-center py-8">No credentials stored yet.</p>
                        ) : (
                            <div className="border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden">
                                <table className="w-full text-sm">
                                    <thead className="bg-slate-50 dark:bg-slate-900/60 text-xs uppercase text-slate-500">
                                        <tr>
                                            <th className="px-4 py-2 text-left">Provider</th>
                                            <th className="px-4 py-2 text-left">Key Name</th>
                                            <th className="px-4 py-2 text-left">Value</th>
                                            <th className="px-4 py-2"></th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
                                        {providerCreds.map(c => (
                                            <tr key={c.id}>
                                                <td className="px-4 py-2.5 font-medium text-slate-700 dark:text-slate-300">{c.provider}</td>
                                                <td className="px-4 py-2.5 font-mono text-slate-500">{c.key_name}</td>
                                                <td className="px-4 py-2.5 font-mono text-slate-400">●●●●●●●●</td>
                                                <td className="px-4 py-2.5 text-right">
                                                    <button onClick={() => deleteProviderCred(c.id)} className="p-1.5 text-slate-400 hover:text-red-500 transition-colors"><Trash2 className="h-4 w-4" /></button>
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </div>
                )}

                {/* Webhooks Tab */}
                {activeSection === "webhooks" && hasAdminAccess && (
                    <div className="space-y-6">
                        <div className="rounded-2xl glass p-6 border border-white/40 dark:border-white/10 space-y-5">
                            <div className="flex items-center justify-between">
                                <div className="flex items-center gap-3">
                                    <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-blue-500 to-indigo-600">
                                        <Webhook className="h-5 w-5 text-white" />
                                    </div>
                                    <div>
                                        <h3 className="text-lg font-bold text-slate-900 dark:text-slate-100">Webhooks</h3>
                                        <p className="text-sm text-slate-500 dark:text-slate-400">Register outbound endpoints — Rio POSTs events to each active webhook</p>
                                    </div>
                                </div>
                                <button onClick={() => openWebhookModal("new")} className="flex items-center gap-2 px-4 py-2 rounded-lg bg-violet-600 text-white text-sm font-semibold hover:bg-violet-700 transition-colors">
                                    <Plus className="h-4 w-4" /> Add Webhook
                                </button>
                            </div>
                            {webhooks.length === 0 ? (
                                <p className="text-center text-slate-400 text-sm py-8">No webhooks yet. Click &ldquo;Add Webhook&rdquo; to register an endpoint.</p>
                            ) : (
                                <div className="space-y-3">
                                    {webhooks.map(w => (
                                        <div key={w.id} className="flex items-start gap-4 p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/30">
                                            <div className="flex-1 min-w-0">
                                                <div className="flex items-center gap-2 mb-1">
                                                    <span className="font-semibold text-slate-800 dark:text-slate-200">{w.name}</span>
                                                    <span className={`px-1.5 py-0.5 rounded text-xs font-bold ${w.is_active ? "bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300" : "bg-slate-100 dark:bg-slate-800 text-slate-500"}`}>
                                                        {w.is_active ? "active" : "paused"}
                                                    </span>
                                                </div>
                                                <div className="flex items-center gap-1.5 text-xs text-slate-400 mb-2">
                                                    <ExternalLink className="h-3 w-3 shrink-0" />
                                                    <span className="font-mono truncate">{w.url}</span>
                                                </div>
                                                <div className="flex flex-wrap gap-1">
                                                    {w.events.map(e => <span key={e} className="px-1.5 py-0.5 rounded bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-300 text-xs">{e}</span>)}
                                                </div>
                                            </div>
                                            <div className="flex items-center gap-1 shrink-0">
                                                <button onClick={() => testWebhook(w.id)} disabled={testingWebhook === w.id} title="Send test event" className="p-1.5 text-slate-400 hover:text-blue-500 transition-colors disabled:opacity-50">
                                                    {testingWebhook === w.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                                                </button>
                                                <button onClick={() => openWebhookModal(w)} className="p-1.5 text-slate-400 hover:text-violet-500 transition-colors">
                                                    <Settings className="h-4 w-4" />
                                                </button>
                                                <button onClick={() => deleteWebhook(w.id)} className="p-1.5 text-slate-400 hover:text-red-500 transition-colors">
                                                    <Trash2 className="h-4 w-4" />
                                                </button>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>

                        {/* Available events reference */}
                        {availableEvents.length > 0 && (
                            <div className="rounded-2xl glass p-6 border border-white/40 dark:border-white/10 space-y-3">
                                <h4 className="font-bold text-slate-700 dark:text-slate-300">Available Event Types</h4>
                                <div className="flex flex-wrap gap-2">
                                    {availableEvents.map((e: any) => {
                                        const eventKey = typeof e === "string" ? e : e.key;
                                        return (
                                            <button key={eventKey} onClick={() => navigator.clipboard.writeText(eventKey)} className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs font-mono text-slate-600 dark:text-slate-300 hover:bg-violet-50 dark:hover:bg-violet-900/20 transition-colors" title="Click to copy">
                                                <Copy className="h-3 w-3" />{eventKey}
                                            </button>
                                        );
                                    })}
                                </div>
                            </div>
                        )}

                        {/* Delivery logs */}
                        {webhookLogs.length > 0 && (
                            <div className="rounded-2xl glass p-6 border border-white/40 dark:border-white/10 space-y-3">
                                <h4 className="font-bold text-slate-700 dark:text-slate-300">Recent Delivery Logs</h4>
                                <div className="space-y-1.5 max-h-64 overflow-y-auto">
                                    {webhookLogs.slice(0, 50).map(log => {
                                        const isSuccess = log.http_status ? (log.http_status >= 200 && log.http_status < 300) : false;
                                        return (
                                            <div key={log.id} className="flex items-center gap-3 px-3 py-2 rounded-lg border border-slate-100 dark:border-slate-800 text-xs">
                                                {isSuccess ? <CheckCircle className="h-3.5 w-3.5 text-emerald-500 shrink-0" /> : <XCircle className="h-3.5 w-3.5 text-red-500 shrink-0" />}
                                                <span className={`font-mono ${isSuccess ? "text-slate-600 dark:text-slate-300" : "text-red-600 dark:text-red-400"}`}>{log.event_type}</span>
                                                {log.http_status && <span className="text-slate-400">HTTP {log.http_status}</span>}
                                                {log.error && <span className="text-red-500 truncate">{log.error}</span>}
                                                <span className="ml-auto text-slate-400">{new Date(log.created_at).toLocaleString()}</span>
                                            </div>
                                        );
                                    })}
                                </div>
                            </div>
                        )}
                    </div>
                )}

                {/* SIP Trunks Tab */}
                {activeSection === "sip_trunks" && hasAdminAccess && (
                    <div className="rounded-2xl glass p-6 border border-white/40 dark:border-white/10 space-y-5">
                        <div className="flex items-center justify-between">
                            <div className="flex items-center gap-3">
                                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-orange-500 to-red-600">
                                    <Server className="h-5 w-5 text-white" />
                                </div>
                                <div>
                                    <h3 className="text-lg font-bold text-slate-900 dark:text-slate-100">SIP Trunks</h3>
                                    <p className="text-sm text-slate-500 dark:text-slate-400">Register external SIP trunks for telephony routing</p>
                                </div>
                            </div>
                            <button onClick={() => openSipModal("new")} className="flex items-center gap-2 px-4 py-2 rounded-lg bg-violet-600 text-white text-sm font-semibold hover:bg-violet-700 transition-colors">
                                <Plus className="h-4 w-4" /> Add Trunk
                            </button>
                        </div>
                        {sipTrunks.length === 0 ? (
                            <p className="text-center text-slate-400 text-sm py-8">No SIP trunks configured.</p>
                        ) : (
                            <div className="border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden">
                                <table className="w-full text-sm">
                                    <thead className="bg-slate-50 dark:bg-slate-900/60 text-xs uppercase text-slate-500">
                                        <tr>
                                            <th className="px-4 py-2 text-left">Name</th>
                                            <th className="px-4 py-2 text-left">Host</th>
                                            <th className="px-4 py-2 text-left">Provider</th>
                                            <th className="px-4 py-2 text-left">Status</th>
                                            <th className="px-4 py-2"></th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
                                        {sipTrunks.map(t => (
                                            <tr key={t.id}>
                                                <td className="px-4 py-2.5">
                                                    <div className="font-medium text-slate-800 dark:text-slate-200">{t.name}</div>
                                                    {t.is_default && <span className="text-xs text-violet-600 dark:text-violet-400 font-semibold">default</span>}
                                                </td>
                                                <td className="px-4 py-2.5 font-mono text-slate-500 text-xs">{t.host}:{t.port}</td>
                                                <td className="px-4 py-2.5 text-slate-500">{t.provider}</td>
                                                <td className="px-4 py-2.5">
                                                    <span className={`px-2 py-0.5 rounded text-xs font-semibold ${t.status === "active" ? "bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300" : "bg-slate-100 dark:bg-slate-800 text-slate-500"}`}>{t.status}</span>
                                                </td>
                                                <td className="px-4 py-2.5 text-right">
                                                    <button onClick={() => openSipModal(t)} className="p-1.5 text-slate-400 hover:text-violet-500 transition-colors mr-1"><Settings className="h-4 w-4" /></button>
                                                    <button onClick={() => deleteSipTrunk(t.id)} className="p-1.5 text-slate-400 hover:text-red-500 transition-colors"><Trash2 className="h-4 w-4" /></button>
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </div>
                )}

                {/* Integrations Keys Tab */}
                {/* My Email Tab — visible to all roles */}
                {activeSection === "my_email" && (
                    <div className="space-y-6">
                        <div className="rounded-2xl glass p-6 border border-white/40 dark:border-white/10">
                            <div className="flex items-center justify-between mb-6">
                                <div className="flex items-center space-x-3">
                                    <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-blue-500 to-cyan-500">
                                        <Mail className="h-5 w-5 text-white" />
                                    </div>
                                    <div>
                                        <h3 className="text-xl font-bold text-slate-900 dark:text-slate-100">My Email Settings</h3>
                                        <p className="text-sm text-slate-500 dark:text-slate-400">
                                            Personal credentials — override company defaults for emails sent by you
                                        </p>
                                    </div>
                                </div>
                            </div>

                            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                                {/* Outbound SMTP */}
                                <div className="space-y-4 p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/40">
                                    <h4 className="font-bold text-slate-700 dark:text-slate-300">Outbound (SMTP)</h4>
                                    {[
                                        { key: "SMTP_HOST", label: "SMTP Server", placeholder: "mail.example.com", secret: false },
                                        { key: "SMTP_PORT", label: "SMTP Port", placeholder: "465 (SSL) · 587 (STARTTLS)", secret: false },
                                        { key: "SMTP_USERNAME", label: "Username / Login", placeholder: "you@example.com", secret: true },
                                        { key: "SMTP_PASSWORD", label: "Password", placeholder: "••••••••", secret: true },
                                        { key: "SMTP_FROM_EMAIL", label: "From Email", placeholder: "you@example.com", secret: false },
                                    ].map(({ key, label, placeholder, secret }) => (
                                        <div key={key} className="space-y-1">
                                            <label className="text-xs font-semibold text-slate-500 uppercase">{label}</label>
                                            <div className="relative">
                                                <input
                                                    type={secret && !visibleKeys[`me_${key}`] ? "password" : "text"}
                                                    placeholder={placeholder}
                                                    value={myEmail[key] || ""}
                                                    onChange={(e) => handleMyEmailChange(key, e.target.value)}
                                                    onFocus={() => {
                                                        if (String(myEmail[key]).startsWith("***")) handleMyEmailChange(key, "");
                                                    }}
                                                    className="w-full p-2.5 pr-10 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500 font-mono text-sm"
                                                />
                                                {secret && (
                                                    <button
                                                        type="button"
                                                        onClick={() => toggleKeyVisibility(`me_${key}`)}
                                                        className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                                                    >
                                                        {visibleKeys[`me_${key}`] ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                                                    </button>
                                                )}
                                            </div>
                                        </div>
                                    ))}
                                    <div className="space-y-1">
                                        <label className="text-xs font-semibold text-slate-500 uppercase">Security</label>
                                        <select
                                            value={myEmail["SMTP_SECURITY"] || "ssl"}
                                            onChange={(e) => handleMyEmailChange("SMTP_SECURITY", e.target.value)}
                                            className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500 text-sm"
                                        >
                                            <option value="ssl">SSL / TLS (port 465)</option>
                                            <option value="starttls">STARTTLS (port 587)</option>
                                            <option value="none">None / Plain (port 25)</option>
                                        </select>
                                    </div>
                                </div>

                                {/* Inbound IMAP */}
                                <div className="space-y-4 p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/40">
                                    <h4 className="font-bold text-slate-700 dark:text-slate-300">Inbound (IMAP)</h4>
                                    <p className="text-xs text-slate-500">Replies to emails sent by you will be pulled from this inbox every 3 minutes.</p>
                                    {[
                                        { key: "IMAP_SERVER", label: "IMAP Server", placeholder: "mail.example.com", secret: false },
                                        { key: "IMAP_PORT", label: "IMAP Port", placeholder: "993 (SSL) · 143 (STARTTLS)", secret: false },
                                        { key: "IMAP_USERNAME", label: "Username / Login", placeholder: "you@example.com", secret: true },
                                        { key: "IMAP_PASSWORD", label: "Password", placeholder: "••••••••", secret: true },
                                    ].map(({ key, label, placeholder, secret }) => (
                                        <div key={key} className="space-y-1">
                                            <label className="text-xs font-semibold text-slate-500 uppercase">{label}</label>
                                            <div className="relative">
                                                <input
                                                    type={secret && !visibleKeys[`me_${key}`] ? "password" : "text"}
                                                    placeholder={placeholder}
                                                    value={myEmail[key] || ""}
                                                    onChange={(e) => handleMyEmailChange(key, e.target.value)}
                                                    onFocus={() => {
                                                        if (String(myEmail[key]).startsWith("***")) handleMyEmailChange(key, "");
                                                    }}
                                                    className="w-full p-2.5 pr-10 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500 font-mono text-sm"
                                                />
                                                {secret && (
                                                    <button
                                                        type="button"
                                                        onClick={() => toggleKeyVisibility(`me_${key}`)}
                                                        className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                                                    >
                                                        {visibleKeys[`me_${key}`] ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                                                    </button>
                                                )}
                                            </div>
                                        </div>
                                    ))}
                                    <div className="space-y-1">
                                        <label className="text-xs font-semibold text-slate-500 uppercase">Security</label>
                                        <select
                                            value={myEmail["IMAP_SECURITY"] || "ssl"}
                                            onChange={(e) => handleMyEmailChange("IMAP_SECURITY", e.target.value)}
                                            className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500 text-sm"
                                        >
                                            <option value="ssl">SSL / TLS (port 993)</option>
                                            <option value="starttls">STARTTLS (port 143)</option>
                                            <option value="none">None / Plain</option>
                                        </select>
                                    </div>

                                    <div className="pt-2 border-t border-slate-200 dark:border-slate-700">
                                        <button
                                            onClick={triggerInboxSync}
                                            disabled={syncingInbox}
                                            className="flex items-center space-x-2 px-4 py-2 rounded-xl border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-300 font-semibold hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-50 transition-all text-sm"
                                        >
                                            {syncingInbox ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                                            <span>Sync Inbox Now</span>
                                        </button>
                                        {syncResult && (
                                            <p className="mt-2 text-xs text-slate-500">{syncResult}</p>
                                        )}
                                    </div>
                                </div>
                            </div>

                            <p className="mt-4 text-xs text-slate-400 dark:text-slate-500">
                                Leave blank to use company-wide email settings. Your password is stored encrypted.
                            </p>
                        </div>

                        <div className="rounded-2xl glass p-6 border border-white/40 dark:border-white/10">
                            <div className="flex items-center justify-between mb-6">
                                <div className="flex items-center space-x-3">
                                    <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-500 to-teal-500">
                                        <PhoneForwarded className="h-5 w-5 text-white" />
                                    </div>
                                    <div>
                                        <h3 className="text-xl font-bold text-slate-900 dark:text-slate-100">My Warm Transfer</h3>
                                        <p className="text-sm text-slate-500 dark:text-slate-400">
                                            Personal handoff destination. Leave blank to use the company warm transfer number.
                                        </p>
                                    </div>
                                </div>
                            </div>

                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                <div className="space-y-1">
                                    <label className="text-xs font-semibold text-slate-500 uppercase">Transfer Number</label>
                                    <input
                                        type="text"
                                        placeholder="+919876543210"
                                        value={myWarmTransfer.WARM_TRANSFER_NUMBER || ""}
                                        onChange={(e) => handleMyWarmTransferChange("WARM_TRANSFER_NUMBER", e.target.value)}
                                        className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500 font-mono text-sm"
                                    />
                                </div>
                                <div className="space-y-1">
                                    <label className="text-xs font-semibold text-slate-500 uppercase">Transfer Name</label>
                                    <input
                                        type="text"
                                        placeholder="Sales manager"
                                        value={myWarmTransfer.WARM_TRANSFER_NAME || ""}
                                        onChange={(e) => handleMyWarmTransferChange("WARM_TRANSFER_NAME", e.target.value)}
                                        className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500 text-sm"
                                    />
                                </div>
                            </div>
                        </div>
                    </div>
                )}

                {activeSection === "api_keys" && hasAdminAccess && (
                    <div className="rounded-2xl glass p-6 border border-white/40 dark:border-white/10">
                        <div className="flex items-center space-x-3 mb-6">
                            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-green-400 to-emerald-600">
                                <KeyRound className="h-5 w-5 text-white" />
                            </div>
                            <div>
                                <h3 className="text-xl font-bold text-slate-900 dark:text-slate-100">API Credentials</h3>
                                <p className="text-sm text-slate-500 dark:text-slate-400">Securely store your provider keys in the encrypted database</p>
                            </div>
                        </div>

                        <div className="grid gap-6 md:grid-cols-2">
                            {Object.entries({
                                "Twilio & Messaging": ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_PHONE_NUMBER", "WHATSAPP_NUMBER"],
                                "Exotel (Telephony)": ["EXOTEL_ACCOUNT_SID", "EXOTEL_API_KEY", "EXOTEL_API_TOKEN", "EXOPHONE", "EXOTEL_APP_ID"],
                                "EnableX (Telephony)": ["ENABLEX_APP_ID", "ENABLEX_APP_KEY", "ENABLEX_FROM_NUMBER"],
                                "Plivo (Telephony)": ["PLIVO_AUTH_ID", "PLIVO_AUTH_TOKEN", "PLIVO_PHONE_NUMBER"],
                                "Vobiz (Telephony)": ["VOBIZ_AUTH_ID", "VOBIZ_AUTH_TOKEN", "VOBIZ_PHONE_NUMBER"],
                                "Warm Transfer": ["WARM_TRANSFER_NUMBER", "WARM_TRANSFER_NAME"],
                                "Speech-to-Text (STT)": ["DEEPGRAM_API_KEY", "SARVAM_API_KEY", "DEEPGRAM_STT_MODEL", "CARTESIA_STT_MODEL", "SARVAM_STT_MODEL", "ELEVENLABS_STT_MODEL", "DEEPGRAM_VOICE", "SMALLEST_STT_MODEL", "SMALLEST_VOICE_ID", "GROQ_STT_MODEL", "GROQ_VOICE", "GLADIA_API_KEY", "ASSEMBLYAI_API_KEY", "RINGG_AI_API_KEY", "GLADIA_STT_MODEL", "ASSEMBLYAI_STT_MODEL", "RINGG_AI_STT_MODEL", "INWORLD_API_KEY", "INWORLD_STT_MODEL", "AZURE_SPEECH_API_KEY", "AZURE_SPEECH_API_VERSION", "AZURE_SPEECH_REGION", "AZURE_STT_MODEL", "AZURE_SPEECH_ENDPOINT", "VACHANA_API_KEY", "VACHANA_STT_MODEL",],
                                "Text-to-Speech (TTS)": ["CARTESIA_API_KEY", "ELEVENLABS_API_KEY", "MIMO_API_KEY", "CARTESIA_VOICE_ID", "ELEVENLABS_VOICE_ID", "MIMO_VOICE_ID", "SARVAM_VOICE_ID", "DEEPGRAM_TTS_MODEL", "ELEVENLABS_TTS_MODEL", "MIMO_TTS_MODEL", "SARVAM_TTS_MODEL", "CARTESIA_TTS_MODEL", "MISTRAL_TTS_MODEL", "SMALLEST_TTS_MODEL", "MISTRAL_VOICE_ID", "GROQ_TTS_MODEL", "INWORLD_TTS_MODEL", "INWORLD_VOICE_ID", "RIME_API_KEY", "RIME_TTS_MODEL", "RIME_VOICE_ID", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_DEFAULT_REGION", "POLLY_TTS_MODEL", "POLLY_VOICE_ID", "AZURE_TTS_MODEL", "AZURE_VOICE_ID", "KITTEN_TTS_MODEL", "KITTEN_TTS_VOICE", "VACHANA_TTS_MODEL", "VACHANA_VOICE_ID",],
                                "Intelligence (LLM)": ["OPENAI_API_KEY", "MISTRAL_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "PERPLEXITY_API_KEY", "CEREBRAS_API_KEY", "OPENROUTER_API_KEY", "MIMO_API_KEY", "SMALLEST_API_KEY", "SMALLEST_LLM_MODEL", "MISTRAL_MODEL", "OPENAI_MODEL", "GEMINI_MODEL", "ANTHROPIC_MODEL", "PERPLEXITY_MODEL", "OPENROUTER_MODEL", "CEREBRAS_MODEL", "MIMO_MODEL", "SARVAM_MODEL", "GROQ_API_KEY", "GROQ_MODEL", "AZURE_LLM_API_KEY", "AZURE_LLM_MODEL", "AZURE_LLM_ENDPOINT", "AZURE_LLM_API_VERSION", "AZURE_LLM_REGION", "INWORLD_LLM_MODEL", "AIRLLM_MODEL", "AIRLLM_COMPRESSION", "AIRLLM_MAX_NEW_TOKENS",],
                                "Email (SMTP — Outbound)": ["SMTP_SERVER", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM_EMAIL"],
                                "Email (IMAP — Inbound)": ["IMAP_SERVER", "IMAP_PORT", "IMAP_USERNAME", "IMAP_PASSWORD"],
                                "Enrichment": ["APOLLO_API_KEY", "LUSHA_API_KEY", "ZOOMINFO_CLIENT_ID", "ZOOMINFO_API_KEY"],
                                "Forex (Currency Conversion)": ["API_LAYER_API_KEY"],
                                "Truecaller Business": ["TRUECALLER_KEY_ID", "TRUECALLER_API_KEY", "TRUECALLER_CLIENT_ACCOUNT_ID"]
                            }).map(([groupName, keys]) => (
                                <div key={groupName} className="space-y-4 p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/40">
                                    <h4 className="font-bold text-slate-700 dark:text-slate-300">{groupName}</h4>
                                    
                                    {keys.map((keyName) => (
                                        <div key={keyName} className="space-y-1">
                                            <label className="text-xs font-semibold text-slate-500 uppercase">{keyName.replace(/_/g, " ")}</label>
                                            <div className="relative group/key">
                                                <input
                                                    type={visibleKeys[keyName] || String(apiKeys[keyName]).startsWith("***") ? "text" : "password"}
                                                    placeholder={keyName.includes("PHONE") || keyName.includes("NUMBER") ? "+19014992283" : "sk-..."}
                                                    value={apiKeys[keyName] || ""}
                                                    onChange={(e) => handleKeyChange(keyName, e.target.value)}
                                                    onFocus={() => {
                                                        if (String(apiKeys[keyName]).indexOf("*") !== -1) {
                                                            handleKeyChange(keyName, "");
                                                        }
                                                    }}
                                                    className="w-full p-2.5 pr-10 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-violet-500 font-mono text-sm"
                                                />
                                                <button
                                                    type="button"
                                                    onClick={() => toggleKeyVisibility(keyName)}
                                                    className="absolute right-2.5 top-1/2 -translate-y-1/2 p-1 text-slate-400 hover:text-violet-500 transition-colors"
                                                    title={visibleKeys[keyName] ? "Hide Key" : "Show Key"}
                                                >
                                                    {visibleKeys[keyName] ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                                                </button>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            ))}
                        </div>
                    </div>
                )}

                {/* Usage Limits Tab */}
                {activeSection === "usage" && hasAdminAccess && (
                    <div className="rounded-2xl glass p-6 border border-white/40 dark:border-white/10 space-y-6">
                        <div className="flex items-center gap-3">
                            <Gauge className="h-6 w-6 text-violet-500" />
                            <div>
                                <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Usage Limits</h2>
                                <p className="text-sm text-slate-500 dark:text-slate-400">
                                    Override monthly limits per metric. Leave blank to use your plan&apos;s defaults.
                                    Set to <code className="text-xs bg-slate-100 dark:bg-slate-800 px-1 rounded">0</code> to block a feature entirely,
                                    or <code className="text-xs bg-slate-100 dark:bg-slate-800 px-1 rounded">unlimited</code> to remove the cap.
                                </p>
                            </div>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                            <div>
                                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">Calls (per month)</label>
                                <input
                                    type="text"
                                    value={usageLimitCalls}
                                    onChange={(e) => setUsageLimitCalls(e.target.value)}
                                    placeholder="Plan default"
                                    className="w-full rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 px-3 py-2 text-sm placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-violet-500"
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">Emails (per month)</label>
                                <input
                                    type="text"
                                    value={usageLimitEmails}
                                    onChange={(e) => setUsageLimitEmails(e.target.value)}
                                    placeholder="Plan default"
                                    className="w-full rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 px-3 py-2 text-sm placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-violet-500"
                                />
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">WhatsApp Messages (per month)</label>
                                <input
                                    type="text"
                                    value={usageLimitWhatsapp}
                                    onChange={(e) => setUsageLimitWhatsapp(e.target.value)}
                                    placeholder="Plan default"
                                    className="w-full rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 px-3 py-2 text-sm placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-violet-500"
                                />
                            </div>
                        </div>

                        <p className="text-xs text-slate-400 dark:text-slate-500">
                            These overrides are saved along with your other settings when you click <strong>Save Changes</strong>.
                            Changes take effect immediately — no restart needed.
                        </p>
                    </div>
                )}

                {/* Competitors Tab */}
                {activeSection === "competitors" && hasAdminAccess && (() => {
                    // Unified row list: union of tracked names (COMPETITOR_NAMES setting) and DB rows (competitorSummary). This means:
                    // Adding a name shows it immediately as a row before any call detects it. Competitors detected on calls also appear even if not in the tracked list
                    const parsedNames = competitorNames.split(",").map(s => s.trim().toLowerCase()).filter(Boolean);
                    const summaryMap = Object.fromEntries(competitorSummary.map(s => [s.competitor, s]));
                    const allNames = [...new Set([...parsedNames, ...Object.keys(summaryMap)])];
                    const rows = allNames.map(name => ({
                        competitor: name,
                        count: summaryMap[name]?.count ?? 0,
                        inTrackedList: parsedNames.includes(name) }));

                    return (
                    <div className="rounded-2xl glass p-6 border border-white/40 dark:border-white/10 space-y-6">
                        {/* Header */}
                        <div className="flex items-center space-x-3">
                            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-orange-400 to-red-500">
                                <Zap className="h-5 w-5 text-white" />
                            </div>
                            <div>
                                <h3 className="text-xl font-bold text-slate-900 dark:text-slate-100">Competitor Intelligence</h3>
                                <p className="text-sm text-slate-500 dark:text-slate-400">
                                    Rio detects these names live on calls. When detected, the counter-script is injected into the AI context automatically.
                                </p>
                            </div>
                        </div>

                        {/* Add competitor row */}
                        <div className="flex gap-2">
                            <input
                                type="text"
                                placeholder="Competitor name, e.g. salesforce"
                                value={newCompetitorName}
                                onChange={e => setNewCompetitorName(e.target.value)}
                                onKeyDown={e => { if (e.key === "Enter") addCompetitorToList(); }}
                                className="flex-1 p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500 text-sm"
                            />
                            <button
                                onClick={addCompetitorToList}
                                className="px-4 py-2 rounded-lg bg-violet-600 text-white text-sm font-semibold hover:bg-violet-700 transition-colors whitespace-nowrap"
                            >
                                + Add
                            </button>
                        </div>

                        {/* Unified table: one row per competitor */}
                        {rows.length === 0 ? (
                            <div className="text-center py-10 text-slate-400 text-sm">
                                No competitors tracked yet. Type a name above and click Add.
                                <br />
                                <span className="text-xs mt-1 block">If left empty, Rio uses built-in defaults: salesforce, hubspot, zoho, pipedrive…</span>
                            </div>
                        ) : (
                            <div className="space-y-3">
                                {rows.map(row => (
                                    <div key={row.competitor} className="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/40 overflow-hidden">
                                        {/* Row header */}
                                        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 dark:border-slate-700">
                                            <div className="flex items-center gap-3">
                                                <span className="font-semibold capitalize text-slate-800 dark:text-slate-200">{row.competitor}</span>
                                                {row.count > 0 && (
                                                    <span className="px-2 py-0.5 rounded-full bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-300 text-xs font-bold">
                                                        {row.count} mention{row.count !== 1 ? "s" : ""}
                                                    </span>
                                                )}
                                                {row.inTrackedList ? (
                                                    <span className="px-2 py-0.5 rounded-full bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300 text-xs">tracked</span>
                                                ) : (
                                                    <span className="px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-500 text-xs">detected on call</span>
                                                )}
                                            </div>
                                            <div className="flex items-center gap-2">
                                                {!row.inTrackedList && (
                                                    <button
                                                        onClick={() => {
                                                            const updated = [...parsedNames, row.competitor].join(", ");
                                                            setCompetitorNames(updated);
                                                            saveCompetitorNames(updated);
                                                        }}
                                                        className="text-xs px-2 py-1 rounded bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-300 hover:bg-violet-200 transition-colors"
                                                    >
                                                        + Track
                                                    </button>
                                                )}
                                                {row.inTrackedList && (
                                                    <button
                                                        onClick={() => removeCompetitorFromList(row.competitor)}
                                                        className="text-xs px-2 py-1 rounded bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400 hover:bg-red-200 transition-colors"
                                                    >
                                                        Remove
                                                    </button>
                                                )}
                                            </div>
                                        </div>

                                        {/* Counter-script input */}
                                        <div className="px-4 py-3 space-y-2">
                                            <label className="text-xs font-semibold text-slate-500 uppercase tracking-wide">Counter-Script (injected into AI when detected)</label>
                                            <textarea
                                                rows={2}
                                                placeholder={`What should Rio say when ${row.competitor} comes up? e.g. "We offer similar features at 30% less cost, and we integrate with your current stack…"`}
                                                value={counterScripts[row.competitor] ?? summaryMap[row.competitor]?.counter_script ?? ""}
                                                onChange={e => setCounterScripts(prev => ({ ...prev, [row.competitor]: e.target.value }))}
                                                className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500 text-sm resize-none"
                                            />
                                            <div className="flex items-center gap-3">
                                                <button
                                                    onClick={() => saveCounterScript(row.competitor)}
                                                    disabled={savingScript === row.competitor}
                                                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-violet-600 text-white text-xs font-semibold hover:bg-violet-700 transition-colors disabled:opacity-50"
                                                >
                                                    {savingScript === row.competitor ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
                                                    Save Script
                                                </button>
                                                {savingScript === null && counterScripts[row.competitor] !== undefined && (
                                                    <span className="text-xs text-slate-400">unsaved changes</span>
                                                )}
                                            </div>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}

                        {/* Save tracked list footer */}
                        <div className="flex items-center justify-between pt-2 border-t border-slate-200 dark:border-slate-700">
                            <p className="text-xs text-slate-400">
                                {parsedNames.length > 0
                                    ? `${parsedNames.length} competitor${parsedNames.length !== 1 ? "s" : ""} in your tracked list`
                                    : "Using built-in defaults"}
                            </p>
                            <div className="flex items-center gap-3">
                                {competitorSaved && <span className="text-xs text-green-600 font-medium flex items-center gap-1"><CheckCircle2 className="h-3.5 w-3.5" /> Saved</span>}
                                <button
                                    onClick={() => saveCompetitorNames()}
                                    disabled={savingCompetitors}
                                    className="flex items-center gap-2 px-4 py-2 rounded-lg bg-gradient-to-r from-violet-600 to-blue-600 text-white text-sm font-semibold hover:opacity-90 transition-opacity disabled:opacity-50"
                                >
                                    {savingCompetitors ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                                    Save Tracked List
                                </button>
                            </div>
                        </div>
                    </div>
                    );
                })()}

                {/* MCP Connections Tab */}
                {activeSection === "mcp_connections" && hasAdminAccess && (
                    <MCPConnectionsTab sessionTimeout={sessionTimeout} />
                )}

                {/* Finance Tabs */}
                {activeSection === "collections" && hasAdminAccess && (
                    <CollectionsTab sessionTimeout={sessionTimeout} />
                )}
                {activeSection === "scheme_claims" && hasAdminAccess && (
                    <SchemeClaimsTab sessionTimeout={sessionTimeout} />
                )}
                {activeSection === "books_sync" && hasAdminAccess && (
                    <BooksSyncTab sessionTimeout={sessionTimeout} />
                )}

                {/* Purchase Tabs */}
                {activeSection === "purchase_indents" && hasAdminAccess && (
                    <PurchaseIndentsTab sessionTimeout={sessionTimeout} />
                )}
                {activeSection === "purchase_orders" && hasAdminAccess && (
                    <div className="py-12 text-center text-slate-400 text-sm">Purchase Orders tab — coming next</div>
                )}
                {activeSection === "grn" && hasAdminAccess && (
                    <div className="py-12 text-center text-slate-400 text-sm">GRN & Receiving tab — coming next</div>
                )}

                {/* Inventory Sources Tab */}
                {activeSection === "inventory_sources" && hasAdminAccess && (
                    <div className="space-y-6">
                        <div className="rounded-2xl glass p-6 border border-white/40 dark:border-white/10 space-y-5">
                            <div className="flex items-center justify-between">
                                <div className="flex items-center gap-3">
                                    <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-green-500 to-teal-600">
                                        <Package className="h-5 w-5 text-white" />
                                    </div>
                                    <div>
                                        <h3 className="text-lg font-bold text-slate-900 dark:text-slate-100">Inventory Sources</h3>
                                        <p className="text-sm text-slate-500 dark:text-slate-400">The built-in Product catalog is always available. Add CSV or ERP sources to layer on top.</p>
                                    </div>
                                </div>
                                <button onClick={() => { setInvError(null); setInvForm({ name: "", source_type: "csv", priority: 80, config_json: "{}", enabled: true }); setInvModal("new"); }} className="flex items-center gap-2 px-3 py-2 rounded-lg bg-green-600 text-white text-sm font-semibold hover:bg-green-700 transition-colors">
                                    <Plus className="h-4 w-4" /> Add Source
                                </button>
                            </div>
                            <div className="rounded-xl border border-slate-200 dark:border-slate-700 p-4 bg-green-50/50 dark:bg-green-900/10">
                                <div className="flex items-center gap-3">
                                    <Database className="h-5 w-5 text-green-600" />
                                    <div>
                                        <p className="text-sm font-semibold text-slate-800 dark:text-slate-200">Product Catalog (built-in)</p>
                                        <p className="text-xs text-slate-500">Always enabled · priority 100 · queries your Products table</p>
                                    </div>
                                    <span className="ml-auto px-2 py-0.5 rounded-full text-xs font-semibold bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400">active</span>
                                </div>
                            </div>
                            {invSources.length === 0 ? (
                                <p className="text-sm text-slate-400 py-2 text-center">No additional sources configured.</p>
                            ) : (
                                <div className="overflow-x-auto">
                                    <table className="w-full text-sm">
                                        <thead><tr className="border-b border-slate-200 dark:border-slate-700 text-xs font-semibold text-slate-500 uppercase"><th className="text-left pb-2 pr-4">Name</th><th className="text-left pb-2 pr-4">Type</th><th className="text-left pb-2 pr-4">Priority</th><th className="text-left pb-2 pr-4">Last Sync</th><th className="text-left pb-2">Actions</th></tr></thead>
                                        <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                                            {invSources.map(s => (
                                                <tr key={s.id}>
                                                    <td className="py-3 pr-4 font-medium text-slate-900 dark:text-slate-100">{s.name}</td>
                                                    <td className="py-3 pr-4"><span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-teal-100 dark:bg-teal-900/30 text-teal-700 dark:text-teal-300">{s.source_type}</span></td>
                                                    <td className="py-3 pr-4 text-slate-600 dark:text-slate-300">{s.priority}</td>
                                                    <td className="py-3 pr-4 text-xs text-slate-400">{s.last_sync_at ? new Date(s.last_sync_at).toLocaleString() : "—"}</td>
                                                    <td className="py-3">
                                                        <div className="flex items-center gap-1">
                                                            <button title="Sync now" onClick={async () => { await apiFetch(`${CRM_BASE}/inventory-sources/${s.id}/sync`, { method: "POST" }).catch(() => {}); apiFetch(`${CRM_BASE}/inventory-sources`).then(r => r.ok ? r.json() : []).then(d => setInvSources(d as InvSource[])).catch(() => {}); }} className="p-1.5 rounded-lg text-slate-400 hover:text-green-600 hover:bg-green-50 dark:hover:bg-green-900/20 transition-colors"><RotateCcw className="h-4 w-4" /></button>
                                                            <button title="Edit" onClick={() => { setInvError(null); setInvForm({ name: s.name, source_type: s.source_type, priority: s.priority, config_json: "{}", enabled: s.enabled }); setInvModal(s); }} className="p-1.5 rounded-lg text-slate-400 hover:text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-900/20 transition-colors"><Settings className="h-4 w-4" /></button>
                                                            <button title="Delete" onClick={async () => { if (!confirm(`Delete "${s.name}"?`)) return; await apiFetch(`${CRM_BASE}/inventory-sources/${s.id}`, { method: "DELETE" }); setInvSources(p => p.filter(x => x.id !== s.id)); }} className="p-1.5 rounded-lg text-slate-400 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"><Trash2 className="h-4 w-4" /></button>
                                                        </div>
                                                    </td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                            )}
                        </div>
                    </div>
                )}

            </div>
            </>
            )}
        </div>

        {/* MCP Server modal */}
        {mcpModal !== null && (
            <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4" onClick={() => setMcpModal(null)}>
                <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-white/10 max-w-lg w-full max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
                    <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-white/10">
                        <h2 className="font-bold text-slate-900 dark:text-slate-100">{mcpModal === "new" ? "Add MCP Server" : "Edit MCP Server"}</h2>
                        <button onClick={() => setMcpModal(null)} className="text-slate-400 hover:text-slate-600"><XCircle className="h-5 w-5" /></button>
                    </div>
                    <div className="p-6 space-y-4">
                        {mcpError && <div className="text-sm text-red-600 bg-red-50 dark:bg-red-950/30 rounded-lg p-3">{mcpError}</div>}
                        <div className="grid grid-cols-2 gap-3">
                            <div className="col-span-2"><label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Name</label><input value={mcpForm.name} onChange={e => setMcpForm(p => ({ ...p, name: e.target.value }))} placeholder="apollo_main" className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500" /></div>
                            <div><label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Provider</label><select value={mcpForm.provider} onChange={e => setMcpForm(p => ({ ...p, provider: e.target.value }))} className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500"><option value="apollo">Apollo</option><option value="zoho">Zoho</option><option value="custom">Custom</option></select></div>
                            <div><label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Transport</label><select value={mcpForm.transport} onChange={e => setMcpForm(p => ({ ...p, transport: e.target.value }))} className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500"><option value="http">HTTP</option><option value="sse">SSE</option><option value="stdio">stdio</option></select></div>
                            <div className="col-span-2"><label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">URL</label><input value={mcpForm.url} onChange={e => setMcpForm(p => ({ ...p, url: e.target.value }))} placeholder="https://mcp.apollo.io/mcp" className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm font-mono text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500" /></div>
                            <div><label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Auth Type</label><select value={mcpForm.auth_type} onChange={e => setMcpForm(p => ({ ...p, auth_type: e.target.value }))} className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500"><option value="oauth2">OAuth 2.0</option><option value="api_key">API Key</option><option value="none">None</option></select></div>
                            <div><label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Priority</label><input type="number" value={mcpForm.priority} onChange={e => setMcpForm(p => ({ ...p, priority: Number(e.target.value) }))} className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500" /></div>
                            <div className="col-span-2 flex items-center gap-2"><input type="checkbox" id="mcp-enabled" checked={mcpForm.enabled} onChange={e => setMcpForm(p => ({ ...p, enabled: e.target.checked }))} className="w-4 h-4 accent-violet-600" /><label htmlFor="mcp-enabled" className="text-sm text-slate-700 dark:text-slate-300 cursor-pointer">Enabled</label></div>
                        </div>
                        <div className="flex justify-end gap-3 pt-2">
                            <button onClick={() => setMcpModal(null)} className="px-4 py-2 text-sm text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 transition-colors">Cancel</button>
                            <button disabled={mcpSaving || !mcpForm.name.trim() || !mcpForm.url.trim()} onClick={async () => { setMcpSaving(true); setMcpError(null); try { const isNew = mcpModal === "new"; const url = isNew ? `${API_BASE}/mcp-connections/registry` : `${API_BASE}/mcp-connections/registry/${(mcpModal as MCPServer).id}`; const res = await apiFetch(url, { method: isNew ? "POST" : "PATCH", body: JSON.stringify(mcpForm) }); if (!res.ok) { setMcpError((await res.json()).detail ?? "Save failed"); } else { const updated = await res.json(); setMcpServers(p => isNew ? [...p, updated] : p.map(x => x.id === updated.id ? updated : x)); setMcpModal(null); } } catch { setMcpError("Network error"); } finally { setMcpSaving(false); } }} className="flex items-center gap-2 px-4 py-2 rounded-lg bg-violet-600 text-white text-sm font-semibold hover:bg-violet-700 disabled:opacity-50 transition-colors">
                                {mcpSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Save
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        )}

        {/* Inventory Source modal */}
        {invModal !== null && (
            <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4" onClick={() => setInvModal(null)}>
                <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-white/10 max-w-lg w-full max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
                    <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-white/10">
                        <h2 className="font-bold text-slate-900 dark:text-slate-100">{invModal === "new" ? "Add Inventory Source" : "Edit Inventory Source"}</h2>
                        <button onClick={() => setInvModal(null)} className="text-slate-400 hover:text-slate-600"><XCircle className="h-5 w-5" /></button>
                    </div>
                    <div className="p-6 space-y-4">
                        {invError && <div className="text-sm text-red-600 bg-red-50 dark:bg-red-950/30 rounded-lg p-3">{invError}</div>}
                        <div className="grid grid-cols-2 gap-3">
                            <div className="col-span-2"><label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Name</label><input value={invForm.name} onChange={e => setInvForm(p => ({ ...p, name: e.target.value }))} placeholder="Warehouse CSV" className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500" /></div>
                            <div><label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Type</label><select value={invForm.source_type} onChange={e => setInvForm(p => ({ ...p, source_type: e.target.value }))} className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500"><option value="csv">CSV File</option><option value="google_sheets">Google Sheets</option><option value="erp_api">ERP API</option><option value="manual">Manual</option></select></div>
                            <div><label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Priority</label><input type="number" value={invForm.priority} onChange={e => setInvForm(p => ({ ...p, priority: Number(e.target.value) }))} className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500" /></div>
                            <div className="col-span-2"><label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Config (JSON)</label><textarea rows={4} value={invForm.config_json} onChange={e => setInvForm(p => ({ ...p, config_json: e.target.value }))} placeholder={'{"file_path": "/data/inventory.csv"}'} className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm font-mono text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500 resize-none" /></div>
                            <div className="col-span-2 flex items-center gap-2"><input type="checkbox" id="inv-enabled" checked={invForm.enabled} onChange={e => setInvForm(p => ({ ...p, enabled: e.target.checked }))} className="w-4 h-4 accent-violet-600" /><label htmlFor="inv-enabled" className="text-sm text-slate-700 dark:text-slate-300 cursor-pointer">Enabled</label></div>
                        </div>
                        <div className="flex justify-end gap-3 pt-2">
                            <button onClick={() => setInvModal(null)} className="px-4 py-2 text-sm text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 transition-colors">Cancel</button>
                            <button disabled={invSaving || !invForm.name.trim()} onClick={async () => { setInvSaving(true); setInvError(null); try { let cfg: Record<string, unknown> = {}; try { cfg = JSON.parse(invForm.config_json); } catch { setInvError("Config must be valid JSON"); setInvSaving(false); return; } const isNew = invModal === "new"; const url = isNew ? `${CRM_BASE}/inventory-sources` : `${CRM_BASE}/inventory-sources/${(invModal as InvSource).id}`; const res = await apiFetch(url, { method: isNew ? "POST" : "PATCH", body: JSON.stringify({ ...invForm, config_json: cfg }) }); if (!res.ok) { setInvError((await res.json()).detail ?? "Save failed"); } else { const updated = await res.json(); setInvSources(p => isNew ? [...p, updated] : p.map(x => x.id === updated.id ? updated : x)); setInvModal(null); } } catch { setInvError("Network error"); } finally { setInvSaving(false); } }} className="flex items-center gap-2 px-4 py-2 rounded-lg bg-green-600 text-white text-sm font-semibold hover:bg-green-700 disabled:opacity-50 transition-colors">
                                {invSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Save
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        )}

        {/* Webhook modal */}
        {webhookModal !== null && (
            <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4" onClick={() => setWebhookModal(null)}>
                <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-white/10 max-w-lg w-full max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
                    <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-white/10">
                        <h2 className="font-bold text-slate-900 dark:text-slate-100">{webhookModal === "new" ? "Add Webhook" : "Edit Webhook"}</h2>
                        <button onClick={() => setWebhookModal(null)} className="text-slate-400 hover:text-slate-600"><XCircle className="h-5 w-5" /></button>
                    </div>
                    <div className="p-6 space-y-4">
                        {webhookError && <div className="text-sm text-red-600 bg-red-50 dark:bg-red-950/30 rounded-lg p-3">{webhookError}</div>}
                        <div><label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Name</label>
                            <input value={webhookForm.name} onChange={e => setWebhookForm(p => ({ ...p, name: e.target.value }))} placeholder="Zapier CRM Sync" className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500" /></div>
                        <div><label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">URL</label>
                            <input value={webhookForm.url} onChange={e => setWebhookForm(p => ({ ...p, url: e.target.value }))} placeholder="https://hooks.zapier.com/…" className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm font-mono text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500" /></div>
                        <div><label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Events (select all that apply)</label>
                            <div className="flex flex-wrap gap-2 max-h-36 overflow-y-auto p-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/60">
                                {availableEvents.map((e: any) => {
                                    const eventKey = typeof e === "string" ? e : e.key;
                                    const eventLabel = typeof e === "string" ? e : e.label;
                                    const isSelected = webhookForm.events.includes(eventKey);
                                    return (
                                        <button
                                            key={eventKey}
                                            type="button"
                                            onClick={() => setWebhookForm(p => ({
                                                ...p,
                                                events: isSelected
                                                    ? p.events.filter(x => x !== eventKey)
                                                    : [...p.events, eventKey]
                                            }))}
                                            className={`px-2 py-0.5 rounded text-xs font-medium transition-colors ${
                                                isSelected
                                                    ? "bg-violet-600 text-white"
                                                    : "bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 text-slate-600 dark:text-slate-300 hover:bg-violet-50"
                                            }`}
                                        >
                                            {eventLabel}
                                        </button>
                                    );
                                })}
                            </div>
                        </div>
                        <div className="grid grid-cols-2 gap-3">
                            <div><label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Timeout (seconds)</label>
                                <input type="number" value={webhookForm.timeout_seconds} onChange={e => setWebhookForm(p => ({ ...p, timeout_seconds: Number(e.target.value) }))} className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500" /></div>
                            <div className="flex items-end pb-1"><label className="flex items-center gap-2 cursor-pointer"><input type="checkbox" checked={webhookForm.is_active} onChange={e => setWebhookForm(p => ({ ...p, is_active: e.target.checked }))} className="w-4 h-4 accent-violet-600" /><span className="text-sm text-slate-700 dark:text-slate-300">Active</span></label></div>
                        </div>
                        <div className="flex justify-end gap-3 pt-2">
                            <button onClick={() => setWebhookModal(null)} className="px-4 py-2 text-sm text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 transition-colors">Cancel</button>
                            <button onClick={saveWebhook} disabled={webhookSaving || !webhookForm.name.trim() || !webhookForm.url.trim()} className="flex items-center gap-2 px-4 py-2 rounded-lg bg-violet-600 text-white text-sm font-semibold hover:bg-violet-700 disabled:opacity-50 transition-colors">
                                {webhookSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Save
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        )}

        {/* SIP Trunk modal */}
        {sipModal !== null && (
            <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4" onClick={() => setSipModal(null)}>
                <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-white/10 max-w-lg w-full max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
                    <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-white/10">
                        <h2 className="font-bold text-slate-900 dark:text-slate-100">{sipModal === "new" ? "Add SIP Trunk" : "Edit SIP Trunk"}</h2>
                        <button onClick={() => setSipModal(null)} className="text-slate-400 hover:text-slate-600"><XCircle className="h-5 w-5" /></button>
                    </div>
                    <div className="p-6 space-y-4">
                        {sipError && <div className="text-sm text-red-600 bg-red-50 dark:bg-red-950/30 rounded-lg p-3">{sipError}</div>}
                        <div className="grid grid-cols-2 gap-3">
                            <div className="col-span-2"><label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Name</label><input value={sipForm.name} onChange={e => setSipForm(p => ({ ...p, name: e.target.value }))} placeholder="My SIP Trunk" className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500" /></div>
                            <div><label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Host</label><input value={sipForm.host} onChange={e => setSipForm(p => ({ ...p, host: e.target.value }))} placeholder="sip.provider.com" className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm font-mono text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500" /></div>
                            <div><label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Port</label><input type="number" value={sipForm.port} onChange={e => setSipForm(p => ({ ...p, port: Number(e.target.value) }))} className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm font-mono text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500" /></div>
                            <div><label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Transport</label><select value={sipForm.transport} onChange={e => setSipForm(p => ({ ...p, transport: e.target.value }))} className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500"><option value="udp">UDP</option><option value="tcp">TCP</option><option value="tls">TLS</option></select></div>
                            <div><label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Provider</label><input value={sipForm.provider} onChange={e => setSipForm(p => ({ ...p, provider: e.target.value }))} placeholder="generic_sip" className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500" /></div>
                            <div><label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Username</label><input value={sipForm.username} onChange={e => setSipForm(p => ({ ...p, username: e.target.value }))} className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm font-mono text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500" /></div>
                            <div className="col-span-2"><label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Password</label><input type="password" value={sipForm.password} onChange={e => setSipForm(p => ({ ...p, password: e.target.value }))} placeholder="Leave blank to keep existing" className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm font-mono text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500" /></div>
                            <div><label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">Codecs</label><input value={sipForm.codecs} onChange={e => setSipForm(p => ({ ...p, codecs: e.target.value }))} className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm font-mono text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500" /></div>
                            <div><label className="text-xs font-semibold text-slate-500 uppercase mb-1 block">DTMF Mode</label><select value={sipForm.dtmf_mode} onChange={e => setSipForm(p => ({ ...p, dtmf_mode: e.target.value }))} className="w-full p-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-violet-500"><option value="rfc2833">RFC 2833</option><option value="inband">In-band</option><option value="info">SIP INFO</option></select></div>
                            <div className="col-span-2 flex items-center gap-2"><input type="checkbox" id="sip-default" checked={sipForm.is_default} onChange={e => setSipForm(p => ({ ...p, is_default: e.target.checked }))} className="w-4 h-4 accent-violet-600" /><label htmlFor="sip-default" className="text-sm text-slate-700 dark:text-slate-300 cursor-pointer">Set as default trunk</label></div>
                        </div>
                        <div className="flex justify-end gap-3 pt-2">
                            <button onClick={() => setSipModal(null)} className="px-4 py-2 text-sm text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 transition-colors">Cancel</button>
                            <button onClick={saveSipTrunk} disabled={sipSaving || !sipForm.name.trim() || !sipForm.host.trim()} className="flex items-center gap-2 px-4 py-2 rounded-lg bg-violet-600 text-white text-sm font-semibold hover:bg-violet-700 disabled:opacity-50 transition-colors">
                                {sipSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Save
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        )}
        </>
    );
}
